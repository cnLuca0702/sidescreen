#!/usr/bin/env python3
"""SideScreen: a local-first system dashboard with optional Gost probes.

- 系统指标每 2 秒采一次（psutil）
- Gost需显式 --enable-gost 启用；每30秒发现端口，名义探测周期10秒
  （HTTP HEAD 与 SOCKS5 CONNECT 竞速，目标 cp.cloudflare.com，与 OpenStats GostSampler 同口径）
- HTTP: /           仪表盘页面
        /metrics    最新快照 + 历史（JSON）
        /healthz    存活检查
"""

import argparse
import json
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

HOST = "127.0.0.1"
PORT = 8790
SAMPLE_INTERVAL = 2.0          # 系统指标采样周期
GOST_DISCOVERY_INTERVAL = 30.0 # gost 进程/端口发现周期
GOST_PROBE_INTERVAL = 10.0     # 线路探测周期
PROBE_TIMEOUT = 4.0
PROBE_HOST = "cp.cloudflare.com"
PROBE_PATH = "/generate_204"
HISTORY_POINTS = 150           # 系统指标历史：150 × 2s = 5 分钟
GOST_HISTORY_POINTS = 360      # 每端口360次探测；实际时间跨度取决于探测耗时

_process_name = "gost"

# ---------------------------------------------------------------- 系统指标

class SystemSampler(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="system-sampler")
        self.lock = threading.Lock()
        self.latest = {}
        self.cpu_history = deque(maxlen=HISTORY_POINTS)
        self.mem_history = deque(maxlen=HISTORY_POINTS)
        self.net_down_history = deque(maxlen=HISTORY_POINTS)
        self.net_up_history = deque(maxlen=HISTORY_POINTS)
        self.time_history = deque(maxlen=HISTORY_POINTS)
        psutil.cpu_percent(percpu=True)  # 先 priming 一次，下一次调用才有差值

    def _top_processes(self):
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = p.info
                if info["cpu_percent"] is None:
                    continue
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x["cpu_percent"] or 0, reverse=True)
        return [{"pid": p["pid"], "name": (p["name"] or "?")[:20],
                 "cpu": round(p["cpu_percent"] or 0, 1),
                 "mem": round(p["memory_percent"] or 0, 1)} for p in procs[:6]]

    def _sample(self):
        cpu_percpu = psutil.cpu_percent(percpu=True)
        cpu_total = sum(cpu_percpu) / len(cpu_percpu) if cpu_percpu else 0
        mem = psutil.virtual_memory()
        net = psutil.net_io_counters(pernic=True)
        # 只统计物理接口，剔除 utun/lo 等隧道环回，避免 gost 的探测流量被重复计入
        down = up = 0
        for name, stat in net.items():
            base = name.split(":")[0]
            if base.startswith(("en", "bridge")):
                down += stat.bytes_recv
                up += stat.bytes_sent
        disk = psutil.disk_usage("/")
        try:
            dio = psutil.disk_io_counters()
        except Exception:
            dio = None
        load1, load5, load15 = psutil.getloadavg()
        boot = psutil.boot_time()
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None

        snap = {
            "time": time.time(),
            "hostname": socket.gethostname(),
            "cpu": round(cpu_total, 1),
            "cpuPercpu": [round(x, 1) for x in cpu_percpu],
            "memUsedGB": round((mem.total - mem.available) / 2**30, 1),
            "memTotalGB": round(mem.total / 2**30, 1),
            "memPercent": round(mem.percent, 1),
            "swapPercent": round(psutil.swap_memory().percent, 1),
            "netDownBps": down,   # 累计字节数，由前端按两次差值算速率
            "netUpBps": up,
            "diskUsedGB": round(disk.used / 2**30, 1),
            "diskTotalGB": round(disk.total / 2**30, 1),
            "diskPercent": round(disk.percent, 1),
            "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
            "uptimeSec": int(time.time() - boot),
            "batteryPercent": round(battery.percent) if battery else None,
            "processes": self._top_processes(),
        }
        with self.lock:
            self.latest = snap
            self.cpu_history.append(snap["cpu"])
            self.mem_history.append(snap["memPercent"])
            self.net_down_history.append(down)
            self.net_up_history.append(up)
            self.time_history.append(snap["time"])

    def run(self):
        while True:
            start = time.time()
            try:
                self._sample()
            except Exception as exc:  # 采样失败不能挂掉服务
                print(f"[system] sample error: {exc}", flush=True)
            time.sleep(max(0.2, SAMPLE_INTERVAL - (time.time() - start)))

    def snapshot(self):
        with self.lock:
            return dict(self.latest), {
                "cpu": list(self.cpu_history),
                "mem": list(self.mem_history),
                "netDown": list(self.net_down_history),
                "netUp": list(self.net_up_history),
                "time": list(self.time_history),
            }


