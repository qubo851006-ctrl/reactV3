# V3 服务器部署手册

> **目标环境**：Windows 11，与 V2 (`D:\prj\react-master`) 在同一台机器并存
> **运行端口**：8001（V2 占 8000，互不影响）
> **更新机制**：每 5 分钟由任务计划程序检测 GitHub master，有新 commit 自动 pull + build + 重启

---

## 首次部署清单（一次性，约 10-15 分钟）

### 1. 准备路径 + clone

```powershell
# 在管理员 PowerShell 跑
New-Item -ItemType Directory -Force -Path D:\prj | Out-Null
cd D:\prj
git clone https://github.com/qubo851006-ctrl/reactV3.git
cd reactV3
```

### 2. 放 `backend/.env`（含密钥，不能进 git）

```powershell
# 从开发环境复制（如果开发环境就是这台机器）
Copy-Item D:\claude\reactV3\backend\.env D:\prj\reactV3\backend\.env

# 验证关键字段
Select-String -Path D:\prj\reactV3\backend\.env -Pattern '^(AIRCHINA_API_KEY|DATABASE_URL|ZHISHU_API_KEY|QCC_TOKEN)='
# 应该看到 4 行非空值
```

主业务库推荐配置 PostgreSQL：

```env
APP_DATABASE_URL=postgresql://<user>:<password>@<host>:5432/reactv3
```

`APP_DATABASE_URL` 只控制 V3 主业务库（用户、会话、审计日志、钉钉通知日志、同步日志）。若不配置，后端会回退到 `data/auth.db` SQLite，适合本地开发。

从现有 SQLite 迁移到 PostgreSQL 时，先 dry-run：

```powershell
python tools\migrate_main_sqlite_to_pg.py
```

确认行数无误、且已备份目标库后执行：

```powershell
python tools\migrate_main_sqlite_to_pg.py --execute --force
python tools\check_main_db.py
```

LLM 追溯库可继续单独配置：

```env
LLM_AUDIT_DATABASE_URL=postgresql://<user>:<password>@<host>:5432/reactv3_audit
```

### 3. 后端 Python 依赖（如果之前没装过）

```powershell
cd D:\prj\reactV3\backend
pip install -r requirements.txt
# 注意：psycopg[binary] 网络可能慢，参考 tools/pg_connectivity_check.py 验证装好
python ..\tools\pg_connectivity_check.py
# 应该看到 [PASS] llm_audit DB is ready.
```

### 4. 前端依赖 + build

```powershell
cd D:\prj\reactV3\frontend
npm install --no-audit --no-fund --registry https://registry.npmmirror.com
npm run build
# 产物在 D:\prj\reactV3\frontend\dist
```

### 5. 首次手动启动验证

```powershell
cd D:\prj\reactV3\backend
python -m uvicorn main:app --host 0.0.0.0 --port 8001
# 看到 "Uvicorn running on http://0.0.0.0:8001" 就 OK
# Ctrl+C 停止，进入下一步配自动启动
```

浏览器开 `http://<服务器IP>:8001/` 应该看到法度云图登录页。**确认无误后 Ctrl+C 停掉**，下面让计划任务接管。

### 6. 注册自动部署任务（管理员 PowerShell）

```powershell
# 6.1 注册"每 5 分钟检查 GitHub 更新"任务
schtasks /create /tn "reactV3 deploy" `
  /sc minute /mo 5 `
  /tr "powershell -ExecutionPolicy Bypass -File D:\prj\reactV3\deploy-watch.ps1" `
  /ru SYSTEM /rl HIGHEST /f

# 6.2 注册"开机自启 uvicorn"任务（首次启动 + 服务器重启后恢复）
schtasks /create /tn "reactV3 boot" `
  /sc onstart `
  /tr "powershell -ExecutionPolicy Bypass -Command `"Start-Process python -ArgumentList '-m','uvicorn','main:app','--host','0.0.0.0','--port','8001' -WorkingDirectory 'D:\prj\reactV3\backend' -WindowStyle Hidden`"" `
  /ru SYSTEM /rl HIGHEST /f

# 6.3 立即手动跑一次 deploy-watch（让 uvicorn 启起来）
powershell -ExecutionPolicy Bypass -File D:\prj\reactV3\deploy-watch.ps1
# 看 D:\prj\reactV3\logs\deploy-watch.log 应该写入 "✅ 部署成功"
```

### 7. 注册数据库定期备份（推荐）

```powershell
schtasks /create /tn "reactV3 PG backup" `
  /sc daily /st 02:00 `
  /tr "powershell -ExecutionPolicy Bypass -File D:\prj\reactV3\tools\backup_pg.ps1" `
  /ru SYSTEM /rl HIGHEST /f
```

