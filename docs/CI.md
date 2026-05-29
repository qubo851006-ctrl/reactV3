# CI 门禁说明

> 配置文件:`.github/workflows/ci.yml`
> 触发时机:push 到 master / 对 master 发 PR
> 当前状态:首版,仅 backend + frontend 两个 job

---

## 在跑什么

### Backend job(timeout 10 分钟)

| 步骤 | 命令 | 当前规模 |
|---|---|---|
| 1. Checkout | actions/checkout@v4 | - |
| 2. Setup Python 3.11 + pip 缓存 | actions/setup-python@v5 | 缓存 key 跟 `backend/requirements.txt` 内容绑定 |
| 3. `pip install -r backend/requirements.txt` | - | 首次 ~1 分钟,有缓存时 ~5 秒 |
| 4. `python -m pytest tests/ -q` | - | **339 个测试** + 6 个子测试 / ~35 秒 |

**没用真实凭据** —— 全部测试 mock 掉 LLM client,alembic env 在 `APP_DATABASE_URL` 未设时 fallback 到 SQLite。

### Frontend job(timeout 10 分钟)

| 步骤 | 命令 | 当前规模 |
|---|---|---|
| 1. Checkout | actions/checkout@v4 | - |
| 2. Setup Node 20 + npm 缓存 | actions/setup-node@v4 | 缓存 key 跟 `frontend/package-lock.json` 绑定 |
| 3. `npm ci` | - | 首次 ~1 分钟,有缓存时 ~10 秒 |
| 4. `npm run lint`(eslint) | - | ~5 秒 |
| 5. `npm run test`(vitest) | - | **39 个测试** / ~4 秒 |
| 6. `npm run build`(tsc + vite) | - | ~10 秒 |

---

## 不在 CI 跑什么(暂时)

| 项 | 为什么不跑 |
|---|---|
| Playwright E2E | 浏览器下载 ~150 MB 慢;spec 全 mock 后端,价值低 |
| Backend ruff/black 静态检查 | 项目历史代码积累的 warning 较多,需要单独治理 PR 再开 |
| `npm run check:branding` | 需要本地资源文件,CI 上不友好 |
| Backend alembic migration 命令 | 测试套件本身覆盖了核心路径,不需要再跑 alembic 命令 |
| 集成测试连真实 PG | 没有 GH Actions secret 配置,跑了也是裸的 |

---

## 怎么读 CI 状态

### 在 PR 页面
打开 GitHub PR 页面下方的 "Checks" 区域,会看到两条:
- `CI / Backend (pytest)` — ✅/❌
- `CI / Frontend (lint + vitest + build)` — ✅/❌

点击任一条进入完整日志。

### 在 commits 列表
master 历史每个 commit 旁边会有 ✅/❌/🟡 标记,鼠标移上去能看到具体 job 状态。

---

## 怎么本地复现 CI 失败

CI 用的命令本地等价:

```powershell
# Backend
cd backend
python -m pytest tests/ -q --tb=short

# Frontend
cd frontend
npm run lint
npm run test
npm run build
```

如果本地能过、CI 不过,大概率是:
- Node / Python 版本差异(CI 用 Node 20 + Python 3.11)
- 系统差异(CI 是 Ubuntu,本地可能是 Windows;路径分隔符等)
- 本地有未提交的修改

---

## Branch 保护规则(推荐手动配置)

CI 跑出来的红/绿目前**只是参考**,master 上的 push 不会因为 CI 红被拒。要让 CI 成为真正的"门禁",需要在 GitHub 网页上配:

1. 打开 https://github.com/qubo851006-ctrl/reactV3/settings/branches
2. 点 "Add branch protection rule"
3. Branch name pattern: `master`
4. 勾上:
   - ✅ **Require status checks to pass before merging**
     - 然后在搜索框输入 `Backend` 和 `Frontend`,把这两个 check 加进必须通过的列表
   - ✅ **Require branches to be up to date before merging**(可选,严格模式)
   - ✅ **Do not allow bypassing the above settings**(防止管理员误绕过)
5. Save

配完之后:
- 直接 push 到 master 不会被拦(GitHub 不支持 push 限制,只限 PR)
- 但所有走 PR 流程的改动,必须等两个 CI job 都绿才能 merge

如果你**完全用 PR workflow**:配 branch protection 就能形成完整门禁。
如果你**习惯直接 push 到 master**(MVP 阶段常见):CI 还是会跑,但只是事后通知,需要看 commits 列表的红绿标记。

---

## 未来扩展(留 v3.6.9+)

- [ ] 加 backend ruff 静态检查(需先治理历史代码)
- [ ] 加 pre-commit hooks(husky / pre-commit 库),让 lint/test 在 commit 前就跑
- [ ] 单独的 Playwright workflow,只在 PR 触发,带浏览器缓存
- [ ] 集成测试 job 连真实 PG(需 GH Actions secret + 临时数据库)
- [ ] 测试覆盖率上报(codecov 或类似)