# ---------------------------------------------------------------- gost 探测

class PortProbe:
    def __init__(self, address, port, pid):
        self.address = address
        self.port = port
        self.pid = pid
        self.state = "pending"          # ok / failed / pending
        self.kind = None                # HTTP / SOCKS5
        self.milliseconds = None
        self.probedAt = 0
        self.latency_history = deque(maxlen=GOST_HISTORY_POINTS)  # (t, ms|None)

    @property
    def key(self):
        return f"{self.address}:{self.port}"


def _find_gost_ports():
    """找 gost 进程的 TCP 监听端口（地址, 端口, pid）。"""
    pids = [p.pid for p in psutil.process_iter(["name"])
            if (p.info.get("name") or "").lower() == _process_name]
    result = []
    for pid in pids:
        try:
            out = subprocess.run(
                ["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN", "-Fpn"],
                capture_output=True, text=True, timeout=10).stdout
        except Exception:
            continue
        current = None
        for line in out.splitlines():
            if line.startswith("p"):
                current = line[1:]
            elif line.startswith("n") and current:
                match = re.match(r"(\*|[\d.]+):(\d+)$", line[1:])
                if match:
                    address, port = match.group(1), int(match.group(2))
                    if address == "*":
                        address = "0.0.0.0"
                    result.append((address, port, pid))
    # 同一端口可能被多个进程监听（IPv4/IPv6 各一条），去重
    unique = {}
    for address, port, pid in result:
        unique[(address, port)] = pid
    return pids, [(a, p, pid) for (a, p), pid in unique.items()]


class _Race:
    """两个协议并发探测，第一个成功者生效（同 OpenStats GostSampler 的 ProbeRace）。"""
    def __init__(self):
        self.lock = threading.Lock()
        self.done = False

    def try_claim(self):
        with self.lock:
            if self.done:
                return False
            self.done = True
            return True


def _probe_http(port, winner, race, on_success):
    try:
        start = time.time()
        with socket.create_connection(("127.0.0.1", port), timeout=PROBE_TIMEOUT) as sock:
            sock.settimeout(PROBE_TIMEOUT)
            request = (f"HEAD http://{PROBE_HOST}{PROBE_PATH} HTTP/1.1\r\n"
                       f"Host: {PROBE_HOST}\r\nUser-Agent: SideScreen\r\n"
                       f"Proxy-Connection: close\r\n\r\n")
            sock.sendall(request.encode())
            data = sock.recv(128)
        match = re.match(rb"HTTP/\d(?:\.\d)?\s+([0-9]{3})\b", data)
        if match and 200 <= int(match.group(1)) < 400 and race.try_claim():
            on_success((time.time() - start) * 1000, "HTTP")
    except OSError:
        pass
    finally:
        winner()


def _probe_socks(port, winner, race, on_success):
    try:
        start = time.time()
        with socket.create_connection(("127.0.0.1", port), timeout=PROBE_TIMEOUT) as sock:
            sock.settimeout(PROBE_TIMEOUT)
            sock.sendall(b"\x05\x01\x00")                      # greeting：无需认证
            if not sock.recv(2).startswith(b"\x05\x00"):
                raise OSError("socks5 greeting rejected")
            host = PROBE_HOST.encode()
            sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + b"\x00\x50")
            reply = sock.recv(16)
            if len(reply) < 2 or reply[1] != 0:
                raise OSError("socks5 connect failed")
        if race.try_claim():
            on_success((time.time() - start) * 1000, "SOCKS5")
    except OSError:
        pass
    finally:
        winner()