备份输出在 `D:\backup\pg\reactv3_*.dump`，保留 30 天后自动清理。

### 8. （可选）注册 LLM 追溯归档

```powershell
schtasks /create /tn "reactV3 LLM trace archive" `
  /sc weekly /d SUN /st 03:00 `
  /tr "python D:\prj\reactV3\tools\archive_llm_traces.py" `
  /ru SYSTEM /rl HIGHEST /f
```

90 天前的 trace 自动迁到 `llm_traces_archive` 表，保持热表轻快。

---

## 部署后验证

| 检查项 | 命令 | 期望 |
|---|---|---|
| 服务在跑 | `Get-NetTCPConnection -LocalPort 8001 -State Listen` | 有一个 listener |
| 健康检查 | `curl http://127.0.0.1:8001/api/health` | `{"status":"ok"}` |
| 前端可达 | 浏览器 `http://server:8001/` | 看到法度云图登录页 |
| 主业务库 | `python tools\check_main_db.py` | 显示 main DB backend 和基础表 |
| PG 写入工作 | `python D:\prj\reactV3\tools\smoke_test_pg.py` | 6 步全 PASS |
| 自动部署日志 | `Get-Content D:\prj\reactV3\logs\deploy-watch.log -Tail 20` | 有 "检测到新版本" / "✅ 部署成功" 记录 |
| 与 V2 共存 | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | V2 仍在 8000，不受影响 |

---

## 触发一次更新（验证自动部署）

在你的开发机做一个无关紧要的 commit 并 push：

```powershell
cd D:\claude\reactV3
# 假装改了 README
git commit --allow-empty -m "test: trigger deploy-watch"
git push origin master
```

5 分钟内观察服务器：

```powershell
Get-Content D:\prj\reactV3\logs\deploy-watch.log -Tail 10 -Wait
```

应该看到 `检测到新版本` → `git pull` → `npm run build` → `✅ 部署成功`。

---

## 故障排查

| 症状 | 检查 | 处理 |
|---|---|---|
| `/api/health` 不返回 | `D:\prj\reactV3\logs\uvicorn-*.err.log` | 看 Python 报错 |
| 部署一直不触发 | `schtasks /query /tn "reactV3 deploy" /v` | 看上次运行结果 + 时间 |
| `npm run build` 失败 | `D:\prj\reactV3\logs\deploy-watch.log` 末尾 | 多是 TypeScript 错误，本地 `npm run build` 复现修了再 push |
| 8001 端口被占 | `Get-NetTCPConnection -LocalPort 8001 -State Listen \| Select OwningProcess` | 找到 PID `Stop-Process -Id <pid> -Force` |
| 锁文件僵死 | 检查 `D:\prj\reactV3\.deploy.lock` | 超过 15 分钟自动清理；手动也可以 `Remove-Item` |
| PG 连不上 | `python D:\prj\reactV3\tools\pg_connectivity_check.py` | 看是否 `127.0.0.1` 在 `.env`、`pg_hba.conf` 是否允许 SCRAM |

---

## 回滚一个 commit

```powershell
cd D:\prj\reactV3
git fetch
git reset --hard <good_commit_sha>  # 回到已知好版本
# 然后再 npm run build + 重启 uvicorn
cd frontend; npm run build
$pid = (Get-NetTCPConnection -LocalPort 8001 -State Listen).OwningProcess
Stop-Process -Id $pid -Force
# 任务计划程序 "reactV3 boot" 不会立即拉起；手动启一次或等下次 deploy-watch
Start-Process python -ArgumentList '-m','uvicorn','main:app','--host','0.0.0.0','--port','8001' -WorkingDirectory D:\prj\reactV3\backend
```

注意：下次有新 push deploy-watch 会自动拉到 master 最新，回滚只是临时手段。彻底回滚要 `git push --force` 主分支或 `git revert`。

---

## 端口冲突应急切换

如果以后 8001 被别的服务占用，改这两处即可：

1. `D:\prj\reactV3\deploy-watch.ps1` 顶部 `$port = 8001` 改成新端口
2. 重新注册 `reactV3 boot` 任务，更新 `--port` 参数
3. 改前端反向代理（如果有）配置

V3 后端不读 `PORT` 环境变量，端口只在启动命令行传。
