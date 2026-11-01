# SideScreen

[简体中文](README.zh-CN.md) · English

SideScreen turns a second computer and a portrait display into a live dashboard for a source Mac. A small Python service collects metrics on the source; the display computer opens a read-only page in Firefox. It needs no desktop monitoring agent on the display computer and no cloud account.

The dashboard is designed to keep the existing CPU, memory, network, optional Gost routes, system information and top processes visible together on a portrait screen. Its interface is currently in Simplified Chinese; this documentation is available in English and Chinese.

## What it monitors

| Section | Information |
| --- | --- |
| CPU | Overall utilization, every logical core, 1/5/15-minute load averages, utilization history |
| Memory | Used and total memory, percentage, swap percentage, utilization history |
| Network | Download/upload rates from interface counters, shared chart scale and recent peak |
| Gost, optional | Local IPv4 listening ports, protocol, reachability, latency, last probe age and latency history; Gost PID/CPU/resident memory |
| System | Root filesystem usage, load averages, battery if present and number of displayed top processes |
| Processes | Six leading processes by CPU, with per-process CPU and memory percentages |
| Header/footer | Source hostname, sampling time, uptime, viewer clock, viewport size, connection and sample freshness |

CPU and memory charts use a fixed 0–100% scale. Network charts share a scale. Failed latency samples leave gaps instead of appearing as zero latency. Process CPU uses the per-core convention and can exceed 100%; the process list is six rows, not the total system process count. Names are currently limited to 20 characters by the sampler.

### Where the data comes from

System metrics come directly from `psutil` and operating-system counters. **This is not an OpenStats remote API, an OpenStats plugin, or a reader of OpenStats's private storage.** Running or signing into OpenStats is not required. Some monitoring concepts were inspired by OpenStats; SideScreen performs its own sampling.

The current network collector is macOS-oriented: it sums interfaces whose names begin with `en` or `bridge`, and excludes loopback and `utun`. It is not a per-application bandwidth meter; unusual bridge setups can still double-count traffic. Memory is `(total - available)`, and disk usage is the root filesystem, not a full APFS volume breakdown.

## Architecture and files

```text
Source computer                         Display computer
psutil + optional local Gost discovery
          ↓
Python threads → HTTP /metrics JSON → Firefox + dashboard.html
                     HTTP /           read-only charts and status
                     HTTP /healthz
```

```text
server.py                              HTTP server and in-memory samplers
dashboard.html                         Responsive UI; no CDN or build step
requirements.txt                       Pinned runtime dependency
tests/                                 Synthetic unit and HTTP contract tests
scripts/render_launchagent.py          Prints a per-user macOS service plist
deploy/com.example.sidescreen.plist.example
README.md / README.zh-CN.md
```

There is no database, persistence layer, login system, remote command API, fan control, process termination, or cleanup operation. Historical samples live only in memory and reset when the service restarts.

## Requirements and tested scope

- Source: macOS is the supported and tested baseline; Python 3.11+ and `psutil==7.2.2`. Development verification used Python 3.14. Other Python versions and operating systems have not been fully validated.
- Gost module: optional, macOS-oriented; uses `/usr/sbin/lsof`, a process named exactly `gost`, IPv4 listeners and unauthenticated HTTP or SOCKS5 proxies reachable through loopback. It neither installs nor configures Gost. IPv6-only listeners, authenticated proxies and listeners bound only to another address are outside its current supported scope.
- Viewer: Firefox is the primary portrait display browser. The page needs JavaScript, CSS Grid, Canvas 2D, Fetch and AbortController. No extension or screen-recording permission is required.
- Optional development checks: Node.js 22+ for the frontend test script; no npm packages.

The portrait layout was visually checked in Firefox at a **720×1195 CSS-pixel viewport** with browser bars visible. Additional Chromium viewport checks covered 720×1180, 720×1196, 720×1280, 1080×1820 and 1080×1920. High-resolution portrait checks were simulated; this does not certify every physical display/browser/zoom combination. No private screenshots or live measurements are included in this repository.

## Quick start on the source computer

```bash
git clone https://github.com/cnLuca0702/sidescreen.git
cd sidescreen
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Open `http://127.0.0.1:8790/` on the source computer. **By default the service binds only to loopback and Gost probes are disabled.** Stop a foreground service with `Ctrl+C`.

If a compatible Python is missing, install one through your usual trusted distribution before creating the virtual environment. A compatible prebuilt psutil wheel avoids a local compiler requirement; building psutil from source may require platform compiler/development tools.

