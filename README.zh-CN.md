# SideScreen

简体中文 · [English](README.md)

SideScreen 把另一台电脑连接的竖屏变成源 Mac 的实时监控屏：源电脑运行轻量 Python 服务采集指标，显示电脑用 Firefox 打开只读网页。显示端无需安装采集代理，也不需要云账号。

页面将 CPU、内存、网络、可选 Gost 线路、系统信息和高占用进程集中在同一块竖屏中。当前界面使用简体中文，本项目提供详细中英文文档。

## 用途与监控内容

| 区域 | 显示内容 |
| --- | --- |
| CPU | 整机使用率、全部逻辑核心、1/5/15分钟平均负载、使用率走势 |
| 内存 | 已用/总量、使用百分比、交换空间百分比、走势 |
| 网络 | 从网卡累计计数计算的上下行速率、共用刻度图表、近期峰值 |
| Gost，可选 | 本地IPv4监听端口、协议、连通性、延迟、距上次探测时间、历史；Gost进程PID/CPU/常驻内存 |
| 系统 | 根文件系统用量、负载、有电池时的电量、已显示的进程项数 |
| 进程 | 按CPU排序的前六项，含CPU及内存占比 |
| 页头/页脚 | 源主机名、采样时间、运行时间、显示端时钟、实际视口、连接与采样新鲜度 |

CPU和内存图表固定使用0–100%刻度；上下行图表共用刻度。失败的延迟样本留空，不会伪装成零延迟。进程CPU使用单核口径，可以超过100%；六行进程不是系统总进程数，采集端目前把名称限制为20个字符。

### 数据来源，以及与OpenStats的关系

系统指标直接来自 `psutil` 和操作系统计数器。**本项目不是OpenStats远程API、不是其插件，也不读取其私有数据库或账号令牌。** 不需要安装或登录OpenStats。部分监控思路参考了OpenStats，SideScreen独立采样。

现有网络采集面向macOS：累加名称以 `en` 或 `bridge` 开头的接口，排除回环及 `utun`。它不是逐应用带宽统计，特殊桥接结构仍可能重复计数。内存按“总量减可用”计算；磁盘使用根文件系统口径，不提供完整APFS各卷拆分。

## 架构与目录

```text
源电脑                                  显示电脑
psutil + 可选本地Gost发现
          ↓
Python后台线程 → HTTP /metrics JSON → Firefox + dashboard.html
                      HTTP /          只读图表与状态
                      HTTP /healthz
```

```text
server.py                              HTTP服务与内存采样器
dashboard.html                         自适应页面，无CDN和前端构建步骤
requirements.txt                       固定运行依赖
tests/                                 合成数据单元测试与HTTP契约测试
scripts/render_launchagent.py          输出参数化的macOS用户登录服务配置
deploy/com.example.sidescreen.plist.example
README.md / README.zh-CN.md
```

没有数据库、账号登录、远程命令、风扇控制、进程终止或清理接口。历史只保存在服务进程内存中，重启后清空。

## 运行要求与已验证边界

- 源端以macOS为支持和测试基线；使用Python 3.11+、`psutil==7.2.2`。开发验证使用Python 3.14；其他Python版本和操作系统尚未完整验证。
- Gost模块可选，面向macOS：使用 `/usr/sbin/lsof`、名称严格为 `gost` 的进程、IPv4监听端口及可经本地回环访问的无认证HTTP/SOCKS5代理。不负责安装或配置Gost。仅IPv6、需要认证、仅绑定其他地址的代理不在当前支持范围内。
- Firefox是主要竖屏显示端；需要JavaScript、CSS Grid、Canvas 2D、Fetch、AbortController。无需浏览器插件或屏幕录制权限。
- 可选开发检查使用Node.js 22+，无需npm包。

已在Firefox真实竖屏、**720×1195 CSS像素视口**下查看一屏效果，包含可见浏览器栏。另在Chromium辅助检查720×1180、720×1196、720×1280、1080×1820、1080×1920；高分辨率竖屏检查属于模拟视口，不代表所有实体屏幕、缩放及浏览器组合均已测试。仓库不包含实际运行截图或真实采样数据。

## 源电脑快速运行

```bash
git clone https://github.com/cnLuca0702/sidescreen.git
cd sidescreen
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

在源电脑打开 `http://127.0.0.1:8790/`。**默认仅监听本机回环地址，Gost探测默认关闭。** 前台运行时按 `Ctrl+C` 停止。

