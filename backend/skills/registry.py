from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowSkill:
    key: str
    intent: str
    stage: str
    intent_description: str
    reply: str = ""
    workflow_hint: str = ""
    fixed_response: bool = True
    actionable: bool = True


WORKFLOW_SKILLS: tuple[WorkflowSkill, ...] = (
    WorkflowSkill(
        key="download_training",
        intent="download_training_excel",
        stage="download_training_excel",
        intent_description="用户想下载或导出培训统计表、培训台账、培训记录 Excel",
        reply="📥 正在为您打开培训统计表下载…",
        workflow_hint="",
        actionable=False,
    ),
    WorkflowSkill(
        key="download_ledger",
        intent="download_ledger_excel",
        stage="download_ledger_excel",
        intent_description="用户想下载或导出案件台账、诉讼台账 Excel",
        reply="📥 正在为您打开案件台账下载…",
        workflow_hint="",
        actionable=False,
    ),
    WorkflowSkill(
        key="download_compliance",
        intent="download_compliance_excel",
        stage="download_compliance_excel",
        intent_description="用户想下载或导出合规审查工作台账 Excel",
        reply="正在为您打开合规审查工作台账下载。",
        workflow_hint="",
        actionable=False,
    ),
    WorkflowSkill(
        key="training",
        intent="waiting_files",
        stage="waiting_files",
        intent_description="用户想统计培训签到、归档培训文件、新增培训记录（需上传文件，不是单纯下载）",
        reply=(
            "好的！请上传以下两个文件：\n\n"
            "- 📄 **培训通知**（PDF 格式）\n"
            "- ✍️ **签到表**（图片格式：JPG / PNG）"
        ),
        workflow_hint="用户有培训通知/签到表需要统计归档",
    ),
    WorkflowSkill(
        key="ledger",
        intent="waiting_ledger_files",
        stage="waiting_ledger_files",
        intent_description="用户想处理案件台账、整理法律文书、新增案件记录（需上传文书，不是单纯下载）",
        reply=(
            "好的！请上传案件的法律文书文件（支持 **PDF / DOCX / DOC**，可多选）。\n\n"
            "系统会自动识别文书类型，并判断是否为台账中的已有案件：\n"
            "- 已有案件：追加审级处理结果或更新执行信息\n"
            "- 新案件：在台账末尾新增一行"
        ),
        workflow_hint="用户有法律文书（起诉状/判决书/裁定书/强制执行申请）需要录入台账",
    ),
    WorkflowSkill(
        key="auth",
        intent="waiting_auth_file",
        stage="waiting_auth_file",
        intent_description="用户想起草授权请示、根据呈批件生成授权文件",
        reply=(
            "好的！请上传**呈批件 PDF**，系统将自动提取关键信息并生成授权请示 Word 文档。\n\n"
            "- 支持文字版 PDF（直接提取）\n"
            "- 支持扫描版 PDF（自动 OCR 识别）"
        ),
        workflow_hint="用户需要根据呈批件起草授权请示或授权书",
    ),
    WorkflowSkill(
        key="compliance",
        intent="waiting_compliance_file",
        stage="waiting_compliance_file",
        intent_description="用户想根据 OA 审批 PDF 生成合规审查工作台账",
        reply="好的！请上传 **OA 流程表单及审批记录 PDF**，系统会提取重大事项、程序、各单位审查意见、签署时间和背景材料，确认后写入长期累计合规审查工作台账。",
        workflow_hint="用户需要根据 OA 流程表单/审批记录 PDF 生成合规审查工作台账",
    ),
    WorkflowSkill(
        key="merge",
        intent="waiting_ledger_merge_files",
        stage="waiting_ledger_merge_files",
        intent_description="用户需要合并合同/采购/财务多个系统导出的台账 Excel",
        workflow_hint="用户需要合并合同/采购/财务多个系统导出的台账 Excel",
        fixed_response=False,
    ),
    WorkflowSkill(
        key="audit",
        intent="waiting_audit_file",
        stage="waiting_audit_file",
        intent_description="用户需要对审计发现问题进行 AI 分类分析",
        workflow_hint="用户需要对审计发现问题进行 AI 分类分析",
        fixed_response=False,
    ),
)


VALID_INTENTS = {skill.intent for skill in WORKFLOW_SKILLS if skill.fixed_response} | {"query_company", "debt_recovery_assessment", "other"}

INTENT_DESCRIPTIONS_WORKFLOW = "\n".join(
    f"- {skill.intent}：{skill.intent_description}"
    for skill in WORKFLOW_SKILLS
    if skill.fixed_response
)

ACTIONABLE_STAGES = {
    skill.stage
    for skill in WORKFLOW_SKILLS
    if skill.actionable
}

WORKFLOW_HINTS = "\n".join(
    f"- {skill.stage}：{skill.workflow_hint}"
    for skill in WORKFLOW_SKILLS
    if skill.workflow_hint
)

INTENT_RESPONSES = {
    skill.intent: (skill.reply, skill.stage)
    for skill in WORKFLOW_SKILLS
    if skill.fixed_response and skill.reply
}

# ── QCC API 技能（非固定回复，chat.py 直接分发）──────────────────────────────
# 以下常量集中管理 LLM 意图分类提示块，避免 chat.py 内硬编码
QCC_INTENT_DESCRIPTIONS = (
    '【企业查询】格式：{"intent": "query_company", "company": "企业名称"}\n'
    "条件：用户提及具体公司名称并想查询工商/司法等基本信息\n"
    "\n"
    '【债务清偿评估】格式：{"intent": "debt_recovery_assessment", "company": "企业名称", "claim_amount": 金额数字或0}\n'
    "条件：用户想评估某企业的偿债能力、追偿可行性、诉前保全决策、债权回收分析等"
)
