import type { VersionEntry } from './branding'

export const VERSION_ENTRIES: VersionEntry[] = [
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