如果没有兼容Python，请先通过平时信任的发行方式安装。psutil有可用预编译wheel时不需要本地编译；从源码构建可能需要平台编译器及开发工具。

### 配置

```bash
.venv/bin/python server.py --help
.venv/bin/python server.py --host 127.0.0.1 --port 8790
# 可选：明确开启Gost发现及对外连通性探测。
.venv/bin/python server.py --host 127.0.0.1 --port 8790 --enable-gost
```

| 参数 | 默认 | 用途 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 监听地址；明确选定可信局域网接口后其他设备才能访问 |
| `--port` | `8790` | HTTP端口；测试时可用0自动分配临时端口 |
| `--enable-gost` | 关闭 | 开启本地Gost端口发现及下文所述对外探测 |

采样间隔和历史上限位于 `server.py` 顶部：系统每2秒采样，最多150点，约5分钟；Gost每30秒发现端口，名义探测周期10秒，每端口最多保留360点。不同端口依次处理，多个慢端口会延长一轮探测，历史覆盖时间也可能超过1小时。

### 在可信局域网显示端访问

1. 把 `YOUR_LAN_IP` 替换为**源电脑可信局域网接口上实际配置的地址**；它是占位符，不能原样运行。
2. 在源电脑明确指定该接口：

   ```bash
   .venv/bin/python server.py --host YOUR_LAN_IP --port 8790
   ```

3. 在显示电脑打开 **`http://YOUR_HOST:8790/`**，把 `YOUR_HOST` 替换为上述源地址或本地可解析的主机名。`/index` 访问同一页面。
4. 若被阻挡，核对源端防火墙与网络隔离，只允许预期可信范围。项目不会替你调整这些设置。

显示端应连接源电脑，不能把源地址替换成显示端自己的回环地址。可通过网络原有的地址管理方式保持源地址稳定。

**服务没有身份认证或TLS。** 能访问监听端口的客户端都能读取主机名、进程名称/PID、使用量及发现的代理端口。不要把它直接发布到公网、添加公共隧道或盲目做路由器端口转发。如需跨不可信网络访问，应先在项目之外提供适当认证和加密访问层。

## Firefox竖屏使用

在显示电脑的Firefox打开页面；如需更多空间，使用浏览器正常的全屏功能。macOS可选kiosk启动示例：

```bash
open -a Firefox --args --kiosk "http://YOUR_HOST:8790/"
```

已有Firefox进程可能复用现有窗口；可手动全屏，或自行关闭旧实例再使用kiosk。项目不安装Firefox，不会自动更改浏览器、显示分辨率、旋转、屏保、自动登录或休眠设置。

竖屏采用“CPU/内存并排 → 网络整行 → Gost整行 → 系统/进程并排”的结构；更宽的高分辨率竖屏会增大字体和间距。在常规720像素竖屏中保留四条既有线路、全部逻辑核心条及六行进程。窗口过矮、文本异常长或代理端口特别多时允许滚动，而不静默隐藏信息；很窄的手机屏幕主动使用可访问的单列布局。

页脚显示**浏览器实际视口**；有浏览器栏时，它小于显示器分辨率。排查一屏显示时先查看视口、浏览器缩放和实体屏幕方向。页面不会更改显示器分辨率或旋转。修改HTML后需要重启源服务并刷新显示端，因为服务在启动时把HTML读入内存。

## 刷新、过期与断线状态

- 系统名义采样周期2秒。显示端每次请求完成后再等2秒；请求5.5秒后主动中止，避免慢请求堆积。
- 网速按真实采样时间差计算，兼容旧格式时回退为2秒；计数器重置导致的负值按零处理。
- 系统采样超过8秒未推进时显示“采样已过期”；即使HTTP一直返回成功，也能识别被冻结的读数。
- 请求失败或超过6.5秒没有成功响应时显示“连接中断/连接失败”；保留上次有效读数，成功后恢复实时状态。
- 每个代理端口显示距上次探测的时间，超过60秒标为“已过期”。
- 源电脑休眠时无法继续提供新采样。源端和显示端的常亮/休眠策略应由用户在系统中明确决定，本项目不自动配置。

### Gost可选探测的联网行为

