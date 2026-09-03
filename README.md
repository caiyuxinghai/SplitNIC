# 网口分流 SplitNIC

Windows 桌面工具：电脑同时连着 **有线网 + 无线网**（或再加 VPN）时，为每个软件指定走哪一张网卡。

典型场景：

- **有线网** 加载 WorkBuddy、VPN 客户端
- **无线网** 加载抖音、Chrome / Edge 等浏览器

本仓库公开，源码可审计。请只在自己的电脑上使用。

## 功能

- 简洁模式：把软件图标拖到有线网 / 无线网分区即可；点图标启动
- 高级模式：保留原来的表格、诊断、手动配置
- 图形界面（深色 GUI），列出当前已连接的网卡：有线 / Wi-Fi / VPN 虚拟网卡、IPv4、网关、状态
- 为每个 `.exe` 指定出口网卡，规则保存在 `%APPDATA%\SplitNIC\config.json`
- 两种分流方式：
  - **网卡绑定**：启动时注入 `BindHook.dll`，把进程的 Winsock 连接绑到指定网卡 IP，并设置 `IP_UNICAST_IF`（适合 WorkBuddy、VPN 客户端等 Win32 程序）
  - **浏览器代理**：在本机起一个只从该网卡出站的 SOCKS5 + HTTP 代理，再用启动参数把浏览器 / 抖音指过去（适合 Chrome、Edge、Firefox、抖音）
- 自动识别常见浏览器，默认走代理模式
- 可从「正在运行的进程」里直接添加规则
- 「测试每张网卡的公网 IP」，确认两条线路是不是真的从不同出口出去
- 启动前可选择结束同名旧进程（浏览器、抖音这类单实例程序必须勾选）
- 使用说明与注意事项做进了第三个标签页，不必先翻 README
- 桌面快捷方式（管理员、无黑框）、托盘、开机自启、单实例、F5 刷新、规则「运行中」状态
- 「设置」页可一键把快捷方式放到桌面
- 每条规则可生成「软件名（有线网/无线网）」桌面快捷方式，双击即按规则启动
- 启动后探测并显示该软件的实际公网出口 IP
- 开机启动会按规则自动拉起软件；网卡重新连上后也会自动启动绑在这张卡上、当时没在运行的软件
- 网卡掉线时结束绑在该卡上的软件，避免改走另一张网
- Chrome / Edge / 抖音默认独立配置目录，不必关掉日常正在用的浏览器
- 自动启动会等待网卡拿到 IPv4（最多约 90 秒），减少开机 DHCP 未完成导致的失败

## 环境要求

- Windows 10 / 11 64 位
- Python 3.10+（已安装依赖即可运行源码）
- **管理员权限**（网卡绑定需要；仅用浏览器代理可以不提权，但建议始终以管理员运行）
- 同时连接 **2 张及以上** 有 IPv4 的网卡

## 安装与运行

```powershell
cd splitnic
python -m pip install -r requirements.txt
```

桌面双击 **网口分流** 快捷方式（管理员、无控制台），或双击 `启动网口分流.bat`，或：

```powershell
python app.py
```

首次使用请点「刷新网卡」，确认能看到有线网和无线网。

### 编译绑定模块（网卡绑定模式需要）

`BindHook.dll` 用于把普通 Win32 程序绑到指定网卡。在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

脚本会下载 TinyCC、编译 `native/bindhook.c` → `native/BindHook.dll`。

没有这份 DLL 时，**浏览器代理模式仍然可用**，网卡绑定模式会提示缺失。

### 打包成独立 exe（可选）

```powershell
python -m pip install pyinstaller
pyinstaller --noconfirm --windowed --name SplitNIC --manifest app.manifest --add-data "native/BindHook.dll;native" --add-data "assets/icon.ico;assets" --icon assets/icon.ico app.py
```

生成的程序在 `dist/SplitNIC/`。

## 使用步骤（对应你的例子）

1. 用管理员打开本程序
2. 确认顶部同时出现「有线网」和「无线网」
3. 添加规则：
   - WorkBuddy.exe → 有线网 → 模式「自动」或「网卡绑定」
   - VPN 客户端 exe → 有线网 → 「网卡绑定」
   - 抖音 exe → 无线网 → 「自动」或「浏览器代理」
   - chrome.exe / msedge.exe → 无线网 → 「浏览器代理」
4. 勾选「启动前先关闭已运行的同名进程」
5. 点规则上的「快捷方式」，桌面会出现「WorkBuddy（有线网）」这类图标。以后用这些图标打开。
6. 启动后看规则上的「出口 IP」，确认走的是对的网卡。
7. 有线拔掉时，绑在有线网上的 WorkBuddy / VPN 会被结束，防止改走 Wi-Fi。

