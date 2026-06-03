import type { VersionEntry } from './branding'

export const VERSION_ENTRIES: VersionEntry[] = [
  {
    version: 'v3.6.16',
    date: '2026-06-03',
    changes: [
      { type: 'fix', text: '强 schema 接入台账抽取:此前 v3.6.7 建好的 extract_structured(防 LLM 吐脏 JSON 污染业务字段)业务零调用。本次给案件台账的四类文书抽取(起诉状/上诉状、判决/裁定、强制执行申请书、业务情况说明)接上 Pydantic 严格校验,新增 ledger_schemas.py 定义四套 schema。LLM 抽取结果写入台账前先过校验:多吐的污染字段直接丢弃、漏字段不致整条作废、标的金额(数字字符串→float、纯叙述文本→null)按财务规范类型规整。' },
      { type: 'fix', text: '行为保持:替换原裸 json.loads(_parse_json),校验彻底失败(非 JSON/非对象/空)时抛 ValueError,沿用原"该文书字段提取失败"的用户可见提示与线程池兜底,不静默吞错、不把脏数据写进台账。字符串字段收到数字时强转(coerce_numbers_to_str)而非作废,降低回归风险。单标签场景(培训类别等)此前已用 extract_short_text 护住;compliance 多步嵌套流水线容错性强,暂不接入。' },
      { type: 'fix', text: '新增 15 个 schema 单测(合法解析/标的金额三态/污染字段丢弃/markdown 包裹/解释性前缀/漏字段/非 JSON 抛错/数组非对象抛错等)。后端 pytest 395 全过,ruff 全绿。' },
    ],
  },
  {
    version: 'v3.6.15',
    date: '2026-06-03',
    changes: [
      { type: 'fix', text: 'LLM 韧性层真正接入业务:此前 v3.6.6 建好的重试/退避/断路器/模型降级链/钉钉告警一直"挂在墙上"业务零调用。本次把韧性下沉进 llm_audit.traced_complete——新增同步版 llm_client.complete_with_resilience,复用同一套断路器/降级链/告警状态,用调用方传入的 client 在 qwen→DeepSeek→GLM→本地 Ollama 链上自动轮换。台账抽取、审计、培训、合规、影像分析等全部 9 个走 traced_complete 的业务点零改动即获得韧性,且完整保留 LLM 调用审计追踪(降级后 trace 记录的是实际服务的模型)。单一模型抽风不再拖垮业务。' },
      { type: 'fix', text: '契约保持:全链路失败仍按原样抛出 RuntimeError(traced_complete 对调用方的错误传播契约不变),中间的重试/降级对业务透明。新增 9 个同步韧性单测(镜像异步层 8 场景 + 1 个降级后记录实际模型的集成测试);后端 pytest 380 全过,ruff 全绿。' },
    ],
  },
  {
    version: 'v3.6.14',
    date: '2026-06-02',
    changes: [
      { type: 'refactor', text: '后端接入 ruff 静态检查:保守规则集(pyflakes F + pycodestyle E4/E7/E9),配置见 backend/ruff.toml。清理历史问题——删除真正未用的 import 和空 f-string;门面模块(ledger_helpers / compliance_ledger,re-export 子模块符号)和测试目录用 per-file-ignore 豁免误报;删掉 ledger.py 一处死代码变量。ruff check 全绿。' },
      { type: 'refactor', text: 'ruff 接入 CI backend job(pytest 前) + pre-push 钩子(第 1 道,最快)。auto-fix 过程中险些误删两个门面模块的 re-export import,被 import smoke + 全套测试拦下并修正——印证了"先有安全网再动"的价值。后端 pytest 371 全过。' },
    ],
  },
  {
    version: 'v3.6.13',
    date: '2026-06-02',
    changes: [
      { type: 'feat', text: '操作审计查询前端:管理员中心新增"操作审计"标签页,可查看"谁在何时对什么做了什么"。展示操作人、操作类型、摘要、目标对象、IP 和时间,支持按操作类型关键词筛选,最近 200 条。登录、台账写入、培训归档、授权请示等关键操作此前已落库但只能查数据库,现在管理员前端直接可查。' },
      { type: 'feat', text: '后端 /api/admin/audit-logs 接口增强:补齐 user_name(批量 join 避免 N+1)、target_type/target_id 字段,新增 action 关键词筛选和 limit 参数(上限 500)。' },
    ],
  },
  {
    version: 'v3.6.12',
    date: '2026-06-02',
    changes: [
      { type: 'perf', text: '前端打包拆分:vite manualChunks 把重库拆成独立 vendor chunk,主应用包从 1.1MB 降到 220KB(gzip 63KB)。recharts 图表(charts 332KB)、html2canvas(200KB)、react-vendor(178KB)、react-markdown(154KB)各自独立,更新频率低的库可被浏览器独立缓存,首屏并行下载也更快。' },
      { type: 'perf', text: 'chunkSizeWarningLimit 调到 700KB,build 不再因单包过大报警告。进一步的路由级懒加载(React.lazy 让 charts 真正按需)留作后续可选优化。' },
    ],
  },
  {
    version: 'v3.6.11',
    date: '2026-06-02',
    changes: [
      { type: 'refactor', text: '接入测试覆盖率统计:后端 pytest-cov(配 .coveragerc 排除测试/迁移),前端 @vitest/coverage-v8 + npm run test:coverage。基线——后端业务代码 63%、前端 30%。' },
      { type: 'refactor', text: '新增 docs/COVERAGE.md 记录基线、运行方法和已知盲区:excel_merger.py(三台账合并核心计算)仅 7% 覆盖最该补,mcp_client/write_excel/pdf_reader 等旧工具 0%。当前不强制阈值,作为后续重构的安全网与"不要倒退"参照。' },
    ],
  },
  {
    version: 'v3.6.10',
    date: '2026-05-29',
    changes: [
      { type: 'fix', text: 'E2E 测试修复+扩容:原有三台账合并 spec 因 UI 改版用了脆弱的位置依赖 selector(getByRole("button").last())已失效,重写为稳定的 role+name 选择器(点快捷技能按钮进入流程);新增登录态路由 spec(未登录落登录页 / 已登录进主界面)。' },
      { type: 'fix', text: 'Playwright 改用系统 Edge 运行(PW_CHANNEL,默认 msedge):内置 chromium 下载被网络封锁,改调本机已装浏览器即可跑,无需下载 ~150MB。' },
      { type: 'refactor', text: 'E2E 纳入 pre-push 钩子第 3 道:push 前自动跑(单 worker 串行 + retry 1 次 + 放宽超时,压住共享 dev server 的冷启动波动)。新增 SKIP_E2E=1 细粒度旁路,急用时可单跳 E2E 保留 pytest+vitest。' },
      { type: 'refactor', text: '抽取 tests/e2e/helpers.ts 公共 mock(登录态/会话/模型路由),避免每个 spec 重复粘贴。' },
    ],
  },
  {
    version: 'v3.6.9',
    date: '2026-05-29',
    changes: [
      { type: 'fix', text: '后台任务孤儿回收：服务重启后，原本卡在"排队中/处理中"的任务因为工作线程已随旧进程消失，会永远停在那个状态、界面一直转圈。现在启动时自动把这类僵尸任务标记为"失败 · 服务重启中断，请重新发起"，给用户明确终态。' },
      { type: 'fix', text: '收口 6 处静默吞错：PDF/.doc 多重提取回退、合规调试快照、资产负债率解析、MCP 可选握手等容错场景此前失败后无任何日志，现在统一记 debug 便于排查。' },
      { type: 'fix', text: '企查查 MCP 单个工具调用失败此前被静默跳过——该维度数据缺失但用户和运维都看不出来，现在升为 warning 日志并带工具名，避免"结果少一块却无人知"。' },
    ],
  },
  {
    version: 'v3.6.8',
    date: '2026-05-29',
    changes: [
      { type: 'refactor', text: 'GitHub Actions CI 门禁上线：每次 push 到 master 或开 PR 自动并行跑 backend pytest 339 个测试 + frontend lint + vitest 39 个测试 + tsc/vite build，全绿才算合格；带 pip / npm 缓存，常态命中后整轮 ~1 分钟。' },
      { type: 'fix', text: '清理前端 lint 历史问题：删 IdentityLogin.test.tsx 未用的 jsonResponse 辅助函数；AuthFlow.tsx 的 Record<string, any> 收紧为嵌套 Record<string, Record<string, string | null | undefined>> 精确类型，编译期就能查出索引错误。' },
      { type: 'refactor', text: 'eslint.config.js 把 React 19 新规则 react-hooks/set-state-in-effect 降为 warn，避免历史代码批量返工阻塞 CI；同时保留 warning 提示新代码不要新增这类用法。' },
      { type: 'refactor', text: '新增 docs/CI.md：当前跑什么、不跑什么、本地复现失败、branch protection 配置步骤、未来扩展路线（ruff / pre-commit / Playwright workflow）。' },
      { type: 'refactor', text: 'README 顶部加 CI 徽章，一眼可见 master 状态。' },
      { type: 'fix', text: '补齐缺失的测试依赖：pytest 此前未在任何依赖文件里声明（本地靠全局安装才跑得起来），导致 CI 干净环境装完依赖后 python -m pytest 直接失败。新增 backend/requirements-dev.txt 显式声明测试依赖，生产 requirements.txt 保持纯净。' },
      { type: 'fix', text: '修复 AdminCenterPanel 后台任务测试在 CI 慢节点上的偶发失败：getByText 是同步断言，但任务列表通过 useEffect 异步渲染，改为 await findByText 等待渲染完成；CI frontend job 固定 TZ=Asia/Shanghai 避免日期断言在 UTC 环境漂移。' },
    ],
  },
  {
    version: 'v3.6.7',
    date: '2026-05-29',
    changes: [
      { type: 'refactor', text: 'AI 输出强 schema 校验层：新增 extract_structured 通用工具，业务方传入 Pydantic 模型即可拿到严格匹配的对象；缺字段、类型错、Markdown 包裹、解释性前缀、嵌入式 JSON、截断 JSON、数组根节点等 10 类污染场景全部返回 fallback，绝不让"半截 JSON"流入业务字段。' },
      { type: 'refactor', text: '新增 call_llm_structured 一体化入口：自动加 response_format=json_object 提示 LLM 输出 JSON，模型不支持时自动 graceful 降级；内部直通 v3.6.6 的韧性调用层（重试/断路/降级链），网络异常或解析异常全部返回 fallback，绝不抛到业务层。' },
      { type: 'fix', text: '所有失败路径打 scene 标签日志，定位"哪个业务场景在污染"成本降到看一行 logger.warning。' },
      { type: 'fix', text: '新增 backend/tests/test_llm_structured.py 12 个用例 + 6 个子测试覆盖：Markdown 包裹、解释性前缀、嵌入式 JSON、缺字段、错类型、多字段、截断、空输入、非对象根节点、provider 拒绝 JSON mode、全失败 fallback。后端整套 pytest 共 339 个全部通过。' },
      { type: 'refactor', text: '新增 docs/STRUCTURED-OUTPUT.md 团队手册：何时用、与 extract_short_text 怎么搭配、从老 json.loads 模式迁移的样例代码。' },
    ],
  },
  {
    version: 'v3.6.6',
    date: '2026-05-29',
    changes: [
      { type: 'refactor', text: 'AI 调用层加固：新增 call_llm_chat 高层入口，自带超时、指数退避重试、连续 5 次失败自动断路 30 秒、模型降级链（首选 → 备选云端 → 本地 Ollama 兜底），单一模型抽风不再拖垮整条业务流。' },
      { type: 'refactor', text: '降级与全失败接入钉钉告警：触发场景包含"降级到备选模型"、"降级到本地 Ollama"、"全链路失败"三类，60 秒同类去重避免刷屏，告警通道复用 v3.6.0 引入的 send_dingtalk_notification。' },
      { type: 'refactor', text: '业务调用路径暂未切换，仍走旧的 AsyncOpenAI 注入方式（保留向后兼容）；新 call_llm_chat 接口已就绪，下个版本起逐个 skill 迁移。' },
      { type: 'fix', text: '新增 backend/tests/test_llm_client.py 共 8 个测试用例覆盖：成功、限流重试、模型降级、Ollama 兜底、全失败告警、断路器拒绝、断路器自动恢复、告警去重；后端整套 pytest 327 个全部通过。' },
    ],
  },
  {
    version: 'v3.6.5',
    date: '2026-05-29',
    changes: [
      { type: 'refactor', text: '主业务数据库引入 alembic 迁移管理：以后增删字段都有可重放、可回滚的脚本，告别上线时人肉改 SQL；当前 MVP PostgreSQL 已 stamp 为 baseline，业务数据 0 改动。' },
      { type: 'refactor', text: '迁移环境自动识别 SQLite 与 PostgreSQL，本地开发和生产共用一份迁移脚本；llm_audit 子系统的 llm_traces / llm_traces_archive 通过 include_object 过滤跳过，不会被误判为多余表删除。' },
      { type: 'refactor', text: '新增 docs/MIGRATIONS.md 团队迁移手册：加字段三步走、SQLite vs PG 兼容性说明、常见故障速查。' },
    ],
  },
  {
    version: 'v3.6.4',
    date: '2026-05-26',
    changes: [
      { type: 'fix', text: '授权委托书 .doc 增加无 Office 环境的二进制文本兜底解析，服务器未安装 Word 或 LibreOffice 时仍可提取老式 Word 授权书。' },
      { type: 'fix', text: '授权请示 DOCX 字体统一为仿宋_GB2312，中文、字母和数字使用同一字体输出。' },
      { type: 'fix', text: '授权台账写入增加编号去重：同一授权编号再次生成时更新原行，不再新增重复记录；授权起止日期自动去掉“授权期限：”前缀。' },
    ],
  },
  {
    version: 'v3.6.3',
    date: '2026-05-25',
    changes: [
      { type: 'feat', text: '授权请示起草流程重做：支持上传依据文件 PDF 和授权委托书（PDF / DOC / DOCX），先提取字段，再由用户确认直接授权或转授权、补填经办人、份数和印章。' },
      { type: 'fix', text: '优化依据文件 PDF 抽取，避免页码、噪声文本混入项目名称、标题和生成文件名；上传入口支持拖拽选择材料。' },
      { type: 'feat', text: '授权请示正文改为固定模板生成，按附件3版式输出 DOCX：仿宋_GB2312、三号正文、固定行距、首行缩进和附件清单格式保持一致。' },
      { type: 'feat', text: '授权台账写入改为下载请示后自动触发，台账字段按授权台账示例填充，授权起止日期保留为单列，办理时间、文号、归档日期等后续归档字段仅保留表头。' },
    ],
  },
  {
    version: 'v3.6.2',
    date: '2026-05-20',
    changes: [
      { type: 'feat', text: '主业务数据库支持 PostgreSQL：新增 APP_DATABASE_URL，用户、会话、审计日志、钉钉通知日志和同步日志可切换到 PG；未配置时继续回退 data/auth.db SQLite，保持本地开发体验不变。' },
      { type: 'feat', text: '新增 tools/check_main_db.py 主库健康检查脚本，可直接查看当前主库 backend、连接 URL（隐藏密码）和核心表是否就绪，方便服务器迁移和运维排查。' },
      { type: 'feat', text: '新增 tools/migrate_main_sqlite_to_pg.py 迁移脚本，支持先 dry-run 查看 SQLite 行数，再显式 --execute --force 将现有 auth.db 主业务数据导入 PostgreSQL。' },
    ],
  },
  {
    version: 'v3.6.1',
    date: '2026-05-20',
    changes: [
      { type: 'feat', text: '管理员菜单新增“钉钉管理”面板：集中测试群机器人通知、企业应用凭证、个人工作通知，并可一键同步通讯录。' },
      { type: 'feat', text: '钉钉管理面板展示最近同步日志和通知日志，方便排查消息是否发送、同步是否成功、钉钉返回码或跳过原因。' },
    ],
  },
  {
    version: 'v3.6.0',
    date: '2026-05-20',
    changes: [
      { type: 'feat', text: '钉钉集成第一阶段上线：V3 长任务在识别完成或失败后可旁路发送钉钉提醒，覆盖培训识别、案件台账识别、合规审查识别、授权请示识别、三台账合并和审计问题分析；默认关闭，未配置时不影响现有业务。' },
      { type: 'feat', text: '通知通道升级：支持钉钉群机器人 Webhook、群内 @ 指定人、企业内部应用工作通知给个人；消息统一包含任务类型、发起人、状态、阶段、摘要、时间和 V3 链接，不发送正文、PDF 原文或文件内容。' },
      { type: 'feat', text: '钉钉企业应用能力接入：支持 AppKey/AppSecret 获取 access_token、发送个人工作通知、同步钉钉通讯录人员信息；同步默认只绑定已有 V3 用户，不自动创建账号。' },
      { type: 'feat', text: '钉钉工作台免登：在钉钉容器内打开 V3 时，前端通过 JSAPI 获取 authCode，后端换取 userid/unionid/name 并复用现有 sid Cookie 登录；匹配不到 V3 用户时回落短码登录并提示联系管理员。' },
      { type: 'feat', text: '运维与排障增强：新增通知开关、通知日志、同步日志和管理员测试接口，可单独测试群通知、企业应用凭证、个人工作通知、通讯录同步与免登配置。' },
    ],
  },
  {
    version: 'v3.5.3',
    date: '2026-05-20',
    changes: [
      { type: 'feat', text: '内网 HTTPS 部署:服务器侧用 Caddy 监听 8443 反代到 uvicorn:8001,证书由 mkcert 本地 CA 签发(SAN 覆盖 IP / localhost / 主机名,10 年有效),客户端机器装一次 mkcert 根 CA 后所有内网 V3 访问无警告。访问地址从 http://192.168.9.226:8001 升级为 https://192.168.9.226:8443。' },
      { type: 'fix', text: '解锁 Web Notification API:Chromium 规定 Notification / Clipboard 等"安全上下文专属 API"在内网 HTTP 地址下被整个禁用(站点设置里通知一栏灰色不可改),用户点 🔔 测试系统通知无任何反应。HTTPS 改造完成后 Notification.permission 可以正常 default → granted,Windows 系统通知正常弹出。' },
      { type: 'feat', text: '配套交付:Caddyfile(相对路径,跨机通用)+ caddy-start.ps1(UTF-8 BOM + 唯一日志名 + Already-running 检测)+ start-https.bat / stop-https.bat 双击启停 + docs/DEPLOY-HTTPS.md 完整运维指南(架构图、服务器搭建、客户端配置、故障排查、与 V2 共存方案)。.gitignore 加 logs/ 排除运行日志(*.pem / *.key 之前已排除)。' },
    ],
  },
  {
    version: 'v3.5.2',
    date: '2026-05-20',
    changes: [
      { type: 'feat', text: 'AI 完成提醒升级:Windows 系统通知改为"停在通知中心不自动消失"(requireInteraction=true),AI 长任务跑完即使你切到别的标签或窗口,回来在 Windows 通知中心还能看到。保留无声(silent=true)不打扰办公环境。' },
      { type: 'feat', text: '用户菜单新增「🔔 测试系统通知」入口(所有用户可见):一键验证 Windows 通知功能是否工作 + 自动处理浏览器三种权限状态(未询问→弹窗申请、已禁用→提示去地址栏锁形图标设置、已授权→立即发测试通知)。' },
    ],
  },
  {
    version: 'v3.5.1',
    date: '2026-05-19',
    changes: [
      { type: 'fix', text: '合规审查台账提取丢字段修复：之前同一份 PDF 在 V3 提取出来只有会签单位行，丢掉了首席合规官 / 合规管理牵头部门 / 承办单位三行核心审批角色。根因是 P1-2 反馈学习的 few-shot 自动注入在合规这种 multi-step 流程（抽取 → 复核 → 修正 → 归一化）里反向引导 LLM，让它按"用户最终采纳的扁平 review_rows"格式输出而丢掉中间结构。现已在 compliance_extract / compliance_review 两个场景显式关闭 few-shot 注入；其他单步抽取场景（案件 / 培训 / 授权）继续受益于反馈学习不变。' },
    ],
  },
  {
    version: 'v3.5.0',
    date: '2026-05-19',
    changes: [
      { type: 'feat', text: '生产部署管线：服务器侧 deploy-watch.ps1 每 5 分钟检查 GitHub，发现新 commit 自动 git pull → npm run build → 优雅重启 uvicorn → /api/health 验证。失败时日志写完整错误 + stack trace，不再静默吞错。配套 tools/start_production.ps1 / tools/backup_pg.ps1 / tools/archive_llm_traces.py 和 docs/DEPLOY-SERVER.md 首次部署手册。' },
      { type: 'feat', text: '服务器手动启停：项目根目录新增 start.bat / stop.bat 双击即用 — start.bat 后台启动 production uvicorn + 健康检查 + 日志重定向到 logs/uvicorn-时间戳.log；stop.bat 按端口 8001 精确停止，不影响 V2 在 8000 上的服务。' },
      { type: 'fix', text: '部署稳定性强化（共 7 处底层修复）：Win PowerShell 5.1 兼容（.ps1 加 UTF-8 BOM 避免中文注释被 GBK 误解码 / 外部命令 stderr 重定向避开 NativeCommandError 包装 / cmd 子进程加 chcp 65001 让 vite 输出保留 ✓ │ 字符）；schedtask jkszb 用户上下文里 git fetch 走 cmd /c 包装绕过 batch logon 凭据问题；Start-Process 启动 uvicorn 失败时显式捕获 + 日志带 stack trace；唯一日志文件名防同日两次部署的文件锁冲突；git fetch 加 3 次重试 5 秒间隔扛 GitHub 偶发 5xx。' },
    ],
  },
  {
    version: 'v3.4.1',
    date: '2026-05-19',
    changes: [
      { type: 'feat', text: '测试套大幅扩容：后端 245 → 264 个测试（新增 22 个）覆盖 API 端到端集成（FastAPI TestClient 跑全链路）+ LLM trace 访问控制安全（管理员读 / 用户只能改自己的 feedback）；前端引入 Vitest + @testing-library/react 测试栈，首批 17 个测试覆盖 api.ts 的 submitLlmFeedback 容错行为和 NotificationProvider 渲染契约；tools/smoke_test_pg.py 提供针对真实 PostgreSQL 的端到端烟雾测试（6 步全过即证明审计链路在生产 DB 上工作）。' },
      { type: 'fix', text: '通知系统加固：Notification API 检测从 `\'Notification\' in window` 改为 `window.Notification != null` —— 防止某些浏览器扩展 / polyfill 把 Notification 设为 undefined 后访问 .permission 触发崩溃。三处检查（初始权限 / 显示通知 / 申请权限）统一收口，正常浏览器行为不变。' },
    ],
  },
  {
    version: 'v3.4.0',
    date: '2026-05-18',
    changes: [
      { type: 'feat', text: 'AI 任务完成通知系统：5 大流程（案件台账 / 合规审查 / 授权请示 / 培训统计 / 三台账合并 / 审计分析）任务完成或失败时，右上角自动弹出气泡 + 浏览器标签页标题闪烁 + 系统通知（需用户授权后即使浏览器在后台也能弹）' },
      { type: 'feat', text: '审计分析饼图复制兜底：剪贴板写入支持超时熔断；剪贴板不可用或写入失败时自动改为下载 PNG 文件，按钮提示当前状态（复制中 / 已下载PNG / 复制失败）' },
    ],
  },
  {
    version: 'v3.3.0',
    date: '2026-05-18',
    changes: [
      { type: 'feat', text: '按场景智能选模型：意图分类 / 合规审查 / 案件提取 / 文档起草等 19 个 LLM 场景自动匹配不同模型——简单任务（意图分类、文档分类）走更便宜的 DeepSeek-V3，复杂任务（案件字段抽取、合规审查）走更准的 Qwen 72B，长期 LLM 成本下降 30-50%' },
      { type: 'feat', text: 'AI 质量仪表盘明细钻取：管理员菜单 → 📊 AI 质量仪表盘 → 点击任意场景行可查看最近 20 次 LLM 调用列表 → 再点击单条调用查看完整输入、AI 输出、用户最终采纳的版本（绿色高亮）' },
      { type: 'feat', text: '新增运维脚本：tools/start_production.ps1（一键启动后端 + 前端）、tools/backup_pg.ps1（PG 数据库每日备份）、tools/archive_llm_traces.py（90 天前 LLM 追溯自动归档），可挂 Windows 任务计划程序无人值守' },
      { type: 'perf', text: '大文件拆分：案件台账模块 ledger_helpers.py（960 行）抽出归档子模块；合规审查模块 compliance_ledger.py（815 行）抽出持久化子模块；审计前端 AuditFlow.tsx（621 行）抽出 TagGroup + PieSection 子组件——单文件维护成本显著降低' },
      { type: 'fix', text: '聊天意图分类契约测试：补 10 个回归测试锁定意图集 / 反馈字段 / 路由选择行为，以后改提示词不会偷偷劣化分类准确率' },
      { type: 'fix', text: '杂草清理：移除未使用的 streamlit 依赖；.env.example 补齐 8 个之前缺失的字段；日志统一格式 + 第三方库降噪' },
    ],
  },
  {
    version: 'v3.2.0',
    date: '2026-05-17',
    changes: [
      { type: 'feat', text: '用户反馈学习闭环：5 大流程（案件台账 / 合规审查 / 授权请示 / 培训统计 / 审计分析）的"AI 提取 → 用户编辑 → 确认入库"全链路反馈数据自动回流到审计库——下一次同类任务自动注入历史采纳示例作为系统提示，AI 输出会逐步贴近用户的口味' },
      { type: 'feat', text: '管理员 AI 质量仪表盘：右上角用户菜单 → 📊 AI 质量仪表盘——按场景统计总调用次数、反馈率、接受率、修改率、错误数、平均 tokens、平均延迟；接受率 ≥70% 绿色 / <50% 红色，高修改率场景标黄提醒' },
      { type: 'feat', text: '"取消"按钮也算反馈：用户对 AI 提取结果点取消时也会记录"未接受"，避免被学习引擎当成成功示例污染未来调用' },
      { type: 'feat', text: '前端反馈失败开放：feedback 上报用 Promise.allSettled，审计库挂掉也不影响业务流程' },
    ],
  },
  {
    version: 'v3.1.0',
    date: '2026-05-15',
    changes: [
      { type: 'feat', text: 'Skill 插件架构：聊天意图分发由 if/elif 列表改为自动发现——新增技能只需在 backend/skills/implementations/ 放一个单文件 Skill 类，分类提示词、反馈追溯、视觉跳过等全部自动接管' },
      { type: 'feat', text: 'LLM 调用全链路追溯：20 个业务场景（案件提取 / 合规审查 / 授权起草 / 培训分类 / 审计分类 / 意图分类 / 通用对话 / 图像 OCR）每次 LLM 调用自动落审计库，记录场景、模型、提示词版本、输入、输出、token 用量、耗时、错误' },
      { type: 'feat', text: '审计库独立到 PostgreSQL：llm_traces 表迁移到 192.168.9.226 上的 PG 实例，与主 SQLite 业务库解耦——审计库挂掉不影响业务，业务库挂掉也不影响审计' },
      { type: 'feat', text: '失败开放兜底：审计库连不上时自动降级为 NoopTracer，业务调用照常工作，仅追溯暂时失效' },
    ],
  },
  {
    version: 'v3.0.0',
    date: '2026-05-15',
    changes: [
      { type: 'feat', text: 'V3 主版本启动：从 ReactV2 拷贝代码到独立仓库（github.com/qubo851006-ctrl/reactV3），全新 Git 历史，业务数据隔离重建' },
      { type: 'feat', text: '所有 V2 既有功能保持工作不变（培训统计 / 案件台账 / 授权请示 / 三台账合并 / 审计分析 / 合规审查 / 企业查询 / 用户管理 / 多会话）' },
    ],
  },
  {
    version: 'v2.26',
    date: '2026-05-15',
    changes: [
      { type: 'fix', text: '合规审查台账会签单位漏项修复：审批流程中的会签单位意见不再被静默丢弃，所有配置表中的部门负责人意见均能正确提取到台账' },
      { type: 'fix', text: '合规牵头部门匹配收紧：审计部/法务合规部只匹配配置表中的负责人（李莹），同部门其他人员不再误入合规牵头行' },
      { type: 'fix', text: '长文本同意意见保留：审批意见虽归类为”同意”但包含实质性内容（超过20字）时，保留原文而非替换为”/”' },
      { type: 'fix', text: '会签补充搜索范围扩展：姓名与部门名称的文本邻近搜索从120字符扩大到300字符，适配长意见场景' },
    ],
  },
  {
    version: 'v2.25',
    date: '2026-05-14',
    changes: [
      { type: 'fix', text: '合规审查台账审批意见识别优化：按签署人独立提取审批意见，首席合规官只取胡鹏斌本人意见，避免混入相邻领导意见' },
      { type: 'fix', text: '合规审查意见分类优化：”拟同意，建议提交/提请会议审议”按同意处理，不再误判为建议补充完善' },
    ],
  },
  {
    version: 'v2.24',
    date: '2026-05-13',
    changes: [
      { type: 'refactor', text: '功能入口改为技能式注册表管理：左侧快捷入口、欢迎页功能卡片、触发话术和下载入口统一从前端 skills/registry.ts 读取，减少新增功能时多处重复配置' },
      { type: 'refactor', text: '聊天意图和工作流引导改为后端技能注册表管理：下载、培训、案件、授权、合规等固定意图回复，以及审计/三台账合并等可引导阶段统一从 backend/skills/registry.py 读取' },
    ],
  },
  {
    version: 'v2.23',
    date: '2026-05-13',
    changes: [
      { type: 'fix', text: '培训统计及归档增加重复事项更新：同一培训日期和培训主题再次确认写入时，更新原有行的地点、部门、人数、课时、类别和归档路径，不再新增重复记录' },
      { type: 'fix', text: '合规审查工作台账增加重复事项更新：同一重大事项标题再次确认写入时，更新原有事项内容并保留原序号，不再新增重复事项' },
    ],
  },
  {
    version: 'v2.22',
    date: '2026-05-13',
    changes: [
      { type: 'perf', text: '任务处理链路增加统一性能耗时日志：案件台账、培训统计、授权请示、合规审查、审计分析会记录关键步骤耗时，便于区分模型、OCR、PDF 解析和写文件瓶颈' },
      { type: 'perf', text: '案件台账提取提速：多个上传文书并发解析，扫描 PDF 复用并发 OCR 通道，减少多文件、多页文书逐个等待的总耗时' },
      { type: 'perf', text: '授权请示生成提速：授权请示正文与授权书正文并行生成，字段提取后不再串行等待两段文档输出' },
      { type: 'fix', text: 'OCR 稳定性增强：中航信 OCR 增加超时收敛、失败计数和临时熔断，服务异常时更快降级到视觉模型，避免每页重复长时间等待' },
    ],
  },
  {
    version: 'v2.21',
    date: '2026-05-12',
    changes: [
      { type: 'fix', text: '安全与隔离增强：三台账合并结果改为按当前用户和本次结果编号隔离保存，下载时优先下载本次合并结果，避免多人使用时互相覆盖' },
      { type: 'fix', text: '预览流程副作用收敛：案件台账、培训统计先暂存上传文件，用户确认写入后才正式归档；授权请示生成后由用户单独点击记录授权台账' },
      { type: 'fix', text: '关键落盘失败显式报错：会话历史、授权台账、合规审查台账写入失败时不再静默吞掉异常，合规台账 JSON 与 Excel 写入失败会回滚旧文件' },
      { type: 'fix', text: '登录与前端稳定性修复：短码连续输错增加限速保护，生产环境可通过 SESSION_COOKIE_SECURE 启用 Secure Cookie，并修复 App 会话消息依赖导致的 lint 警告' },
    ],
  },
  {
    version: 'v2.20',
    date: '2026-05-12',
    changes: [
      { type: 'fix', text: '案件台账人工口径增强：诉讼主体要求列全原告、被告、第三人等全部主体，禁止用"等"省略，减少主体漏提' },
      { type: 'fix', text: '处理结果改为企业法务管理摘要口径：自动补齐法院、日期、案号、文书性质、裁判主文、后续程序和公司经济影响，更接近人工台账写法' },
      { type: 'fix', text: '基本情况字段回归诉请口径，重点保留请求事项、金额、期间和责任承担，避免混入过长裁判理由；补充对应回归测试' },
    ],
  },
  {
    version: 'v2.19',
    date: '2026-05-12',
    changes: [
      { type: 'fix', text: '案件台账二审文书识别修复：当 PDF 自带文字层被解析成重复数字、符号等低质量内容时，自动转入 OCR，不再把乱码当作有效正文，避免二审判决书被误判为新案件' },
      { type: 'fix', text: '案件匹配增强：放宽案号识别规则，支持 OCR 结果中带空格的案号格式，并通过二审文书正文中的原审案号匹配已有案件，正确追加二审审级结果' },
      { type: 'fix', text: 'OCR 返回解析兼容增强：兼容中航信 OCR 的 payload.markdown、payload.text、payload.result.markdown 和 document markdown 等多种返回结构，并复用 AI 平台 Host 头配置' },
    ],
  },
  {
    version: 'v2.18',
    date: '2026-05-12',
    changes: [
      { type: 'perf', text: '扫描件 OCR 引擎升级：案件台账、合规审查、授权委托三个模块的扫描版 PDF 识别，由视觉大模型切换为中航信专用 OCR 服务，速度更快、识别更稳定、不消耗视觉模型 Token；服务不可用时自动降级回视觉模型，不影响正常使用' },
    ],
  },
  {
    version: 'v2.17',
    date: '2026-05-11',
    changes: [
      { type: 'feat', text: '台账类功能补充右上角常驻下载入口：培训统计、案件台账生成、三台账合并、合规审查台账均可在功能卡片内直接点击"下载已有台账"，无需重新上传或走完整生成流程即可导出已有台账' },
      { type: 'fix', text: '补齐合规审查工作台账下载链路：聊天中说"下载合规审查台账"可触发下载，功能页上传、预览、完成状态均提供下载入口' },
    ],
  },
  {
    version: 'v2.16',
    date: '2026-05-11',
    changes: [
      { type: 'fix', text: '审计报告图表复制优化：移除「下载 PNG」按钮，仅保留「复制图片」；复制时底色自动设为白色，便于粘贴到 Word/PPT；复制按钮不出现在截图内容中' },
      { type: 'fix', text: '移除法研知识库 MCP 调用功能：删除相关后端客户端、调试脚本、配置项及前端开关，精简功能入口' },
    ],
  },
  {
    version: 'v2.15',
    date: '2026-05-11',
    changes: [
      { type: 'fix', text: '审计问题分析双模型交叉校验固定为 Qwen2.5 72B 初步分类、DeepSeek V3 二次复核，避免该流程受全局默认模型影响而误用 GLM-5' },
      { type: 'fix', text: '保留 GLM-5 作为全局可选文字模型，不再从模型路由和前端模型选项中移除 glm-5-outside' },
    ],
  },
  {
    version: 'v2.14',
    date: '2026-05-11',
    changes: [
      { type: 'feat', text: '新增合规审查工作台账生成：上传 OA 流程表单及审批记录 PDF，系统提取重大事项、董事会/总办会程序、各单位审查意见、负责人签署时间和背景材料，预览确认后写入长期累计台账' },
      { type: 'feat', text: '合规审查台账支持多会签单位多行展开，审查单位列显示部门名称；管理员可在功能内维护部门负责人配置，默认内置财务部、审计部/法务合规部、人力资源部等负责人名单' },
      { type: 'fix', text: '补充合规审查台账单元与回归测试：覆盖意见归一化、多会签展开、Excel 合并单元格、负责人配置持久化和累计台账自然序号追加；后端全量 73 条测试通过' },
    ],
  },
  {
    version: 'v2.13',
    date: '2026-05-11',
    changes: [
      { type: 'feat', text: '审计问题分析新增双模型交叉校验：模型A完成初步分类后，模型B逐条审查并提出修正建议；分歧行以橙色高亮，展示A/B两种分类选项，用户手动确认后生成报告，提升分类可信度' },
      { type: 'feat', text: '审计报告图表新增下载/复制功能：每张饼图右上角提供「下载 PNG」和「复制图片」按钮，以2倍分辨率截图，可直接粘贴到 Word/PPT' },
    ],
  },
  {
    version: 'v2.12',
    date: '2026-05-11',
    changes: [
      { type: 'feat', text: '培训统计新增培训时长（课时）：AI 自动从培训通知 PDF 中提取开始时间和结束时间，按"总分钟数 ÷ 40 = 课时"计算；多天培训支持天数×单日时长；课时精度保留 1 位小数' },
      { type: 'feat', text: '培训确认页新增「培训开始时间」「培训结束时间」「培训时长（课时）」三个可编辑字段，识别不准时可手动修正后再写入' },
      { type: 'feat', text: '培训统计表 Excel 新增「培训时长（课时）」列（位于参与人数之后），已有台账文件自动迁移表头，无需手动处理旧数据' },
    ],
  },
  {
    version: 'v2.11',
    date: '2026-05-08',
    changes: [
      { type: 'feat', text: '引入 Noto Sans SC 字体：替换系统默认中文字体，中文显示更精致统一' },
      { type: 'feat', text: '空会话欢迎页：无对话时显示 6 宫格功能入口卡片，点击直接触发对应技能，告别空白页面' },
      { type: 'feat', text: '侧边栏技能图标升级：每个技能添加专属彩色背景圆角块（培训蓝、台账紫、授权绿、合并琥珀、审计红），一眼可辨' },
      { type: 'feat', text: '输入框视觉优化：input 与发送按钮合并为统一外壳容器，聚焦时亮起 indigo 双圈发光效果' },
      { type: 'feat', text: '整体配色调整：主背景改为更深的深蓝色（#0a0f1e），滚动条换用 indigo 色调，视觉层次更清晰' },
    ],
  },
  {
    version: 'v2.10',
    date: '2026-05-08',
    changes: [
      { type: 'fix', text: '修复所有 async def 端点中的事件循环阻塞问题（根本原因）：培训提取、案件台账提取、授权请示生成、审计分析均调用了同步 LLM/PDF/OCR 函数，直接运行于事件循环，在 Session A 处理期间（10~60 秒）完全阻塞了 Session B 的所有请求；现全部通过 asyncio.to_thread 卸载到线程池，事件循环始终保持畅通' },
      { type: 'fix', text: '模型路由配置读取改为内存缓存（_get_cached_routes）：消除每次 chat 请求中 resolve_intent_model 等函数触发的 3 次同步磁盘读取，彻底杜绝 async 端点内的文件 I/O 阻塞' },
      { type: 'fix', text: '聊天流式回复中每个 token 后增加 await asyncio.sleep(0)：主动让出事件循环，防止高频 token 流在 Starlette 缓冲未满时连续占用循环导致其他协程饿死' },
      { type: 'fix', text: 'SQLite 启用 WAL 模式（journal_mode=WAL）并设置 busy_timeout=5000ms：允许多连接并发读写 auth.db，彻底消除 get_current_user 并发 db.commit() 时的 SQLITE_BUSY 错误' },
      { type: 'fix', text: '聊天 StreamingResponse 增加 Cache-Control: no-cache、X-Accel-Buffering: no 响应头，防止代理层缓冲 SSE 数据' },
    ],
  },
  {
    version: 'v2.9',
    date: '2026-05-08',
    changes: [
      { type: 'fix', text: '聊天端点改为全异步（async def + AsyncOpenAI）：LLM 调用（意图分类、流式回答）均通过 await 非阻塞执行，事件循环在每个 token 之间都可响应其他会话的请求（新建会话、切换会话、发消息），彻底消除多会话并行时的阻塞和排队问题' },
    ],
  },
  {
    version: 'v2.8',
    date: '2026-05-08',
    changes: [
      { type: 'feat', text: '消息状态改为按会话独立存储：Session A 正在流式回答时切换到 Session B，A 的回答继续在后台写入 A 自己的消息队列，切回后内容完整呈现；Flow（培训统计/案件台账等）在后台完成时，完成消息也正确归入触发该 Flow 的会话，而非当前活跃会话，实现真正的多会话并行互不干扰' },
    ],
  },
  {
    version: 'v2.7',
    date: '2026-05-08',
    changes: [
      { type: 'feat', text: '多会话并行处理：在一个会话执行培训统计、案件台账等任务时，可自由切换到其他会话处理不同事务，切回后原任务状态完整保留（含上传文件、识别结果、待确认数据）' },
    ],
  },
  {
    version: 'v2.6',
    date: '2026-05-08',
    changes: [
      { type: 'feat', text: '图像模型新增 Qwen3 VL 8B（本地）选项，支持通过本地 Ollama 服务进行图像分析，在 .env 中配置 OLLAMA_BASE_URL 后即可启用' },
      { type: 'feat', text: '新增后端单元测试：Ollama 客户端路由逻辑、模型标签、签到表解析，共 25 个测试用例全部覆盖' },
    ],
  },
  {
    version: 'v2.5',
    date: '2026-04-30',
    changes: [
      { type: 'feat', text: '新增右上角文字模型与图像模型手工切换：普通对话可选择 Qwen2.5 72B、DeepSeek V3、GLM-5，图像与扫描件识别默认使用 Qwen2.5 VL 72B' },
      { type: 'feat', text: '新增运行时模型路由：模型列表、默认文字模型、默认意图识别模型、默认图像模型统一读取 data/model_routes.json，后续调整模型配置无需重启后端，刷新前端即可生效' },
      { type: 'feat', text: '培训签到图片识别、案件台账扫描版 PDF OCR、授权呈批件扫描版 PDF OCR 已接入图像模型选择' },
      { type: 'fix', text: '当用户询问“当前模型/你是什么模型”时，后端直接返回当前文字模型和图像模型，避免大模型自报身份不准确' },
      { type: 'fix', text: '默认文字模型与意图识别模型固定为 qwen2.5-72b，避免服务器旧 .env 中的 MODEL_CHAT 残留配置影响首次运行默认值' },
    ],
  },
  {
    version: 'v2.4',
    date: '2026-04-29',
    changes: [
      { type: 'fix', text: '补强所有上传入口安全校验：培训、授权请示、审计分析、台账合并、案件台账均增加文件名净化、扩展名白名单、大小限制、MIME 与文件头校验' },
      { type: 'fix', text: '修复案件文书归档路径风险：上传文件名和案件归档目录均限制在 data 目录内，防止路径穿越和非法文件名写入' },
      { type: 'fix', text: '案件台账写入改为事务式流程：cases.json 与 Excel 写入使用文件锁和原子替换，失败时回滚旧文件，避免 JSON、Excel 状态不一致' },
      { type: 'fix', text: 'LLM 与外部知识库 HTTP 客户端默认开启 TLS 证书校验，可通过 AI_HTTP_VERIFY_SSL 环境变量显式控制' },
      { type: 'fix', text: '会话 session_id 增加白名单格式和路径边界校验，会话历史与元数据改为文件锁 + 原子写入' },
      { type: 'refactor', text: '前端移除显式 any 类型，统一错误消息提取逻辑，提升 TypeScript 质量门禁稳定性' },
      { type: 'feat', text: '补充 Windows 服务器自动部署方案：GitHub master 有新提交后，服务器任务计划程序可自动更新、构建前端并重启后端服务' },
    ],
  },
  {
    version: 'v2.3',
    date: '2026-04-28',
    changes: [
      { type: 'feat', text: '新增用户登录与身份认证：基于 SQLite + HttpOnly Cookie 的会话管理，30 天免登录，支持密码短码登录' },
      { type: 'feat', text: '新增角色权限控制：管理员可管理用户、重置密码；普通用户仅访问自己的数据' },
      { type: 'feat', text: '新增操作审计日志：所有写入操作（台账、培训、授权请示）均记录操作人、时间和内容' },
      { type: 'feat', text: '新增多会话历史侧边栏：对话历史按会话隔离，可新建对话、切换历史会话、删除会话，体验与 ChatGPT 一致' },
      { type: 'feat', text: '每位用户拥有独立的对话历史，用户之间互不可见' },
    ],
  },
  {
    version: 'v2.2',
    date: '2026-04-28',
    changes: [
      { type: 'feat', text: '前端 SSE 流式输出：普通对话首字秒出、逐字显示，彻底告别等待全文生成后才渲染的体验' },
      { type: 'refactor', text: '意图分类与通用回复合并为单次 LLM 调用：原需 2 次串行调用，现 1 次分类（max_tokens=80）即可同时识别意图、提取公司名、判断 next_stage' },
      { type: 'refactor', text: '企业查询公司名提取内嵌到分类步骤：省去原本的第 2 次独立 LLM 调用，查询响应时间进一步缩短' },
    ],
  },
  {
    version: 'v2.1',
    date: '2026-04-28',
    changes: [
      { type: 'feat', text: '新增企业信息查询：在聊天框直接输入公司名称即可查询工商基本信息和司法风险，数据来源于 mcpmarket.cn 企业信息 MCP 服务' },
      { type: 'fix', text: '修复 Markdown 表格渲染：安装 remark-gfm 插件，消息中的表格语法正确显示为带边框的深色主题表格；同时修复 prose 类样式缺失问题' },
    ],
  },
  {
    version: 'v2.0',
    date: '2026-04-25',
    changes: [
      { type: 'feat', text: '通用对话引入轻量 ReAct：助手现在了解系统全部功能，能根据上下文主动引导用户进入对应工作流，无需每次手动点击卡片' },
      { type: 'refactor', text: '意图识别由 5 次独立 LLM 调用优化为单次分类调用，聊天响应速度提升约 5 倍，新增意图只需在配置文件加一行描述' },
      { type: 'refactor', text: '新增工具注册表（tools/registry.py），统一管理 15 个 AI 工具函数及描述，为后续接入 ReAct 预留接口' },
      { type: 'refactor', text: '前端功能模块改为配置表驱动（FLOW_COMPONENTS / DOWNLOAD_ACTIONS / SKILL_TRIGGERS），新增功能仅需在表中加一行，不改主逻辑' },
    ],
  },
  {
    version: 'v1.5',
    date: '2026-04-24',
    changes: [
      { type: 'feat', text: '授权请示起草：同步生成授权书（法定代表人授权书格式）' },
      { type: 'feat', text: '授权请示起草：完成后自动追加授权委托台账（Excel），支持一键下载' },
      { type: 'feat', text: '授权台账文件自动创建，无需手动配置路径，存放于项目 data/授权台账/ 目录' },
    ],
  },
  {
    version: 'v1.4',
    date: '2026-04-24',
    changes: [
      { type: 'feat', text: '新增审计问题智能分析模块：上传汇总表，AI 双维度分类（问题类别 × 业务领域），可编辑后导出' },
      { type: 'fix', text: '修复 Excel 表头识别错误导致数据提取为空的问题' },
      { type: 'fix', text: '修复授权请示下载链接消失问题并优化 Word 生成格式' },
    ],
  },
  {
    version: 'v1.3',
    date: '2026-04-23',
    changes: [
      { type: 'feat', text: '新增三台账合并功能：以合同系统台账为主键，自动合并采购 / 财务台账，支持模糊匹配合同编号' },
    ],
  },
  {
    version: 'v1.2',
    date: '2026-04-22',
    changes: [
      { type: 'feat', text: '支持生产部署：FastAPI 托管前端静态文件，单进程启动' },
      { type: 'feat', text: '聊天中直接说"下载统计表/台账"即可自动触发文件下载' },
      { type: 'feat', text: '案件台账写入前增加确认步骤，完成后提供下载入口' },
      { type: 'fix', text: '下载改为内联按钮，避免浏览器弹窗拦截' },
      { type: 'refactor', text: '所有用户生成数据统一迁移到项目 data/ 目录' },
    ],
  },
  {
    version: 'v1.1',
    date: '2026-04-22',
    changes: [
      { type: 'feat', text: '培训签到人数识别加入自我反思二次核查，提升识别准确率' },
    ],
  },
  {
    version: 'v1.0',
    date: '2026-04-22',
    changes: [
      { type: 'feat', text: '法度云图 V1 上线：React + FastAPI 全栈重构，支持培训统计、案件台账、授权请示起草' },
    ],
  },
]
