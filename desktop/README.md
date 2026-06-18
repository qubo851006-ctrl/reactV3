# V3 Desktop Shell

这个目录是 V3 的 Electron 桌面壳。它不打包后端、不复制前端业务代码，只加载现有 V3 Web 服务。

默认地址:

```text
https://192.168.9.226:8443
```

## 本地运行

```powershell
cd desktop
npm install
npm start
```

如果服务器/办公网络有 HTTPS 证书拦截，先让 Node 使用系统证书库:

```powershell
$env:NODE_OPTIONS = "--use-system-ca"
npm ci
```

临时指定服务地址:

```powershell
$env:V3_DESKTOP_URL = "http://localhost:8001"
npm start
```

或者复制 `config.example.json` 为 `desktop.config.json`，放在 `desktop/` 目录或打包后的 exe 同目录。

## 设计边界

- 桌面壳只负责窗口、托盘、下载、外链打开、基础诊断。
- V3 的业务、登录、权限、审计、LLM trace、任务队列仍然走现有 FastAPI 服务。
- 不在用户电脑上本地启动 Python 后端，也不本地存储模型密钥或业务数据库。

## 打包

```powershell
cd desktop
npm run dist
```

产物输出到 `desktop/release/`。