### Configuration

```bash
.venv/bin/python server.py --help
.venv/bin/python server.py --host 127.0.0.1 --port 8790
# Optional: opt in to Gost discovery and external connectivity probes.
.venv/bin/python server.py --host 127.0.0.1 --port 8790 --enable-gost
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Address to bind; an explicit trusted LAN interface enables other devices to reach it |
| `--port` | `8790` | HTTP port; `0` selects an ephemeral port for tests |
| `--enable-gost` | Off | Discover Gost listeners and send the probes described below |

Sampling intervals and history limits are constants near the top of `server.py`: system sampling every 2 seconds, up to 150 points (about 5 minutes); Gost discovery every 30 seconds; nominal Gost probe cycles every 10 seconds, with 360 samples retained per port. Probes are processed serially by port, so multiple slow ports can extend a cycle and the history can span more than an hour.

### Show it on a trusted LAN display

1. Replace `YOUR_LAN_IP` with an address assigned to the **source computer's trusted LAN interface**. It is a placeholder, not a literal address to copy.
2. Start the source service with that interface explicitly selected:

   ```bash
   .venv/bin/python server.py --host YOUR_LAN_IP --port 8790
   ```

3. On the display computer, open **`http://YOUR_HOST:8790/`**, replacing `YOUR_HOST` with that source address or a locally resolvable name. `/index` serves the same dashboard.
4. If access is blocked, inspect your source firewall and network isolation rules and permit only the intended trusted scope. The project does not change those settings for you.

The viewer connects to the source computer, not to its own loopback address. Keep the source address stable using your network's normal address-management approach.

**HTTP has no authentication or TLS.** Every client able to reach the listener can read hostnames, process names/PIDs, usage and discovered proxy ports. Do not publish the port to the Internet, add a public tunnel or blindly forward it on a router. If an untrusted network is involved, first supply an appropriately authenticated/encrypted access layer outside this project.

## Firefox portrait display

Open the URL in Firefox on the display computer, keep JavaScript enabled, and use the browser's normal fullscreen mode if you want more room. Optional kiosk launch on macOS:

```bash
open -a Firefox --args --kiosk "http://YOUR_HOST:8790/"
```

An already running Firefox process may reuse an existing window; open fullscreen manually or close an existing instance yourself before using kiosk. The project does not install Firefox or automatically alter browser, display, screen-saver, login or sleep settings.

The portrait grid has CPU/memory side by side, a full-width network row, a full-width Gost section, and system/processes side by side. At wider portrait sizes, text and spacing increase. Normal 720-pixel portrait sizes preserve all four existing route cards, all logical-core bars and all six top-process rows. Very short windows, unusually long text or many extra proxy ports can require scrolling rather than silently hiding data. Very narrow phone layouts deliberately use an accessible single column.

The footer reports the **actual browser viewport**, which is smaller than the display resolution when browser bars are visible. First check the viewport, browser zoom and physical orientation when troubleshooting fit. Layout does not change the monitor resolution or rotation. After changing HTML, restart the source service and refresh the viewer; HTML is loaded into memory when the server starts.

## Refresh, stale data and disconnection

- System sampling is nominally every 2 seconds. Viewer polling waits 2 seconds after each completed request; a request is aborted after 5.5 seconds so slow requests do not accumulate.
- Network rates use actual sample timestamps, with a 2-second fallback for an older response format. Counter resets are clamped to zero.
- More than 8 seconds without an advancing system sample shows **采样已过期** (sample stale), including when HTTP responses still succeed.
- A failed request, or more than 6.5 seconds without a successful response, shows **连接中断** / **连接失败** (disconnected / connection failed). The last valid readings remain visible; successful polling restores live status.
- Each proxy port shows its last probe age. A probe older than 60 seconds is marked **已过期** (stale).
- A source computer that sleeps cannot supply new data. Decide your source/viewer sleep policy explicitly through the operating system; no such policy is installed automatically.

### Optional Gost probe traffic

With `--enable-gost`, SideScreen races an HTTP proxy HEAD request and a SOCKS5 CONNECT through each discovered local port toward **`cp.cloudflare.com:80`**, using `/generate_204` for HTTP. HTTP 2xx/3xx or a successful SOCKS5 CONNECT counts as reachable. It is a connectivity/latency indicator, not a throughput test or a proof that every destination works. HTTP proxy errors such as 407 and 502 are not counted as healthy.

