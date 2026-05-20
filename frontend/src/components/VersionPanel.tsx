import { useState } from 'react'
import { APP_NAME } from '../branding'
import { VERSION_ENTRIES } from '../versionHistory'

const FEATURES = [
  {
    icon: '🧩',
    name: '技能式功能入口管理',
    steps: [
      '培训统计、案件台账、授权请示、三台账合并、审计分析、合规审查台账统一按“技能”配置管理',
      '左侧快捷入口、欢迎页功能卡片、点击后的引导话术和下载入口保持一致，减少新增功能时的漏配',
      '后端对话意图和工作流引导也集中到技能注册表，用户原有点击和聊天触发方式不变',
    ],
  },
  {
    icon: '🤖',
    name: '模型切换与运行时路由',
    steps: [
      '右上角提供“文字模型”和“图像模型”两个下拉框，可在发送对话或处理图片前手工选择模型',
      '文字模型用于普通聊天回答；意图识别默认走 qwen2.5-72b，以保证流程判断稳定和响应速度',
      '图像模型用于培训签到图片识别、案件台账扫描件 OCR、授权呈批件扫描 OCR 等视觉任务',
      '模型列表和默认模型来自 data/model_routes.json，管理员后续调整该文件后无需重启后端，刷新前端即可加载新配置',
      '在聊天中询问“当前模型是什么”时，系统会直接返回当前文字模型和图像模型，而不是让大模型自行猜测',
    ],
  },
  {
    icon: '💬',
    name: '多会话对话历史',
    steps: [
      '登录后左侧边栏上方自动显示历史对话列表，按"今天 / 昨天 / 较早"分组',
      '点击"新建对话"创建空白会话，原有对话保留在列表中',
      '点击任意历史会话可立即切换，聊天记录自动恢复，工作流状态同步重置',
      '将鼠标悬停在会话条目上，右侧出现删除图标，单击即可删除该会话',
      '每条会话标题取自该会话第一条用户消息的前 20 个字，便于快速识别',
    ],
  },
  {
    icon: '🔐',
    name: '用户登录与权限管理',
    steps: [
      '首次访问自动跳转登录页，选择姓名后输入短码（由管理员设置）完成登录',
      '登录状态保持 30 天，关闭浏览器后再次打开无需重新登录',
      '在钉钉工作台打开 V3 时，可通过企业应用免登自动进入系统；未绑定用户会回落到短码登录并提示联系管理员',
      '右上角头像菜单可查看当前身份，点击"退出登录"可手动注销',
      '管理员可点击右上角"用户管理"，对所有用户进行增删、重置短码、切换角色等操作',
      '所有台账写入、培训归档、授权请示生成操作均记录审计日志',
    ],
  },
  {
    icon: '🔔',
    name: '钉钉集成',
    steps: [
      '长任务识别完成或失败后，可通过钉钉群机器人或企业应用工作通知发送提醒',
      '企业应用工作通知会发送给绑定的钉钉用户，相比群里 @ 人更适合个人待办提醒',
      '通知内容只包含任务类型、发起人、状态、阶段、摘要、时间和 V3 链接，不发送原文或附件内容',
      '通知支持成功、失败、提醒三个级别，并可通过环境变量分别开关成功通知、失败通知、提醒通知和 @ 人',
      '管理员可测试群通知、企业应用凭证、个人工作通知，并查看最近通知日志',
      '钉钉通讯录同步默认只绑定已有 V3 用户，不自动创建账号，避免通讯录全量写入系统',
    ],
  },
  {
    icon: '📊',
    name: '培训统计及归档',
    steps: [
      '点击左侧"培训统计及归档"按钮，或直接在聊天中描述需求',
      '上传培训通知 PDF 和签到表图片（JPG/PNG）',
      '填写组织部门后点击"提取信息"，AI 自动识别培训主题、日期、人员名单',
      'AI 从培训通知 PDF 中提取开始时间和结束时间，自动计算培训时长（总分钟数 ÷ 40 = 课时，保留 1 位小数；多天培训按天数×单日时长计算）',
      '处理过程会记录 PDF 解析、签到识别、分类、时长提取、暂存归档等步骤耗时，便于定位慢点',
      '确认页可编辑开始时间、结束时间、课时数，识别有误时手动修正后再写入',
      '确认信息后写入培训统计表（含培训时长列），并将暂存文件正式归档；仅预览不写入台账也不进入正式归档目录',
      '同一培训日期和培训主题再次写入时，会更新原有记录，不会新增重复行',
      '可在聊天中说"下载培训统计表"随时导出 Excel',
      '也可在功能卡片右上角点击"下载已有台账"，无需重新上传即可导出累计台账',
    ],
  },
  {
    icon: '⚖️',
    name: '案件台账生成',
    steps: [
      '点击左侧"案件台账生成"按钮',
      '上传案件相关法律文书（PDF/DOCX/DOC，可多选）',
      '多个文书会并发解析，扫描 PDF 会走并发 OCR 通道，减少多文件、多页文书等待时间',
      'AI 自动识别文书类型（起诉状、判决书、仲裁裁决书等）并提取关键字段',
      '诉讼主体会尽量列全原告、被告、第三人等全部主体，不用“等”替代关键当事人',
      '处理结果按企业法务台账口径整理，优先保留法院、日期、案号、文书性质、裁判主文、后续程序和公司经济影响',
      '基本情况以诉讼请求为主，重点保留请求事项、金额、期间和责任承担',
      '系统判断是否为台账已有案件，确认匹配关系后写入台账；上传文书会先暂存，确认写入后才进入正式案件归档目录',
      '可在聊天中说"下载案件台账"随时导出 Excel',
      '也可在功能卡片右上角点击"下载已有台账"，无需重新上传即可导出累计案件台账',
    ],
  },
  {
    icon: '📝',
    name: '授权请示起草',
    steps: [
      '点击左侧"授权请示起草"按钮',
      '上传呈批件 PDF（支持文字版和扫描版，扫描版自动 OCR）',
      'AI 自动提取项目名称、文件编号、授权事项、授权单位、期限、份数等字段',
      '生成授权请示 Word 文档（规范散文格式）和授权书（法定代表人授权书）；两份正文并行生成以减少等待',
      '生成后可先下载核对，也可点击"记录授权台账"将本次授权记录追加到授权委托台账 Excel',
      '下载后，授权书中注册地址、法定代表人等空白处需人工填写',
    ],
  },
  {
    icon: '🔀',
    name: '三台账合并',
    steps: [
      '点击左侧"三台账合并"按钮',
      '上传合同系统台账 Excel（必填），采购/财务系统台账（可选）',
      '系统以合同编号为主键自动关联，支持大小写、全角括号等差异的模糊匹配',
      '合并完成后下载合并结果 Excel，包含匹配状态和来源标记',
      '也可在功能卡片右上角点击"下载已有台账"，直接下载当前用户最近一次合并生成的台账；本次合并按钮会优先下载本次结果',
    ],
  },
  {
    icon: '🔍',
    name: '审计问题分析',
    steps: [
      '点击左侧"审计问题分析"按钮',
      '上传审计发现问题汇总表 Excel（系统自动识别问题列）',
      '双模型交叉分析：模型A 按13大类分类体系初步分类，模型B 对结果逐条审查并标注修正建议',
      '审查页：分歧行以橙色高亮显示⚠标记，点击「用A」或「用B」快速选择，也可手动修改下拉框',
      '分析过程记录 Excel 解析、模型A分类、模型B复核和结果合并耗时，便于后续优化',
      '生成报告：两张饼图（问题类别 / 业务领域分布），每张图右上角可复制图片到剪贴板（白色底色，方便粘贴到 Word/PPT）',
      '点击"下载 Excel"导出含分类结果的格式化表格',
    ],
  },
  {
    icon: '📑',
    name: '合规审查工作台账生成',
    steps: [
      '点击左侧"合规审查台账"按钮',
      '上传 OA 流程表单及审批记录 PDF',
      '系统自动识别重大事项、董事会/总办会程序、各单位审查意见、负责人签署时间和背景材料',
      '审批意见按签署人独立识别，首席合规官只取胡鹏斌本人意见，避免相邻领导意见串行合并',
      '提取和写入过程记录 PDF/OCR、负责人配置、AI 提取、Excel 生成和文件提交耗时',
      '审查单位支持多行展开，多个会签部门会分别生成独立行',
      '确认预览后写入长期累计台账，并可下载合规审查工作台账 Excel',
      '同一重大事项标题再次写入时，会更新原有事项，不会新增重复事项',
      '上传页、预览页和完成页均提供台账下载入口，可随时导出已有合规审查台账',
      '管理员可在该功能内维护部门负责人配置',
    ],
  },
  {
    icon: '🏢',
    name: '企业信息查询',
    steps: [
      '无需点击按钮，直接在聊天框输入即可，例如："查一下XX公司的工商信息"',
      '支持模糊输入公司名称，系统自动匹配精确注册名称',
      '默认返回基本信息（注册资本、法定代表人、地址等）和司法风险（立案、执行、裁判文书数量）',
      '数据来源：mcpmarket.cn 企业信息 MCP 服务，查询结果仅供参考',
    ],
  },
  {
    icon: '🛡️',
    name: '安全校验与自动部署',
    steps: [
      '后端会统一校验上传文件的安全文件名、扩展名、文件大小、MIME 类型和文件头，异常文件会直接拒绝处理',
      '案件文书归档、会话历史、案件台账、培训台账、授权台账等关键文件写入均使用原子替换或文件锁，降低并发写入和半写入风险',
      '案件台账确认写入时，JSON 与 Excel 作为一组事务处理；任一步失败会返回错误并尽量回滚旧文件',
      '合规审查台账写入时，JSON 与 Excel 也作为一组事务处理；生成 Excel 或替换文件失败会回滚到旧文件',
      '登录短码连续输错会触发临时限速；生产环境可通过 SESSION_COOKIE_SECURE=true 启用 Secure Cookie',
      'OCR 服务异常时会缩短等待并临时熔断，自动降级到视觉模型，避免同一批扫描件反复长时间等待失败服务',
      '后端输出 perf.step / perf.total 性能日志，可用于判断慢点来自模型、OCR、PDF 解析还是文件写入',
      '服务器端可通过 Windows 任务计划程序定时检测 GitHub master 分支更新，自动拉取最新代码、构建前端并重启后端',
      '生产环境请在服务器本地保留 .env 和 data 目录，不要将业务数据或密钥提交到 GitHub',
    ],
  },
]