开启 `--enable-gost` 后，每个发现的本地端口会并发尝试HTTP代理HEAD和SOCKS5 CONNECT，目标为 **`cp.cloudflare.com:80`**，HTTP路径为 `/generate_204`。HTTP 2xx/3xx或SOCKS5 CONNECT成功视为可达；这是连通性/延迟信号，不是吞吐测速，也不保证任何其他目标都可访问。HTTP 407、502等代理错误不视为健康。

该显式启用的模块会经本机代理线路发起对外请求及DNS解析；不会把CPU、内存、进程表、主机名或存储凭据发给探测目标。默认系统监控模式不发起这些探测。页面资源与指标来自本地服务，没有CDN资源或统计脚本。

## 可选：macOS登录后后台运行

先前台验证，再停止该前台实例。模板用于**用户登录后启动源服务**，不是开机级系统守护进程，也不是显示端kiosk安装器。通常不需要管理员权限。

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

需要局域网访问时，在理解上文暴露范围后把host换成 `YOUR_LAN_IP`；只有需要可选对外探测时，才给生成器追加 `--enable-gost`。生成器只输出配置，不安装服务、不创建日志目录、不改系统设置。也可手工修改示例plist，把所有 `YOUR_...` 换成绝对路径或选定值。不要把生成后的个人配置提交到仓库。

### 日志、重启与移除

HTTP访问日志默认静默。启动、采样或探测错误写入标准输出/标准错误；模板将其保存到 `~/Library/Logs/SideScreen/sidescreen.log`，不自动轮换日志。

```bash
# 代码更新后重启已安装的服务。
launchctl kickstart -k "gui/$(id -u)/com.example.sidescreen"
# 先停止并卸载服务，再移除该用户的配置。
launchctl bootout "gui/$(id -u)/com.example.sidescreen"
rm "$HOME/Library/LaunchAgents/com.example.sidescreen.plist"
```

移除登录项不会删除仓库、虚拟环境或日志；如需清理，请先检查这些本地文件再单独移除。本项目没有数据库或监控账号需要删除。

回退时先停止服务，恢复可信的旧Git提交或审核过的文件备份，必要时重新安装该版本固定依赖，再启动并刷新显示端。个人配置与日志备份放在Git之外；不要为回退而覆盖未提交的工作。

## 开发与检查

不需要前端构建或npm安装，`dashboard.html` 是完整自包含页面。Python测试可独立运行；前端检查需要Node.js 22+。

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/frontend.test.cjs
.venv/bin/python -m py_compile server.py scripts/render_launchagent.py
```

测试使用合成指标和回环HTTP，不要求Gost、不发起对外探测、不修改显示或网络。覆盖历史时间对齐、快照隔离、安全默认值、HTTP契约、模板生成、字节/速率计算、转义与连接状态转换。实体监控屏仍需在实际显示端进行视觉验收。

## 常见问题

| 现象 | 检查方向 |
| --- | --- |
| 源端能打开，显示端不能 | 默认只监听回环；明确选定可信源接口，核对源URL、防火墙与客户端隔离，不盲目改公网暴露。 |
| 端口被占用 | 停止确认属于本项目的实例，或选择其他 `--port`，不要误杀未知进程。 |
| 显示端仍是旧布局 | 重启源服务以重新加载HTML，再刷新显示端或打开 `/index`。 |
| 卡片在屏幕下方 | 核对页脚实际视口、缩放、浏览器栏、方向、异常长数值与线路数量；页面不会为塞进一屏故意隐藏指标。 |
| Gost显示“未启用” | 仅在需要发现和对外探测时，使用 `--enable-gost`。 |
| 没有Gost或所有线路失败 | 核对进程名 `gost`、IPv4回环监听、无认证代理支持、`/usr/sbin/lsof` 及探测目标可达性。 |
| 其他系统网速为零 | 当前网卡名称过滤面向macOS，其他平台尚未完整支持。 |
| 没有电池数据 | 台式机或无电池设备显示相应占位，属于预期行为。 |
| JSON可访问但提示过期 | 核对源端休眠和采样错误；HTTP成功不代表采样已更新。 |

## 隐私与发布

运行中的指标按设计向获准访问的显示端展示。仓库只包含代码、文档、合成测试与参数化模板；不要提交实际部署地址、用户账号、Wi-Fi设置、代理配置、秘密、日志、截图、原始采样、数据库或虚拟环境。`.gitignore` 只是辅助，仍需审核暂存差异和待推送历史。

## 许可证

SideScreen项目自有代码采用 [MIT许可证](LICENSE)。第三方组件保留各自许可证，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
