# V3 内网 HTTPS 部署指南

> 本文档配合 `Caddyfile` / `caddy-start.ps1` / `start-https.bat` / `stop-https.bat` 使用。
> 适用环境:Windows 11 服务器 + 内网 IP 访问 + 客户端是 Edge / Chrome 浏览器。

---

## 为什么 V3 需要 HTTPS

V3 用到了若干**仅在"安全上下文"(secure context)下可用**的 Web 平台 API,典型如:

- `window.Notification` — Windows 系统通知
- `navigator.clipboard.writeText` — 一键复制(审计饼图等)
- 未来可能用到的 `getUserMedia` / Service Worker / PushManager

Chromium 内核的判定规则:

| 地址 | secure context? |
|---|---|
| `https://任意地址` | ✅ |
| `http://localhost` / `http://127.0.0.1` | ✅(测试豁免) |
| `http://内网 IP`(192.168.x.x / 10.x.x.x)| ❌ |
| `http://主机名` | ❌ |

V3 部署在 `http://192.168.9.226:8001` → 内网 IP + HTTP,**Notification API 在客户端浏览器里被整个禁用**(站点设置里的"通知"那一栏灰色不可改),用户点 🔔 测试系统通知没反应。

**解决方案**:服务器本地用 mkcert 签内网证书,Caddy 做 HTTPS 反向代理 → uvicorn,客户端机器装一次 mkcert 根 CA 即可全内网无警告访问。

---

## 架构

```
┌──────────────────────────────────────────────────────────┐
│ 客户端机器(每位同事电脑,一次性配置)                   │
│ └─ 安装 mkcert 根 CA → 浏览器自动信任所有 V3 内网域名    │
└──────────────────────────────────────────────────────────┘
                         ↓ HTTPS
┌──────────────────────────────────────────────────────────┐
│ 服务器 192.168.9.226 (Windows 11)                        │
│                                                          │
│  ┌──────────────┐                                       │
│  │ Caddy :8443  │ ← HTTPS 终结(mkcert 签的内网证书)   │
│  └──────┬───────┘                                       │
│         │ 本地反代(127.0.0.1,零延迟)                 │
│         ↓                                                │
│  ┌──────────────┐                                       │
│  │ uvicorn:8001 │ ← V3 后端(HTTP,不动)              │
│  └──────────────┘                                       │
└──────────────────────────────────────────────────────────┘
```

**端口选择**:Caddy 监听 8443 是因为 443 标准端口被服务器上其他工具占用(本机情况:Steam 加速)。如果你的服务器 443 空闲,可以改 Caddyfile 第一行 `:443 {` 用标准端口,客户端访问 URL 也不用带端口号(`https://192.168.9.226` 即可)。

---

## 一次性服务器搭建

> 服务器:Windows 11,管理员 PowerShell。

### 1. 下载工具

```powershell
New-Item -ItemType Directory -Force D:\tools | Out-Null

# mkcert(本地 CA 签证书工具,~5MB)
Invoke-WebRequest `
    -Uri "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe" `
    -OutFile "D:\tools\mkcert.exe" -UseBasicParsing

# Caddy(反向代理,~30MB)
Invoke-WebRequest `
    -Uri "https://caddyserver.com/api/download?os=windows&arch=amd64" `
    -OutFile "D:\tools\caddy.exe" -UseBasicParsing

# 验证版本
& D:\tools\mkcert.exe -version    # 期望:v1.4.4
& D:\tools\caddy.exe version       # 期望:v2.11.x+
```

### 2. 装根 CA + 签证书

```powershell
$env:PATH = "D:\tools;" + $env:PATH

# 装本地 CA 到 Windows 受信任根库(会弹安全框,点【是】)
mkcert -install

# 签证书(SAN 包含 IP / localhost / 本机名,通吃所有访问方式)
New-Item -ItemType Directory -Force D:\prj\reactV3\certs | Out-Null
Set-Location D:\prj\reactV3\certs
mkcert 192.168.9.226 localhost 127.0.0.1 <你的主机名>

# 产物:192.168.9.226+3.pem(证书) + 192.168.9.226+3-key.pem(私钥)
# 注意:文件名里的数字 +3 是 SAN 个数,如果你少签一个就是 +2
# 如果文件名不同,需要改 Caddyfile 第 6 行对应路径
```

### 3. 防火墙放行 8443

```powershell
New-NetFirewallRule `
    -DisplayName "Caddy HTTPS (8443)" `
    -Direction Inbound -LocalPort 8443 `
    -Protocol TCP -Action Allow -Profile Any
```

### 4. 启动 Caddy

```powershell
# 仓库根目录,假设 git clone 到 D:\prj\reactV3
Set-Location D:\prj\reactV3
.\start-https.bat

# 验证
Get-Process caddy                  # 应能看到 caddy.exe 进程
Get-NetTCPConnection -LocalPort 8443 -State Listen
Invoke-WebRequest -Uri "https://localhost:8443" -UseBasicParsing | Select StatusCode
# 期望:200
```

启停命令:

| 操作 | 命令 |
|---|---|
| 启动 | `.\start-https.bat` 或双击 |
| 停止 | `.\stop-https.bat` 或双击 |
| 看实时日志 | `Get-Content .\logs\caddy-access.log -Tail 20 -Wait` |
| 看错误日志 | `Get-Content .\logs\caddy-*.err.log -Tail 20` |

> ⚠️ 当前没有开机自启 — 如果服务器重启,需要手动跑 `start-https.bat` 或在任务计划程序里挂登录触发。

---

## 一次性客户端配置(每位同事做一次)

### 1. 拿到根 CA

服务器管理员把 `C:\Users\<服务器用户>\AppData\Local\mkcert\rootCA.pem` 拷出来,
分发渠道:共享盘 / 微信 / 邮件 / U 盘均可。**文件不含私钥,公开传输安全**。

服务器侧拷贝命令:

```powershell
Copy-Item "$env:LOCALAPPDATA\mkcert\rootCA.pem" "$env:USERPROFILE\Desktop\reactV3-rootCA.pem"
```

### 2. 客户端安装

**方式 A — PowerShell(推荐,1 条命令)**

客户端机器开**管理员 PowerShell**:

```powershell
Import-Certificate `
    -FilePath "<你保存 reactV3-rootCA.pem 的路径>" `
    -CertStoreLocation Cert:\LocalMachine\Root