class GostSampler(threading.Thread):
    daemon = True

    def __init__(self, enabled=False):
        super().__init__(name="gost-sampler")
        self.enabled = enabled
        self.lock = threading.Lock()
        self.ports = []            # [PortProbe]
        self.processes = []        # 进程信息（不含命令行，避免带出凭据）
        self._proc_cache = {}      # pid -> psutil.Process，跨轮缓存才能拿到 cpu_percent 差值
        self.next_discovery = 0
        self.next_probe = 0

    def _discover(self):
        pids, port_infos = _find_gost_ports()
        self._proc_cache = {pid: proc for pid, proc in self._proc_cache.items() if pid in pids}
        processes = []
        for pid in pids:
            try:
                p = self._proc_cache.setdefault(pid, psutil.Process(pid))
                processes.append({
                    "pid": pid,
                    "cpu": round(p.cpu_percent(interval=None), 1),
                    "memMB": round(p.memory_info().rss / 2**20, 1),
                    "uptimeSec": int(time.time() - p.create_time()),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        with self.lock:
            self.processes = processes
            known = {pp.key: pp for pp in self.ports}
            self.ports = []
            for address, port, pid in sorted(port_infos, key=lambda x: x[1]):
                pp = known.get(f"{address}:{port}")
                if pp is None:
                    pp = PortProbe(address, port, pid)
                pp.pid = pid
                self.ports.append(pp)

    def _probe_all(self):
        with self.lock:
            ports = list(self.ports)
        for pp in ports:
            race = _Race()
            counter = {"left": 2}
            cond = threading.Condition()
            result = {}

            def on_success(ms, kind):
                result["value"] = (ms, kind)

            def winner():
                with cond:
                    counter["left"] -= 1
                    if counter["left"] <= 0:
                        cond.notify_all()

            threads = [
                threading.Thread(target=_probe_http, args=(pp.port, winner, race, on_success), daemon=True),
                threading.Thread(target=_probe_socks, args=(pp.port, winner, race, on_success), daemon=True),
            ]
            for t in threads:
                t.start()
            with cond:
                cond.wait(PROBE_TIMEOUT + 0.5)
            now = time.time()
            if "value" in result:
                pp.state, pp.kind = "ok", result["value"][1]
                pp.milliseconds = round(result["value"][0], 0)
            else:
                pp.state, pp.milliseconds = "failed", None
            pp.probedAt = now
            pp.latency_history.append(pp.milliseconds)

    def run(self):
        while True:
            now = time.time()
            if now >= self.next_discovery:
                self.next_discovery = now + GOST_DISCOVERY_INTERVAL
                try:
                    self._discover()
                except Exception as exc:
                    print(f"[gost] discovery error: {exc}", flush=True)
            if now >= self.next_probe:
                self.next_probe = now + GOST_PROBE_INTERVAL
                try:
                    self._probe_all()
                except Exception as exc:
                    print(f"[gost] probe error: {exc}", flush=True)
            time.sleep(0.5)

    def snapshot(self):
        with self.lock:
            ports = [{
                "address": pp.address, "port": pp.port, "pid": pp.pid,
                "state": pp.state, "kind": pp.kind, "ms": pp.milliseconds,
                "probedAt": pp.probedAt,
                "history": list(pp.latency_history),
            } for pp in self.ports]
            processes = list(self.processes)
        ok_ports = [p for p in ports if p["state"] == "ok"]
        return {
            "enabled": self.enabled,
            "running": bool(processes),
            "ports": ports,
            "processes": processes,
            "upCount": len(ok_ports),
            "totalPorts": len(ports),
            "bestMs": min((p["ms"] for p in ok_ports), default=None),
        }


# ---------------------------------------------------------------- HTTP

system_sampler = SystemSampler()
gost_sampler = GostSampler()

DASHBOARD_HTML = Path(__file__).with_name("dashboard.html").read_bytes()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            body = DASHBOARD_HTML
            content_type = "text/html; charset=utf-8"
        elif self.path == "/metrics":
            snap, history = system_sampler.snapshot()
            payload = {"system": snap, "history": history,
                       "gost": gost_sampler.snapshot(), "serverTime": time.time(),
                       "sampleInterval": SAMPLE_INTERVAL}
            body = json.dumps(payload, ensure_ascii=False).encode()
            content_type = "application/json; charset=utf-8"
        elif self.path == "/healthz":
            body = b"ok"
            content_type = "text/plain; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 每两秒被轮询一次，静默访问日志


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="SideScreen local-first system dashboard")
    parser.add_argument("--host", default=HOST,
                        help="Bind address (default: %(default)s; use a trusted LAN interface explicitly)")
    parser.add_argument("--port", type=int, default=PORT,
                        help="HTTP port (default: %(default)s; 0 selects an ephemeral port)")
    parser.add_argument("--enable-gost", action="store_true",
                        help="Opt in to local Gost discovery and external connectivity probes")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    return args


def main(argv=None):
    args = parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    system_sampler.start()
    gost_sampler.enabled = args.enable_gost
    if args.enable_gost:
        gost_sampler.start()
    print(f"SideScreen listening on {args.host}:{server.server_port}; Gost probes {'enabled' if args.enable_gost else 'disabled'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
