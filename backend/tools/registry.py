"""
工具注册表 — 统一管理所有 AI 可调用的工具函数。

新增工具只需在此文件的 TOOLS 字典中增加一条记录，无需修改各业务路由。
每条记录包含：
  - func        实际执行的 Python 函数
  - description 给 LLM 看的工具说明（将来接入 ReAct 直接用）
  - inputs      输入参数名列表（供文档和校验使用）
  - workflow    该工具属于哪个业务流程
"""

from utils import pdf_reader, image_analyzer, classifier, archiver, excel_writer
from utils import auth_request_drafter, excel_merger, write_excel
from ledger_helpers import (
    extract_file_text,
    detect_doc_type_by_content,
    extract_case_fields,
    find_matching_case_idx,
    archive_legal_docs,
)


TOOLS: dict[str, dict] = {
    # ── 通用文档提取 ──────────────────────────────────────────
    "extract_pdf_text": {
        "func": pdf_reader.extract_pdf_text,
        "description": "从 PDF 文件路径中提取纯文字内容。",
        "inputs": ["pdf_path"],
        "workflow": "common",
    },

    # ── 培训统计流程 ──────────────────────────────────────────
    "count_attendees": {
        "func": image_analyzer.count_attendees,
        "description": "从签到表图片路径统计出席人数。内置二次验证机制，返回人数和置信度。",
        "inputs": ["image_path"],
        "workflow": "training",
    },
    "classify_training": {
        "func": classifier.classify_training,
        "description": "根据培训通知文字和培训主题，将培训归类到预定义类别。",
        "inputs": ["notice_text", "sign_in_topic"],
        "workflow": "training",
    },
    "archive_training_files": {
        "func": archiver.archive_files,
        "description": "将培训通知和签到表按部门、日期归档到指定目录。",
        "inputs": ["notice_path", "sign_path", "department", "date", "archive_root"],
        "workflow": "training",
    },
    "write_training_record": {
        "func": excel_writer.append_record,
        "description": "将培训记录追加写入培训统计表 Excel。",
        "inputs": ["topic", "location", "date", "department", "count", "category", "archive_path"],
        "workflow": "training",
    },

    # ── 案件台账流程 ──────────────────────────────────────────
    "extract_legal_doc_text": {
        "func": extract_file_text,
        "description": "从法律文书（PDF/DOCX）bytes 中提取文字，支持文字版和扫描版。",
        "inputs": ["file_bytes", "filename"],
        "workflow": "ledger",
    },
    "detect_doc_type": {
        "func": detect_doc_type_by_content,
        "description": "根据文书内容判断文书类型（起诉状、判决书、裁定书、强制执行申请书等）。",
        "inputs": ["text"],
        "workflow": "ledger",
    },
    "extract_case_fields": {
        "func": extract_case_fields,
        "description": "从多份法律文书列表中提取案件结构化字段（案号、当事人、金额、日期等）。",
        "inputs": ["docs"],
        "workflow": "ledger",
    },
    "find_matching_case": {
        "func": find_matching_case_idx,
        "description": "在现有案件台账中查找与当前文书对应的案件，返回匹配索引或 None（新案件）。",
        "inputs": ["new_case", "existing_cases"],
        "workflow": "ledger",
    },
    "archive_legal_docs": {
        "func": archive_legal_docs,
        "description": "将法律文书按案件名称归档，返回归档目录路径。",
        "inputs": ["files_data", "docs", "case_name"],
        "workflow": "ledger",
    },
    "write_ledger": {
        "func": write_excel.write_ledger,
        "description": "将案件列表写入或更新诉讼案件台账 Excel。",
        "inputs": ["cases", "output_path"],
        "workflow": "ledger",
    },

    # ── 授权请示流程 ──────────────────────────────────────────
    "extract_approval_info": {
        "func": auth_request_drafter.extract_approval_info,
        "description": "从呈批件文字中提取授权请示所需的 15 个关键字段。",
        "inputs": ["text"],
        "workflow": "auth",
    },
    "draft_auth_request": {
        "func": auth_request_drafter.draft_auth_request,
        "description": "根据提取的字段生成授权请示正文（Word 格式）。",
        "inputs": ["info"],
        "workflow": "auth",
    },
    "draft_auth_letter": {
        "func": auth_request_drafter.draft_auth_letter,
        "description": "根据提取的字段生成授权委托书正文（Word 格式）。",
        "inputs": ["info"],
        "workflow": "auth",
    },

    # ── 台账合并流程 ──────────────────────────────────────────
    "merge_ledgers": {
        "func": excel_merger.merge_ledgers,
        "description": "以合同编号为主键，将合同系统、采购系统、财务系统三份 Excel 台账合并为一张表。支持模糊匹配。",
        "inputs": ["contract_bytes", "purchase_bytes", "finance_bytes"],
        "workflow": "merge",
    },
}


def get_tool(name: str):
    """按名称取工具函数，不存在时抛出 KeyError。"""
    return TOOLS[name]["func"]


def list_tools_for_llm() -> str:
    """
    生成供 LLM 阅读的工具列表字符串。
    将来接入 ReAct 时，把此字符串放入 system prompt 即可让模型知道有哪些工具可用。
    """
    lines = []
    for name, meta in TOOLS.items():
        lines.append(f"- {name}({', '.join(meta['inputs'])}): {meta['description']}")
    return "\n".join(lines)