## 使用注意事项（必读）

1. **必须从本程序启动软件。** 从桌面快捷方式、开始菜单、任务栏钉选直接打开，Windows 仍会走系统默认网卡，规则不会生效。
2. **浏览器 / 抖音是单实例。** 如果不先关掉已经打开的窗口，新进程会合并到旧进程，代理参数全部丢失。请勾选「启动前先关闭已运行的同名进程」。
3. **微软商店 UWP 应用无法分流**（例如部分内置应用）。
4. **不要对带反作弊的游戏使用「网卡绑定」。** 注入会被视为外挂，可能导致封号或无法启动。
5. **不要对系统关键进程注入**（`csrss.exe`、`lsass.exe`、`svchost.exe`、`services.exe`、`explorer.exe`）。
6. **32 位程序**不能使用当前的 64 位 `BindHook.dll`，请改用浏览器代理模式，或改用 64 位版本的软件。
7. **杀毒软件可能拦截注入。** 这是误报常见场景。请把本程序目录和 `BindHook.dll` 加入信任列表后重试。
8. **DNS 可能泄漏。** 即使 TCP 走了指定网卡，Windows DNS 仍可能从「度量值更低」的那张网卡查询。两条线路的 DNS 策略不同时，请在网卡属性里分别填写 DNS，或禁用不用那张网卡的 IPv6。
9. **IPv6 可能绕过分流。** 本工具以 IPv4 为主。不需要 IPv6 时，在「不该出门」的那张网卡上取消勾选 IPv6。
10. **VPN 有两种完全不同的绑法，不要搞混：**
    - 让 VPN **客户端自己**走有线网去连接 VPN 服务器 → 把 `VPN.exe` 绑到**有线网**
    - 让某个软件走 **已经连上的 VPN 隧道** → 把该软件绑到 **VPN 虚拟网卡**（WireGuard / Wintun / TAP 等），不是绑到 VPN.exe
11. **Firefox 代理模式使用独立配置目录**（`%APPDATA%\SplitNIC\firefox-profiles\`），和日常书签、登录态不是同一套。
12. **分流不是隐身，也不是防火墙。** 绑定失败、代理没挂上、程序自己用了自定义网络栈时，流量仍可能从默认网卡出去。可用「测试每张网卡的公网 IP」对照。
13. **需要管理员权限。** 非管理员时网卡绑定会失败。批处理 `启动网口分流.bat` 会自动请求 UAC。
14. **只在自己拥有的电脑上使用。** 本工具通过 DLL 注入和本地代理工作，请勿用于未授权的设备。

## 原理简述

- 列出网卡：Windows `GetAdaptersAddresses`
- 浏览器分流：本地 SOCKS5/HTTP 代理的出站 socket `bind(网卡IP)` + `IP_UNICAST_IF`
- 普通程序分流：`CreateProcess(CREATE_SUSPENDED)` → 远程 `LoadLibrary(BindHook.dll)` → 挂钩 `connect` / `WSAConnect` / `sendto` 等，在连接前绑定指定接口
- Windows 默认是弱主机模型，只 `bind` 源 IP 不够，所以同时设置 `IP_UNICAST_IF`

## 自检 / 排错

程序里打开「诊断」页点「开始自检」，或命令行：

```powershell
python app.py --selftest
```

会检查：管理员权限、BindHook.dll 能否加载、网卡是否 ≥ 2 张、每张网卡绑定出口、本地 SOCKS 代理、向 notepad.exe 注入后进程是否还活着。

崩溃日志：`%APPDATA%\SplitNIC\error.log`  
注入日志：`%TEMP%\splitnic-bindhook.log`

常见问题：

- 双击 bat 一闪而过：以管理员运行后找不到 Python。bat 会优先用 `%LocalAppData%\Programs\Python\Python3xx\python.exe`。
- 一点启动软件就闪退：旧版用了不安全的 12 字节 inline hook，已改为 IAT 挂钩。
- 浏览器显示没网：已去掉会把 Chrome DNS 全部打成 NOTFOUND 的启动参数。
- 启动后弹出「要以管理员重新打开吗」然后界面没了：已改成右上角按钮，不再强制弹窗关窗。

## 配置文件

```
%APPDATA%\SplitNIC\config.json
```

绑定模块调试日志：

```
%TEMP%\splitnic-bindhook.log
```

## 许可证

MIT。见 [LICENSE](LICENSE)。

`BindHook.dll` 由本仓库 `native/bindhook.c` 编译，同属 MIT。构建时如下载 TinyCC，TinyCC 本身为 LGPL。
