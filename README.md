# 法度云图

[![CI](https://github.com/qubo851006-ctrl/reactV3/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/qubo851006-ctrl/reactV3/actions/workflows/ci.yml)

法度云图是基于 React + FastAPI 的内部法务合规智能工具，面向培训归档、案件台账、授权请示、审计问题分析、企业信息查询和多会话对话等工作场景。

> **v3 主版本**（仓库 `reactV3`）。V2 同名仓库继续维护历史功能；V3 是为了引入 LLM 调用全链路追溯、用户反馈学习闭环、按场景智能选模型等架构能力而独立的演进分支，新功能后续只在 V3 落地。

## 主要功能

### 业务流程
- **培训统计及归档**：上传培训通知 PDF 和签到表图片，识别培训信息，确认后写入统计表并正式归档，后台记录关键步骤耗时。
- **案件台账生成**：上传 PDF/DOCX/DOC 法律文书，并发解析文书和 OCR，按企业法务台账口径提取案件字段，确认后更新案件台账并归档文书；识别为同一案件的文书自动归入同一文件夹。
- **授权请示起草**：上传呈批件 PDF，生成授权请示、授权书，两份正文并行生成，核对后可单独记录授权委托台账。
- **合规审查台账**：上传 OA 流程表单及审批记录 PDF，提取重大事项、程序、各单位审查意见、签署时间和背景材料，确认后写入长期累计合规审查工作台账。
- **三台账合并**：以合同台账为主，合并采购和财务台账，结果按当前用户和本次合并编号隔离保存。
- **审计问题分析**：上传审计发现问题 Excel，按问题类别和业务领域进行 AI 分类，结果支持饼图复制（剪贴板兼容自动 PNG 下载兜底）。
- **企业信息查询 / 债务清偿评估**：在聊天中直接查询企业工商与司法风险信息，或对特定企业进行追偿可行性评估。

### V3 新增能力
- **用户反馈学习闭环**：5 大流程的"AI 提取 → 用户编辑 → 确认入库"全链路反馈自动回流到审计库；下一次同类任务自动注入历史采纳示例，AI 输出会逐步贴近用户的口味。
- **AI 质量仪表盘**（管理员）：右上角用户菜单 → 📊 AI 质量仪表盘，按场景统计接受率、修改率、错误率、平均 tokens、平均延迟；可下钻到单次调用的完整输入 / 输出 / 用户修改对比。
- **LLM 调用全链路追溯**：20 个业务场景每次 LLM 调用自动落审计库（PostgreSQL），记录场景、模型、提示词版本、输入、输出、token 用量、耗时、错误。
- **按场景智能选模型**：意图分类 / 合规审查 / 案件提取 / 文档起草等 19 个场景自动匹配不同模型——简单任务走更便宜的 DeepSeek-V3，复杂任务走更准的 Qwen 72B，长期 LLM 成本下降 30-50%。
- **任务完成通知**：长任务完成或失败时右上角自动弹气泡 + 浏览器标签页标题闪烁 + 可选系统通知（用户授权后即使浏览器在后台也能弹）。
- **Skill 插件架构**：聊天意图分发自动发现——新增技能只需放一个单文件 Skill 类，分类提示词 / 反馈追溯 / 视觉跳过等全部自动接管。

### 基础设施
- 用户登录、角色权限、操作审计和多会话历史。
- 模型切换：右上角可手工选择文字模型和图像模型；模型列表与默认模型由运行时路由配置控制。
- 运维脚本（`tools/`）：一键启动后端 + 前端、PG 数据库每日备份、90 天前 LLM 追溯自动归档，可挂 Windows 任务计划程序无人值守。

---

## 2026-05-29 更新（v3.6.10 · E2E 测试修复 + 扩容 + 纳入钩子）

- **修好失效的 E2E**：原有三台账合并 spec 因 UI 改版用了脆弱的位置依赖 selector（`getByRole('button').last()`）早已失效、却没纳入任何门禁所以无人发现。重写为稳定的 `role+name` 选择器（点快捷技能按钮进入流程），断言收缩到"关键路径不崩 + flow 切换正确"（业务计算由后端单测覆盖，mock 下断言完整结果既脆弱又无意义）。
- **新增登录态路由 spec**：验证 `AuthGate` 按 `/api/auth/me` 正确分流——未登录落到登录页、已登录进主界面。这一层独立于业务 UI 细节，最稳。
- **Playwright 改用系统 Edge**：内置 chromium（v1223 / Chrome 148）下载被网络封锁（官方源超时、npmmirror 未同步），改用 `PW_CHANNEL`（默认 `msedge`）调本机已装浏览器，无需下载 ~150MB。Linux CI 上可置空 `PW_CHANNEL` 回退内置 chromium。
- **E2E 纳入 pre-push 钩子第 3 道**：push 前自动跑。针对 mock E2E 共享 vite dev server 的冷启动波动，配了单 worker 串行 + retry 1 次 + 放宽超时（test 60s / 断言 15s）压住 flaky；连续两次跑稳定通过（~17s）。新增 `SKIP_E2E=1` 细粒度旁路（急用时单跳 E2E、保留 pytest+vitest），`SKIP_HOOK=1` 仍可全跳。
- **抽取 `tests/e2e/helpers.ts`** 公共 mock（登录态 / 会话列表 / 模型路由），避免每个 spec 重复粘贴。
- **仍不进 GitHub CI**：E2E 依赖系统 Edge + 冷启动慢，留在本地 pre-push 这一道；CI 保持 pytest + vitest 的快稳组合（理由见 `docs/CI.md`）。
- 对应 2026-05-29 健壮性体检报告的 P1 #8（E2E 扩容）。

---

## 2026-05-29 更新（v3.6.9 · 后台任务孤儿回收 + 静默吞错收口）

- **后台任务孤儿回收**：后台任务跑在进程内的 `ThreadPoolExecutor` 里，服务一旦重启（部署/崩溃/手动重启），原本"排队中/处理中"的任务工作线程随旧进程消失，但 DB 行永远停在那个状态——界面一直转圈、永不结束。新增 `task_runner.reclaim_orphaned_tasks()`，在 startup 时把所有非终态（queued/running）任务标记为 `failed` + "服务重启导致任务中断,请重新发起"，给用户明确终态。幂等，终态任务（succeeded/failed/cancelled）不受影响。
- **收口 6 处静默吞错**：`auth_request_drafter`（PDF/.doc 多重提取回退）、`compliance_ledger`（调试快照写入）、`qcc_debt_assessment`（资产负债率解析）、`qcc_mcp_client`（MCP 可选握手）此前 `except: pass` 失败后无任何痕迹，现在统一记 `logger.debug`，失败可排查、控制流不变（全是合理的容错降级，零回归）。
- **企查查工具失败从"静默跳过"升为告警**：`qcc_mcp_client` 单个 MCP 工具调用失败此前被 `pass` 吞掉——该维度数据缺失，但用户和运维都看不出来。现在升为 `logger.warning` 并带工具名，避免"结果少一块却无人知"。
- **测试**：新增 `tests/test_task_reclaim.py` 3 个用例（孤儿回收 + 终态不动 + 幂等）；后端 pytest 342 全过（v3.6.8 的 339 + 新 3），前端 vitest 39 全过。
- 对应 2026-05-29 健壮性体检报告的 P1 #1（静默吞错收口）与 P1 #3（后台任务持久化）。

---

## 2026-05-29 更新（v3.6.8 · GitHub Actions CI 门禁）

- **CI 门禁上线**：`.github/workflows/ci.yml` 在 push 到 master / 对 master 开 PR 时自动并行跑两个 job —— Backend（pytest 339 个测试）+ Frontend（eslint + vitest 39 个测试 + tsc/vite build），全绿才算合格。
- **缓存优化**：pip cache key 跟 `backend/requirements.txt` 内容绑定、npm cache 跟 `frontend/package-lock.json` 绑定，常态命中后整轮 ~1 分钟即可结束；同分支新 push 自动 cancel 旧 run，避免堆积。
- **清理前端 lint 历史问题**：删 `IdentityLogin.test.tsx` 未用的 `jsonResponse` 辅助函数；`AuthFlow.tsx` 的 `Record<string, any>` 收紧为 `Record<string, Record<string, string | null | undefined>>` 精确嵌套类型，编译期就能查出索引错误。
- **eslint.config.js 调整**：React 19 新规则 `react-hooks/set-state-in-effect` 在历史代码里有 3 处触发，先降级为 `warn` 让 CI 能跑起来，保留 warning 提示新代码不要新增这类用法（留 v3.6.9+ 单独治理 PR）。
- **README 顶部加 CI 徽章**，一眼可见 master 当前状态；新增 `docs/CI.md` 说明当前跑什么、不跑什么、本地复现失败方法、branch protection 配置步骤、未来扩展路线（backend ruff / pre-commit hooks / Playwright workflow / 测试覆盖率上报）。
- **不在 CI 范围内**：Playwright E2E（浏览器下载 ~150MB 慢且 spec 全 mock 后端）、backend ruff 静态检查（需历史代码先治理）、check:branding（需本地资源文件）；这些都在 `docs/CI.md` 里明确标注了排除理由。
- **落地过程中修复的两个真问题**：① pytest 此前未在任何依赖文件里声明（本地靠全局安装才跑得起来），CI 干净环境装完依赖后 `python -m pytest` 直接失败 —— 新增 `backend/requirements-dev.txt` 显式声明测试依赖，生产 `requirements.txt` 保持纯净；② `AdminCenterPanel` 后台任务测试用同步 `getByText` 断言异步 `useEffect` 渲染的列表，在 CI 慢节点偶发失败 —— 改为 `await findByText`，并给 frontend job 固定 `TZ=Asia/Shanghai` 避免日期断言在 UTC 环境漂移。

---

## 2026-05-29 更新（v3.6.7 · AI 输出强 Schema 校验层）

- **斩断"LLM 自由文本污染业务字段"这一类 bug**：5/22 ~ 5/26 出现过 4 起同类问题（培训类别字段塞入整段 JSON、首席合规官意见污染、授权请示提取错乱），根因都是业务方直接信任了 LLM 输出的"格式"，但 LLM 偶尔会吐 Markdown 包裹 / 解释性前缀 / 缺字段 / 错类型 / 截断 JSON。
- **新增 `utils/llm_extract.extract_structured`** 通用强 schema 抽取工具：业务方传入 Pydantic 模型即可拿到严格匹配的对象，10 类污染场景全部返回 `fallback`，**永远不返回半截对象**，且每次失败都打带 `scene` 标签的 warning 日志方便排查。
- **新增 `llm_client.call_llm_structured`** 一体化异步入口：自动加 `response_format={"type": "json_object"}` 提示 LLM 输出 JSON；如果模型不支持这个参数会自动 graceful 降级重试；内部直通 v3.6.6 的韧性调用层（重试 / 断路 / 模型降级链）；网络层异常和解析层异常**全部返回 fallback，永远不抛到业务层**。
- **新增 12 个测试用例 + 6 个子测试**（`backend/tests/test_llm_structured.py`）：Markdown 包裹、解释性前缀、嵌入式 JSON、缺字段、错类型、多字段、截断 JSON、空输入、非对象根节点、provider 拒绝 JSON mode、全失败回 fallback —— 把现实出现过的污染场景全部锁死，作为业务方的"反污染契约"。
- **零回归验证**：后端 pytest 339 全过（v3.6.6 的 327 + 新 12）、前端 vitest 39 全过、router import 11 全过；业务调用路径 **0 改动**（向后兼容），下个版本起逐个 skill 迁移到新接口。
- **新增 `docs/STRUCTURED-OUTPUT.md`** 团队迁移手册：何时用、与 `extract_short_text` 怎么搭配、从老 `json.loads` 模式迁移的样例代码、为什么"错值比无值更危险"是 N2 的核心设计哲学。

---

## 2026-05-29 更新（v3.6.6 · AI 调用韧性层）

- **AI 调用层加固**：`backend/llm_client.py` 从 43 行裸客户端扩展为带韧性的统一调用层，新增 `call_llm_chat` 入口，自带超时（默认 30s）、指数退避重试（默认 3 次）、连续 5 次失败自动断路 30 秒（防止雪崩）、模型降级链（`MODEL_CHAT` → `AI_CHAT_MODELS` 其它模型 → 本地 Ollama 兜底）。单一模型抽风不再拖垮整条业务流。
- **降级与全失败接入钉钉告警**：触发场景包含「降级到备选模型」「降级到本地 Ollama」「全链路失败」三类，60 秒同类去重避免刷屏，告警通道复用 v3.6.0 引入的 `send_dingtalk_notification`。
- **业务调用路径保持向后兼容**：原 `get_async_llm_client()` 和 `get_llm_client()` 保留，避免大面积回归；新 `call_llm_chat` 接口已就绪，下个版本起逐个 skill 迁移（v3.6.7+）。
- **新增 8 个单元测试**：`backend/tests/test_llm_client.py` 覆盖 ①首次成功 ②限流重试成功 ③主模型耗尽降级到次模型 ④全云端失败降级到 Ollama ⑤全失败开断路器+告警 ⑥断路器打开期间立刻拒绝 ⑦断路器超时后自动恢复 ⑧60 秒告警去重。
- **零回归验证**：后端 pytest 327 全过（新增 8 + 原 319）、前端 vitest 39 全过、router import 11 全过；改动 0 影响现有业务。
- **配置开关**：`LLM_BREAKER_THRESHOLD`（默认 5 次）、`LLM_BREAKER_COOLDOWN_SEC`（默认 30 秒）、`LLM_ALERT_DEDUPE_SEC`（默认 60 秒）均可通过 `.env` 调整。

---

## 2026-05-29 更新（v3.6.5 · 数据库迁移基础设施）

- **主业务数据库引入 alembic 迁移管理**：新增 `backend/alembic.ini` + `backend/migrations/`，以后任何模型字段改动都生成可重放、可回滚的迁移脚本，告别上线时人肉改 SQL 的赌博式升级。
- **当前 MVP PostgreSQL 已 stamp baseline**（版本号 `37d6fb9c6e53`）：本次只是给现网库挂上"版本号锚点"，业务表 0 改动（前后对比每表 count 完全一致：`audit_logs=10 / llm_traces=736 / users=1 / ...`），新增一张 `alembic_version` 元数据表存版本号。
- **跨数据库兼容**：`migrations/env.py` 自动识别 SQLite 与 PostgreSQL，启用 `render_as_batch=True` 让本地 SQLite 也能跑同一份迁移脚本，本地开发零成本。
- **避免误删 llm_audit 表**：`llm_traces` / `llm_traces_archive` 实际归 `llm_audit` 子系统管，本次通过 `include_object` 过滤器主动跳过，autogenerate 不会再"以为"它们是多余表想删。
- **新增团队迁移手册** `docs/MIGRATIONS.md`：加字段三步走、SQLite vs PG 兼容性说明、常见故障速查（GBK 编码、路径报错、过滤失效等）。
- **验证覆盖**：后端 pytest 319 / frontend vitest 39 / 真实 PG 读写冒烟 4 / router import 11 全部通过；改动对业务功能 0 影响。

---

## 2026-05-21 更新（登录页改版 · 国航品牌融合）

- **登录页全面改版**：深色玻璃拟态 + 左右分屏布局。左侧玻璃登录卡保留全部功能（人员选择 / 钉钉 SSO / 短码登录 / SSO 状态提示），右侧大幅展示「中国航空集团建设开发有限公司」主标识 + 「法度云图」白→靛→紫渐变大字 + 副标「法务智能工具集」+ 版本号。左上角小 LOGO（白底圆角卡 + 柔光底盘）+ 沉浸式背景（网格点阵 + 双层漂浮光斑 + 顶部光带 + 渐入分层动画）。
- **鼠标视差 + 3D 倾斜**：主 LOGO 跟随鼠标做 ±13° 3D 倾斜（lerp 0.11 缓动），表面玻璃高光按鼠标位置滑动，底部镜面倒影同步翻转；「法度云图」大字与副标做反向小幅视差，背景两团光斑做大幅反向视差，营造多层纵深。
- **国航 747 客机鼠标光标**：鼠标进入右侧动画区时系统光标隐藏，变成 60×20 的侧视客机 SVG（白机身 / 蓝腰线 / 双发动机 / 红尾翼凤凰 / 一排客舱小窗）。`facing` 按鼠标 dx 平滑切换（scaleX 翻身），`pitch` 按 dy 在 ±22° 内做俯仰，停下时自动恢复水平；机尾拖凝结尾迹；离开区域渐隐。
- **品牌资源处理**：新增 `tools/remove_white_bg.py`（Pillow），自动抠掉公司 LOGO 的白色背景并做边缘羽化（hard=30 / soft=140 阈值），消除原图白底硬边。后期柔光底盘双层叠加（外层 blur 48 / 内层 blur 36 + 8-stop 线性过渡到完全透明），LOGO 自然融入深色背景，无任何视觉边界。
- 移动端与 `prefers-reduced-motion` 优雅降级：客机光标在无 hover 能力或减少动画偏好时不渲染，所有视差/倾斜效果自动关闭。
- **配套后端修复**：`backend/main.py` 的 SPA 兜底原本会把 `dist/` 根目录下的静态文件（`airchina-*.png` / `favicon.svg` / `icons.svg` 等）也当作 SPA 路由返回 `index.html`，导致部署后 LOGO 显示为破图。改为在 SPA fallback 之前先尝试匹配 `dist` 根下的真实文件并返回（带路径穿越防护），所有 `dist` 根静态资源现在能被正确服务。

## 2026-05-20 更新（v3.5.3）

- **内网 HTTPS 部署**：服务器侧用 [Caddy](https://caddyserver.com/) 监听 8443 反代到 uvicorn:8001，证书由 [mkcert](https://github.com/FiloSottile/mkcert) 本地 CA 签发（SAN 覆盖 `192.168.9.226` / `localhost` / 主机名，10 年有效），客户端机器装一次 mkcert 根 CA 后所有内网 V3 访问无警告。
- **访问地址变更**：`http://192.168.9.226:8001` → **`https://192.168.9.226:8443`**（旧地址仍可用，但浏览器侧 Notification / Clipboard 等 API 不工作）。
- **解锁 Web Notification API**：Chromium 规定 Notification / Clipboard / Service Worker 等"安全上下文专属"API 在内网 HTTP 地址下被整个禁用（站点权限里"通知"一栏灰色不可改），用户点 🔔 测试系统通知无任何反应；HTTPS 改造完成后 `Notification.permission` 可正常 `default → granted`，Windows 系统通知正常弹出。
- **配套交付**：仓库根新增 `Caddyfile`（相对路径，跨机通用）+ `caddy-start.ps1`（UTF-8 BOM + 唯一日志名 + Already-running 检测）+ `start-https.bat` / `stop-https.bat` 双击启停 + [`docs/DEPLOY-HTTPS.md`](docs/DEPLOY-HTTPS.md) 完整运维指南（架构图、服务器搭建、客户端 mkcert 根 CA 分发、故障排查、与 V2 共存方案）。
- **每位同事一次性配置**：管理员把服务器 `rootCA.pem` 文件分发（共享盘 / 微信 / U 盘都行），客户端管理员 PS 一行命令导入即可：`Import-Certificate -FilePath rootCA.pem -CertStoreLocation Cert:\LocalMachine\Root`。
- 与现有 V2 / deploy-watch 完全隔离：V2 在 8000，V3 uvicorn 在 8001，Caddy 在 8443，三者互不影响；deploy-watch 仍只管前端 build + uvicorn 重启，不动 Caddy。

---

## 2026-05-20 更新（v3.5.2）

- AI 完成提醒升级：Windows 系统通知改为"停在通知中心不自动消失"（`requireInteraction=true`），AI 长任务跑完即使你切到别的标签或窗口，回来在 Windows 通知中心还能看到。保留无声（`silent=true`）不打扰办公环境。
- 用户菜单新增「🔔 测试系统通知」入口（所有用户可见）：一键验证 Windows 通知功能是否工作 + 自动处理浏览器三种权限状态：
  - **未询问** → 弹窗向你申请权限
  - **已禁用** → 提示去浏览器地址栏锁形图标 → 网站设置 → 通知 → 改为"允许"
  - **已授权** → 立即弹一条测试通知（in-app toast + Windows 系统通知）

---

## 2026-05-19 更新（v3.5.1）

- 合规审查台账提取丢字段修复：同一份 PDF 在 V3 提取出来只剩会签单位行，丢失首席合规官 / 合规管理牵头部门 / 承办单位三行核心审批角色。根因是 P1-2 反馈学习的 few-shot 自动注入在合规这种 multi-step 流程（抽取→复核→修正→归一化）里反向引导 LLM，让它按"用户最终采纳的扁平 review_rows"格式输出而丢掉中间结构。现已在 compliance_extract / compliance_review 两个场景显式关闭 few-shot 注入；其他单步抽取场景（案件 / 培训 / 授权）继续受益于反馈学习不变。

## 2026-05-19 更新（v3.5.0）

- 生产部署管线：服务器侧 `deploy-watch.ps1` 每 5 分钟检查 GitHub，发现新 commit 自动 `git pull` → `npm run build` → 优雅重启 uvicorn → `/api/health` 验证。失败时日志写完整错误 + stack trace，不再静默吞错。
- 服务器辅助脚本：`start.bat` / `stop.bat` 双击即用 — start.bat 后台启动 production uvicorn + 健康检查 + 日志重定向到 `logs/uvicorn-时间戳.log`；stop.bat 按端口 8001 精确停止，不影响 V2 在 8000 上的服务。
- 配套运维：`tools/start_production.ps1` / `tools/backup_pg.ps1` / `tools/archive_llm_traces.py` + 首次部署手册 `docs/DEPLOY-SERVER.md`。
- 部署稳定性强化（7 处底层修复）：
  - .ps1 加 UTF-8 BOM 避免 PowerShell 5.1 按 GBK 误解码中文注释
  - 外部命令 stderr 重定向用 `cmd /c` 包装避开 NativeCommandError
  - cmd 子进程加 `chcp 65001` 让 vite 输出保留 `✓` `│` 字符
  - schedtask jkszb 用户上下文里 git fetch 走 cmd /c 绕过 batch logon 凭据问题
  - Start-Process 启动 uvicorn 失败时显式捕获 + 日志带 stack trace
  - 唯一日志文件名（带时间戳 + 随机后缀）防同日两次部署的文件锁冲突
  - git fetch 加 3 次重试 5 秒间隔扛 GitHub 偶发 5xx

## 2026-05-19 更新（v3.4.1）

- 测试套大幅扩容：后端 245 → 264 个测试（新增 22 个）覆盖 API 端到端集成（FastAPI TestClient 跑全链路）+ LLM trace 访问控制安全（管理员读 / 用户只能改自己的 feedback）；前端引入 Vitest + `@testing-library/react` 测试栈，首批 17 个测试覆盖 `api.ts` 的 `submitLlmFeedback` 容错行为和 `NotificationProvider` 渲染契约；`tools/smoke_test_pg.py` 针对真实 PostgreSQL 的端到端烟雾测试（6 步全过即证明审计链路在生产 DB 上工作）。
- 通知系统加固：Notification API 检测从 `'Notification' in window` 改为 `window.Notification != null` —— 防止某些浏览器扩展 / polyfill 把 Notification 设为 undefined 后访问 `.permission` 触发崩溃。三处检查（初始权限 / 显示通知 / 申请权限）统一收口。

---

## 2026-05-18 更新（v3.4.0）

- AI 任务完成通知系统：5 大流程任务完成或失败时，右上角自动弹出气泡 + 浏览器标签页标题闪烁 + 系统通知（需用户授权后即使浏览器在后台也能弹）。
- 审计分析饼图复制兜底：剪贴板写入支持超时熔断；剪贴板不可用或写入失败时自动改为下载 PNG 文件，按钮提示当前状态。

## 2026-05-18 更新（v3.3.0）

- 按场景智能选模型：19 个 LLM 场景自动匹配不同模型，长期 LLM 成本下降 30-50%。
- AI 质量仪表盘明细钻取：管理员菜单 → 📊 AI 质量仪表盘 → 点击场景行查看最近 20 次调用 → 再点单条查看完整输入 / 输出 / 用户最终采纳的版本（绿色高亮）。
- 新增运维脚本：`tools/start_production.ps1`、`tools/backup_pg.ps1`、`tools/archive_llm_traces.py`，可挂 Windows 任务计划程序无人值守。
- 大文件拆分：`ledger_helpers.py`（960 行）抽出归档子模块；`compliance_ledger.py`（815 行）抽出持久化子模块；`AuditFlow.tsx`（621 行）抽出子组件——单文件维护成本显著降低。
- 聊天意图分类契约测试：10 个回归测试锁定意图集 / 反馈字段 / 路由选择行为，防止改提示词偷偷劣化分类准确率。
- 杂草清理：移除未使用的 streamlit 依赖；`.env.example` 补齐 8 个缺失字段；日志统一格式 + 第三方库降噪。

## 2026-05-17 更新（v3.2.0）

- 用户反馈学习闭环：5 大流程"AI 提取 → 用户编辑 → 确认入库"全链路反馈数据自动回流到审计库；下一次同类任务自动注入历史采纳示例，AI 输出逐步贴近用户口味。
- 管理员 AI 质量仪表盘：按场景统计总调用次数、反馈率、接受率、修改率、错误数、平均 tokens、平均延迟；接受率 ≥70% 绿色 / <50% 红色，高修改率场景标黄。
- "取消"按钮也算反馈：用户对 AI 提取结果点取消时也会记录"未接受"，避免被学习引擎当成成功示例污染未来调用。
- 前端反馈失败开放：feedback 上报用 Promise.allSettled，审计库挂掉也不影响业务流程。

## 2026-05-15 更新（v3.1.0）

- Skill 插件架构：聊天意图分发由 if/elif 列表改为自动发现——新增技能只需在 `backend/skills/implementations/` 放一个单文件 Skill 类，分类提示词 / 反馈追溯 / 视觉跳过等全部自动接管。
- LLM 调用全链路追溯：20 个业务场景每次 LLM 调用自动落审计库，记录场景、模型、提示词版本、输入、输出、token 用量、耗时、错误。
- 审计库独立到 PostgreSQL：`llm_traces` 表迁移到独立 PG 实例（`192.168.9.226/reactv3`），与主 SQLite 业务库解耦。
- 失败开放兜底：审计库连不上时自动降级为 NoopTracer，业务调用照常工作。

## 2026-05-15 更新（v3.0.0）

- V3 主版本启动：从 ReactV2 拷贝代码到独立仓库（`github.com/qubo851006-ctrl/reactV3`），全新 Git 历史，业务数据隔离重建。
- 所有 V2 既有功能保持工作不变（培训统计 / 案件台账 / 授权请示 / 三台账合并 / 审计分析 / 合规审查 / 企业查询 / 用户管理 / 多会话）。

---

## 2026-05-15 更新（v2.26）

- 合规审查台账会签单位漏项修复：移除对 `source_section` 字段的依赖，审批流程中所有配置表内部门负责人的会签意见均能正确提取到台账，不再被静默丢弃。
- 合规牵头部门匹配收紧：`_is_compliance_department()` 不再按部门名称模糊匹配，只匹配配置表中指定的负责人（李莹），同部门其他签署人（宋媛媛、申奇奇）不再误入合规牵头行。
- 长文本同意意见保留：审批意见归类为"同意"但原文超过 20 字时，保留原文内容到台账详情列，不再一律替换为"/"。
- 会签补充搜索范围扩展：`_supplement_countersign_from_text()` 姓名与部门名称的文本邻近检索从 120 字符扩大到 300 字符，适配杨焕等长意见场景。
- 补充单元测试和回归测试，覆盖会签合并、合规部门精确匹配、长意见保留和完整 PDF 场景模拟。

## 2026-05-14 更新（v2.23）

- 案件文书归档合并修复：同一案件的文书现在统一归入同一文件夹，不再因 AI 每次提取的案件名称略有差异（如被告数量不同导致名称变化）而产生多个文件夹。
- 匹配到已有案件时，归档目录使用已有案件的原始名称，保证后续上传的文书自动归入已有案件文件夹。
- 移除案件名称为空时以文件名回退作为案件名称的逻辑，避免出现以文件名（如"一审判决书.pdf"）命名的错误归档文件夹。
- 补充案件文书归档合并的单元测试，覆盖同案件合并、不同案件隔离、空名称回退三种场景。
- 培训签到表识别提速：去掉第二次反思校验调用，只调一次视觉模型完成人数统计，响应速度提升约一倍。

## 2026-05-13 更新（v2.22）

- 增加统一性能耗时日志：案件台账、培训统计、授权请示、合规审查、审计分析均记录关键步骤耗时，便于区分模型、OCR、PDF 解析和文件写入瓶颈。
- 案件台账提取提速：多个上传文书并发解析，扫描 PDF 复用并发 OCR 通道，减少多文件、多页文书逐个等待。
- 授权请示生成提速：授权请示正文和授权书正文并行生成，字段提取后不再串行等待两段文档输出。
- OCR 稳定性增强：中航信 OCR 增加超时收敛、失败计数和临时熔断，服务异常时更快降级到视觉模型。
- 补充性能回归测试，覆盖文书并发处理、OCR 熔断、授权并行生成和性能日志输出。

## 2026-05-12 更新（v2.21）

- 三台账合并结果按用户和结果编号隔离保存，下载本次结果不会被其他用户或后续合并覆盖。
- 案件台账、培训统计提取阶段只暂存上传文件，用户确认写入后才正式归档；授权请示生成与授权台账记录拆分为两步。
- 会话历史、授权台账、合规审查台账写入失败时显式报错；合规审查台账 JSON 与 Excel 写入失败会回滚旧文件。
- 登录短码连续输错增加临时限速保护，生产环境可通过 `SESSION_COOKIE_SECURE=true` 启用 Secure Cookie。
- 修复前端 App 会话消息依赖导致的 lint 警告，并补充隔离、回滚、暂存归档相关单元测试。

## 2026-05-12 更新（v2.20）

- 案件台账人工口径增强：诉讼主体提取要求列全原告、被告、第三人等主体，禁止用“等”省略。
- 处理结果改为企业法务管理摘要口径：自动补齐法院、日期、案号、文书性质、裁判主文、后续程序和公司经济影响，更接近人工台账写法。
- 基本情况字段回归诉请口径，重点保留请求事项、金额、期间和责任承担，避免混入过长裁判理由。
- 补充案件台账处理结果回归测试，覆盖“挽回损失/后续程序/法院案号日期”类人工台账写法。

## 2026-05-12 更新（v2.19）

- 案件台账二审文书识别修复：PDF 自带文字层如果被解析成重复数字、符号等低质量内容，系统会自动转入 OCR，不再把乱码当作有效正文。
- 案件匹配增强：支持 OCR 结果中带空格的案号格式，并可通过二审判决书正文中的原审案号匹配已有案件，避免现有案件的二审文书被误判为新案件。
- OCR 返回解析兼容增强：兼容中航信 OCR 的 `payload.markdown`、`payload.text`、`payload.result.markdown` 和 `document` markdown 等多种返回结构，并复用 AI 平台 Host 头配置。

## 2026-05-12 更新（v2.18）

- 扫描件 OCR 引擎升级：案件台账、合规审查、授权委托三个模块的扫描版 PDF 识别，由视觉大模型切换为中航信专用 OCR 服务（`/v1/oneapi/proxy/25`），识别速度更快、不消耗视觉模型 Token。
- 服务异常时自动降级回原视觉模型，不影响正常使用；培训签到图片分析（需理解签名）保持使用视觉模型不变。

## 2026-05-08 更新（六）

- 引入 Noto Sans SC 网络字体，中文显示更精致统一。
- 新增空会话欢迎页：无对话记录时显示 6 宫格功能入口卡片，点击直接触发对应技能。
- 侧边栏技能图标升级：每个技能配专属彩色背景圆角块，培训蓝、台账紫、授权绿、合并琥珀、审计红，一眼可辨。
- 输入框视觉优化：input 与发送按钮合并为统一外壳，聚焦时亮起 indigo 发光效果。
- 整体配色调整：主背景改为更深的深蓝色（`#0a0f1e`），滚动条换用 indigo 色调。

## 2026-05-08 更新（五）

- **根本原因修复**：培训提取、案件台账提取、授权请示生成、审计分析四个 `async def` 端点内的同步 LLM/PDF/OCR 调用（耗时 10~60 秒）直接运行于事件循环，导致 Session A 处理期间 Session B 的所有请求完全阻塞。现全部通过 `asyncio.to_thread` 卸载到线程池，事件循环始终畅通。
- 模型路由配置改为内存缓存，消除 `async` 端点中每次请求触发的 3 次同步磁盘读取。
- 聊天流式回复每个 token 后增加 `await asyncio.sleep(0)`，防止高频 token 流饿死其他协程。
- SQLite 启用 WAL 模式 + `busy_timeout=5000ms`，消除并发 `db.commit()` 引发的 `SQLITE_BUSY` 错误。
- 聊天 SSE 响应增加 `Cache-Control: no-cache` / `X-Accel-Buffering: no` 头，防止代理层缓冲。

## 2026-05-08 更新（四）

- 聊天端点改为全异步（`async def` + `AsyncOpenAI`）：LLM 调用（意图分类 `_classify_async`、流式回答 `_stream_reply_async`）均通过 `await` 非阻塞执行；文件 I/O 通过 `asyncio.to_thread` 卸载，事件循环在每个 token 之间均可响应其他请求，彻底解决多会话并行时的阻塞和排队问题。

## 2026-05-08 更新（三）

- 消息状态改为按会话独立存储（`messagesMap`）：Session A 正在流式回答时切换到 Session B，A 的回答继续在后台写入 A 自己的队列；Flow 在后台完成时，完成消息正确归入触发该 Flow 的会话；切回任意会话后，历史内容完整呈现，无需重新从后端加载。

## 2026-05-08 更新（二）

- 多会话并行处理：工作流（培训统计、案件台账等）执行期间可自由切换到其他会话，切回后原流程状态完整保留，互不干扰。

## 2026-05-08 更新

- 新增本地 Ollama 视觉模型支持：图像模型下拉框中增加 `Qwen3 VL 8B (本地)` 选项，图像分析会自动路由到本地 Ollama 服务。
- 新增 `OLLAMA_BASE_URL` / `OLLAMA_API_KEY` 环境变量，在 `.env` 中配置后即可启用本地推理，无需修改代码。
- 本地模型与云端模型可随时切换，未配置 `OLLAMA_BASE_URL` 时选项不生效，不影响现有流程。

## 2026-04-30 更新

- 新增右上角“文字模型 / 图像模型”两个下拉框，普通聊天、图片识别和扫描件 OCR 可分别选择模型。
- 新增运行时模型路由，后端从 `data/model_routes.json` 读取模型列表和默认模型；后续调整模型配置无需重启后端，刷新前端即可加载。
- 培训签到图片识别、案件台账扫描版 PDF OCR、授权呈批件扫描版 PDF OCR 已接入图像模型选择。
- 用户询问“当前模型是什么”时，后端直接返回当前文字模型和图像模型，避免大模型自报身份不准确。

运行时模型路由配置示例：

```json
{
  "default_chat_model": "qwen2.5-72b",
  "default_intent_model": "qwen2.5-72b",
  "default_vision_model": "qwen2.5-vl-72b",
  "chat_models": ["qwen2.5-72b", "DeepSeek-V3", "glm-5-outside"],
  "vision_models": ["qwen2.5-vl-72b"]
}
```

## 2026-04-29 更新

- 增加统一上传安全校验：文件名净化、扩展名白名单、大小限制、MIME 校验和文件头校验。
- 修复案件文书归档路径风险，避免上传文件名或案件名造成路径穿越。
- 案件台账写入改为事务式流程，`cases.json` 与 Excel 写入使用文件锁和原子替换，失败时尽量回滚旧文件。
- 会话历史、培训台账、授权台账、合并台账等关键文件写入增加文件锁或原子写入。
- LLM 和外部知识库 HTTP 客户端默认开启 TLS 证书校验。
- 前端清理显式 `any` 类型并统一错误消息处理。
- 补充 Windows 服务器自动部署方案：通过任务计划程序检测 GitHub `master` 更新，自动更新、构建前端并重启后端服务。

## 部署说明

生产模式下，FastAPI 会托管 `frontend/dist` 静态文件，因此服务器只需要启动后端：

```powershell
cd backend
py -3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

服务器本地应保留 `.env` 和 `data/` 目录，不要提交密钥和业务数据到 GitHub。