# 验证
Get-ChildItem Cert:\LocalMachine\Root |
    Where-Object { $_.Issuer -like "*mkcert*" } |
    Select-Object Subject, NotAfter
```

**方式 B — GUI**

Windows 11 不认识 `.pem` 扩展名,先改名 `.crt`:

1. 重命名 `reactV3-rootCA.pem` → `reactV3-rootCA.crt`
2. 双击 → 【安装证书】
3. 存储位置选 **【本地计算机】**(不是当前用户)→ UAC 允许
4. 【将所有的证书都放入下列存储】→ 浏览 → **【受信任的根证书颁发机构】**
5. 完成

### 3. 重启浏览器

**完全关闭 Edge / Chrome**(任务管理器看 msedge.exe / chrome.exe 进程全消失),再重新打开。
然后访问 `https://192.168.9.226:8443` — 地址栏锁形无警告 = 成功。

---

## 日常运维

### Caddy 是否在跑

```powershell
Get-Process caddy
Get-NetTCPConnection -LocalPort 8443 -State Listen
```

### 看访问日志

```powershell
# 实时
Get-Content D:\prj\reactV3\logs\caddy-access.log -Tail 20 -Wait

# 最新错误
Get-ChildItem D:\prj\reactV3\logs\caddy-*.err.log |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 |
    Get-Content -Tail 30
```

### 证书续期

mkcert 默认签 **10 年有效证书**,2036 年之前不需要管。
真要续:删 `certs\*.pem` → 重跑 `mkcert 192.168.9.226 localhost 127.0.0.1 <hostname>` → 重启 Caddy。
**根 CA 是 10 年有效,客户端不需要重装根 CA**。

### Caddy 升级

```powershell
.\stop-https.bat
Invoke-WebRequest "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile D:\tools\caddy.exe -UseBasicParsing
.\start-https.bat
```

---

## 故障排查

### 客户端浏览器报"您的连接不是专用连接"

- 客户端没装根 CA → 按"一次性客户端配置"重做
- 装到了"当前用户"而不是"本地计算机" → 重做 Step 2,**选本地计算机**
- 浏览器没真正重启 → 任务管理器确认浏览器进程全部退出后再开

### 客户端报错"NET::ERR_CERT_AUTHORITY_INVALID" 但根 CA 已装

- 服务器 mkcert 签证书时漏了客户端访问用的 IP / 主机名 → 服务器重新签:
  ```powershell
  Set-Location D:\prj\reactV3\certs
  mkcert 192.168.9.226 localhost 127.0.0.1 <hostname1> <hostname2>
  .\..\stop-https.bat
  .\..\start-https.bat
  ```

### Caddy 起不来,报 "bind: 拒绝访问"

- 8443 被占用:`Get-NetTCPConnection -LocalPort 8443` 看是谁占的
- 防火墙规则缺失:重跑 Step 3 的 `New-NetFirewallRule`

### 客户端访问报 HTTP 502 Bad Gateway

- Caddy 通了但 uvicorn 8001 没响应 → `Get-NetTCPConnection -LocalPort 8001 -State Listen` 确认
- uvicorn 没起来 → 跑 `start.bat`

### Edge 弹通知时报 "msedge.exe Windows 无法访问指定设备"

- 客户端机器本地 Edge 注册表残留(64 位升级后旧 32 位路径没清)
- 与 V3 / Caddy / 证书无关,**不影响其他客户端**
- 临时方案:用 Chrome 访问(Chrome 也走系统根 CA,装的根证书 Chrome 也认)
- 修复方案:Windows 设置 → 应用 → Microsoft Edge → 修改 → 修复

---

## 文件清单

仓库根目录新增:

| 文件 | 用途 | 是否进 git |
|---|---|---|
| `Caddyfile` | Caddy 配置(相对路径,跨机通用)| ✅ |
| `caddy-start.ps1` | 后台启动(避免双开 + 日志唯一名)| ✅(UTF-8 BOM)|
| `start-https.bat` | 双击启动入口 | ✅ |
| `stop-https.bat` | 双击停止入口 | ✅ |
| `certs/*.pem`, `certs/*-key.pem` | mkcert 签的证书 | ❌(`.gitignore` 排除 `*.pem` `*.key`)|
| `logs/caddy-*.log` | Caddy 运行日志 | ❌(`.gitignore` 排除 `logs/`)|

---

## 与现有部署的关系

- **跟 V2 完全隔离**:V2 在 8000,V3 uvicorn 在 8001,Caddy 在 8443 — 三套互不影响
- **跟 deploy-watch.ps1 协同**:deploy-watch 只管 git pull + 前端 build + 重启 uvicorn,**不重启 Caddy**(因为 Caddy 不依赖 V3 代码,只反代)
- **V2 也想上 HTTPS**:复用同一份证书(SAN 已包含 192.168.9.226),给 V2 加个 Caddyfile 块监听不同端口(如 8444)即可