This opt-in module makes outbound traffic and DNS resolution through the local proxy routes. It sends no CPU, memory, process list, hostname or stored credential to that destination. The system-only mode makes no such probe requests. Browser assets and metrics are served locally; there are no CDN assets or analytics scripts.

## Optional macOS login service

Run it first in the foreground and stop that instance before installing a background service. The template starts the **source service after that user logs in**; it is not a boot-time system daemon or a viewer kiosk installer. No administrator privileges are normally required.

```bash
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/SideScreen"
.venv/bin/python scripts/render_launchagent.py \
  --project-dir "$PWD" \
  --python "$PWD/.venv/bin/python" \
  --log-dir "$HOME/Library/Logs/SideScreen" \
  --host 127.0.0.1 --port 8790 \
  > "$HOME/Library/LaunchAgents/com.example.sidescreen.plist"
plutil -lint "$HOME/Library/LaunchAgents/com.example.sidescreen.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.example.sidescreen.plist"
```

For a LAN listener, substitute `YOUR_LAN_IP` after reviewing the exposure described above. Add `--enable-gost` to the renderer only if you want the optional external probes. The renderer prints configuration; it does not install a service, create log directories or change system settings. The example plist can also be edited manually by replacing every `YOUR_...` placeholder with an absolute path or selected value. Do not commit the rendered personal plist.

### Logs, restart and removal

The HTTP access log is silent. Startup and sampling/probe errors go to stdout/stderr; the template sends them to `~/Library/Logs/SideScreen/sidescreen.log`. Logs are not rotated automatically.

```bash
# Restart the installed service after updating code.
launchctl kickstart -k "gui/$(id -u)/com.example.sidescreen"
# Stop and unload it before removing the per-user configuration.
launchctl bootout "gui/$(id -u)/com.example.sidescreen"
rm "$HOME/Library/LaunchAgents/com.example.sidescreen.plist"
```

Removing this login item leaves the repository, virtual environment and logs intact. Review those local files before removing them separately. There is no project database or stored monitoring account to delete.

For rollback, stop the service, restore a previous trusted Git commit or reviewed file backup, reinstall its pinned requirements if needed, start the service and refresh the viewer. Keep local configuration/log backups outside Git. Do not overwrite uncommitted work to roll back.

## Development and checks

There is no frontend build or npm installation. `dashboard.html` is self-contained. If Node.js is unavailable, Python tests still run; frontend checks require Node.js 22+.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/frontend.test.cjs
.venv/bin/python -m py_compile server.py scripts/render_launchagent.py
```

Tests use synthetic metrics and loopback HTTP only. They do not require Gost, perform external probes, or modify the display/network. They cover history alignment, sample isolation, safe defaults, HTTP contract, template rendering, byte/rate calculations, escaping and connection-state transitions. Physical-screen acceptance remains a visual check on the actual viewer.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Source works, viewer cannot connect | Listener is loopback-only by default; select the trusted source LAN interface, verify the source URL, firewall and client isolation. Do not change router exposure blindly. |
| Address already in use | Stop the known instance or choose another `--port`; do not kill an unknown process. |
| Viewer still shows old layout | Restart the source (HTML is cached at startup), then refresh the viewer or open `/index`. |
| Some cards are missing below the screen | Check footer viewport/zoom, browser bars, orientation, unusually long values and route count. No metric is intentionally hidden to force fit. |
| Gost says 未启用 | Start with `--enable-gost` only if you want discovery and outbound probes. |
| Gost is absent or all ports fail | Verify exact process name `gost`, IPv4 loopback access, unauthenticated proxy support, `/usr/sbin/lsof`, and reachability of the probe destination. |
| Network rates are zero on another OS | The current interface-name filter is macOS-oriented. Other platforms are not fully supported. |
| Battery is absent | A desktop/no-battery source shows a desktop placeholder; this is expected. |
| JSON works but sample is stale | Inspect source sleep and sampler errors; receiving HTTP is not the same as receiving a new sample. |

## Privacy and publishing

Runtime metrics are intentionally visible to allowed viewers. The repository contains code, documentation, synthetic tests and parameterized templates only. Keep real deployment addresses, usernames, Wi-Fi settings, proxy configurations, secrets, logs, screenshots, raw snapshots, databases and virtual environments out of commits. The `.gitignore` is a convenience, not a substitute for reviewing the staged diff and Git history.

## License

A project license has not been selected. No `LICENSE` grant is included. Contact the repository owner about licensing. Runtime dependencies retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