const TYPE_BADGE: Record<string, string> = {
  feat: 'bg-indigo-500/20 text-indigo-300',
  fix: 'bg-amber-500/20 text-amber-300',
  refactor: 'bg-slate-500/20 text-slate-300',
}
const TYPE_LABEL: Record<string, string> = {
  feat: '新增',
  fix: '修复',
  refactor: '重构',
}

interface Props {
  open: boolean
  onClose: () => void
}

export default function VersionPanel({ open, onClose }: Props) {
  const [tab, setTab] = useState<'guide' | 'history'>('guide')

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        className={`
          fixed top-0 right-0 z-50 h-full w-[420px] max-w-full
          bg-slate-900 border-l border-slate-700/60 shadow-2xl
          flex flex-col
          transition-transform duration-300 ease-in-out
          ${open ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/60">
          <div>
            <div className="text-sm font-semibold text-white">功能说明 &amp; 版本记录</div>
            <div className="text-xs text-slate-500 mt-0.5">{APP_NAME} · Created by 曲波</div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-700/60">
          {(['guide', 'history'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2.5 text-sm transition-colors ${
                tab === t
                  ? 'text-indigo-400 border-b-2 border-indigo-400'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {t === 'guide' ? '📖 功能使用说明' : '🕐 版本更新记录'}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {tab === 'guide' ? (
            <div className="space-y-6">
              {FEATURES.map(f => (
                <div key={f.name}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-base">{f.icon}</span>
                    <span className="text-sm font-medium text-white">{f.name}</span>
                  </div>
                  <ol className="space-y-1.5 pl-1">
                    {f.steps.map((step, i) => (
                      <li key={i} className="flex gap-2 text-xs text-slate-400">
                        <span className="flex-shrink-0 w-4 h-4 rounded-full bg-slate-700 text-slate-400 flex items-center justify-center text-[10px] mt-0.5">
                          {i + 1}
                        </span>
                        <span>{step}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-5">
              {VERSION_ENTRIES.map(v => (
                <div key={v.version}>
                  <div className="flex items-baseline gap-2 mb-2">
                    <span className="text-sm font-semibold text-white">{v.version}</span>
                    <span className="text-xs text-slate-500">{v.date}</span>
                  </div>
                  <ul className="space-y-1.5">
                    {v.changes.map((c, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-slate-400">
                        <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${TYPE_BADGE[c.type]}`}>
                          {TYPE_LABEL[c.type]}
                        </span>
                        <span>{c.text}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
