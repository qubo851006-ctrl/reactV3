# CI 门禁说明

> 配置文件:`.github/workflows/ci.yml`
> 触发时机:push 到 master / 对 master 发 PR
> 当前状态:backend + frontend + security-audit 三个 job(security-audit 自 v3.6.19)

---

## 在跑什么

### Backend job(timeout 10 分钟)

| 步骤 | 命令 | 当前规模 |
|---|---|---|
| 1. Checkout | actions/checkout@v4 | - |
| 2. Setup Python 3.11 + pip 缓存 | actions/setup-python@v5 | 缓存 key 跟 `backend/requirements.txt` 内容绑定 |
| 3. `pip install -r requirements.txt -r requirements-dev.txt` | - | 首次 ~1 分钟,有缓存时 ~5 秒 |
| 4. `ruff check .`(lint,配置见 `backend/ruff.toml`) | - | ~1 秒 |
| 5. `python -m pytest tests/ -v` | - | **371 个测试** + 6 个子测试 / ~35 秒 |

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

### Security-audit job(依赖漏洞巡检 · timeout 10 分钟 · 自 v3.6.19)

| 步骤 | 命令 | 说明 |
|---|---|---|
| 1. `pip-audit -r requirements.txt` | 后端生产依赖对 PyPI/OSV 漏洞库 | 任一已知漏洞 → job 失败 |
| 2. `npm audit --omit=dev --audit-level=high` | 前端生产依赖 | high/critical → job 失败 |

**为什么只查生产依赖**:开发工具(pytest/ruff、vite/vitest/eslint)不随产品部署,排除以免被构建链告警刷屏。

**为什么不进 pre-push 钩子**:漏洞巡检要联网查询漏洞库、且供应链风险是"周期性"而非"每次提交"的关注点;放 CI(+ Dependabot)即可,pre-push 保持快、离线。

**这是真门禁还是参考**:本仓库直接 push 到 master(CI 是 push 后跑),所以 security-audit 红了不会"拦住"提交,但会在 master 上显红 X 提示关注。配合下面的 Dependabot 主动修复,形成"发现 + 修复"闭环。上线前若要更严,可加 branch protection 把它列为必过 check。

### Dependabot(依赖自动巡检 · 自 v3.6.19)

配置:`.github/dependabot.yml`。每周一对三个生态各开一次"有更新/有漏洞"的 PR:

| 生态 | 范围 |
|---|---|
| `pip` | `backend/requirements*.txt` |
| `npm` | `frontend/package.json` + lock |
| `github-actions` | CI 用到的 action 版本 |

- 安全类更新(security advisory)Dependabot 会优先单独开 PR;非安全的 minor/patch 升级按生态分组合并成一个 PR 减噪。
- 所有 Dependabot PR 合并前仍走 CI 四门禁把关,不绕过测试。
- **首次启用需在 GitHub 网页确认**:Settings → Code security → 确认 Dependabot 已开启(推送 dependabot.yml 后通常自动生效)。

---

## 不在 CI 跑什么(暂时)

| 项 | 为什么不跑 |
|---|---|
| Playwright E2E | 浏览器下载 ~150 MB 慢;spec 全 mock 后端,价值低 |
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
如果你**习惯直接 push 到 master**(MVP 阶段常见):branch protection 拦不住直接 push,这时真正有用的是下面的**本地 pre-push 门禁**。

---

## 本地 pre-push 门禁(已启用 · 推荐给直接 push 到 master 的工作流)

因为 GitHub 免费版的 branch protection 只对 PR 生效、拦不住直接 push,本仓库额外配了一个**本地 git pre-push 钩子**:每次 `git push` 前自动在本机跑 backend pytest + frontend vitest + frontend e2e,**任一失败就拦住 push**,红的代码根本出不了你的机器。

钩子脚本:`tools/git-hooks/pre-push`(已纳入版本控制)。三道依次:

1. `backend: python -m pytest tests/`
2. `frontend: npm run test`(vitest)
3. `frontend: npm run test:e2e`(playwright,用系统 Edge)

### 新 clone / 换机器后激活(每个克隆跑一次)

```powershell
cd <仓库根>
git config core.hooksPath tools/git-hooks
```

> 注:`core.hooksPath` 是本地 git config,不随仓库同步,所以每台机器 clone 后都要重跑这一行。跑一次就长期生效。

### 验证是否已激活

```powershell
git config --get core.hooksPath   # 应输出 tools/git-hooks
```

### 它在拦什么

- push 前依次跑 pytest + vitest + playwright e2e
- 全绿 → 放行 push
- 任一红 → 打印失败项并 **exit 1 拦截**,push 不会发生

### E2E 说明(第 3 道)

- 用**系统 Edge** 跑(`PW_CHANNEL` 默认 `msedge`),不依赖下载内置 chromium
- mock 模式:验证关键路径导航不崩 + flow 切换,不连真实后端
- 配了单 worker 串行 + retry 1 次 + 放宽超时,压住共享 dev server 的冷启动波动
- 比前两道慢(~17-50 秒,含 vite 冷启动 + 浏览器启动)

### 紧急绕过(谨慎)

```powershell
# 全跳(文档热修等明确安全场景)
$env:SKIP_HOOK=1; git push; Remove-Item Env:SKIP_HOOK

# 只跳较慢的 e2e,保留 pytest+vitest
$env:SKIP_E2E=1; git push; Remove-Item Env:SKIP_E2E
```

(bash 环境:`SKIP_HOOK=1 git push` / `SKIP_E2E=1 git push`)

### 跟 CI 的关系

- **pre-push 钩子** = 第一道,在本机拦,最快反馈(~40 秒),代码不出门
- **GitHub Actions CI** = 第二道,push 到 GitHub 后云端再跑一遍,防"本机环境跟 CI 不一致"漏网

两道用的是同一批测试,互为保险。

---

## 未来扩展

- [x] ~~加 backend ruff 静态检查~~ 已接入(v3.6.14):ruff.toml 保守规则集(E4/E7/E9/F),门面模块 per-file-ignore,CI + pre-push 钩子都跑
- [x] ~~本地 pre-push 钩子~~ 已用 git 原生 hook 实现(见上节;比 husky/pre-commit 库更轻,零额外依赖)
- [x] ~~依赖漏洞扫描~~ 已接入(v3.6.19):pip-audit + npm audit 进 CI security-audit job + Dependabot 每周自动开修复 PR + `tools/audit-deps.ps1` 本地按需跑
- [ ] 单独的 Playwright workflow,只在 PR 触发,带浏览器缓存
- [ ] 集成测试 job 连真实 PG(需 GH Actions secret + 临时数据库)
- [ ] 测试覆盖率上报(codecov 或类似)
- [ ] 后端静态类型检查(mypy/pyright,渐进式)
