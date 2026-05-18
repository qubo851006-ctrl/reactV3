"""Legal document archival — case files dropped into per-case folders.

Extracted from ledger_helpers.py to keep that module focused on
LLM extraction. Public surface (validate_legal_upload, archive_legal_docs)
stays importable from ledger_helpers via a re-export.

Path safety:
- case_name is stripped of Windows-forbidden chars and capped at 100 chars
- each filename is run through safe_upload_name (extension whitelist) and
  Windows reserved name protection (CON, PRN, …)
- final destination is `is_relative_to` checked against the archive root
  to defeat path-traversal even if the previous checks miss something
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from config import LEGAL_ARCHIVE_ROOT
from file_store import atomic_write_bytes
from upload_validation import safe_upload_name


_LEGAL_ALLOWED_EXTS = {".pdf", ".docx", ".doc"}
_WINDOWS_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$', re.IGNORECASE)
_LEGAL_UPLOAD_MAX_BYTES = int(os.getenv("LEGAL_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))


def _safe_basename(filename: str) -> str:
    name = Path(str(filename or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Invalid upload filename")
    return name


def _sanitize_upload_name(filename: str) -> str:
    return safe_upload_name(filename, _LEGAL_ALLOWED_EXTS)


def validate_legal_upload(filename: str, content_type: str | None, data: bytes) -> str:
    """Validate uploaded legal document — defer to upload_validation."""
    from upload_validation import validate_legal_upload as _validate_legal_upload
    return _validate_legal_upload(filename, content_type, data)


def archive_legal_docs(files_data: list, docs: list, case_name: str) -> str:
    """Write each uploaded file under data/案件文书/{case_name}/ with a
    `{doc_type}_{filename}` prefix. Returns the resolved case folder.

    Idempotent on case_name: re-archiving for the same case folds into the
    same directory, with `_2`, `_3` suffixes for duplicate filenames.
    """
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", case_name).strip() or "未知案件"
    safe_name = safe_name[:100]
    archive_root = Path(LEGAL_ARCHIVE_ROOT).resolve()
    target_dir = (archive_root / safe_name).resolve()
    if not target_dir.is_relative_to(archive_root):
        raise ValueError(f"archive_legal_docs: case_name 越出归档根目录: {case_name!r}")
    target_dir.mkdir(parents=True, exist_ok=True)
    base = target_dir  # 已经是 resolved 路径

    for fd, doc in zip(files_data, docs):
        name = fd.get("name", "")
        data = fd.get("bytes")
        if not name or not isinstance(data, (bytes, bytearray)):
            continue

        doc_type = doc.get("doc_type", "其他")
        safe_doc_type = re.sub(r'[\\/:*?"<>|]', "_", doc_type).strip() or "其他"
        if _WINDOWS_RESERVED.match(safe_doc_type):
            safe_doc_type = f"_{safe_doc_type}"

        # 防御 1：提取纯文件名，去掉任何路径前缀
        pure_name = _sanitize_upload_name(name)

        # 防御 2：扩展名白名单（点文件特殊处理）
        if pure_name.startswith(".") and "." not in pure_name[1:]:
            ext = ".bin"          # 点文件无真实扩展名，直接归为 bin
            stem_only = pure_name  # 保留整个点文件名作为 stem（如 ".pdf"）
        else:
            ext = Path(pure_name).suffix.lower()
            stem_only = Path(pure_name).stem
            if ext not in _LEGAL_ALLOWED_EXTS:
                ext = ".bin"

        # 防御 3：清理文件名中的非法字符 + 长度限制
        safe_stem = re.sub(r'[\\/:*?"<>|]', "_", stem_only).strip() or "文件"
        safe_stem = safe_stem[:200]
        safe_filename = safe_stem + ext

        dest_name = f"{safe_doc_type}_{safe_filename}"
        dest_path = (target_dir / dest_name).resolve()

        # 越界兜底：确认路径仍在归档根目录内
        if not dest_path.is_relative_to(base):
            logging.warning("archive_legal_docs: 路径越界已跳过 %s", dest_path)
            continue

        if dest_path.exists():
            i = 2
            while i <= 9999 and (target_dir / f"{safe_doc_type}_{safe_stem}_{i}{ext}").exists():
                i += 1
            if i > 9999:
                logging.warning("archive_legal_docs: 重名文件数超限，跳过 %s", safe_filename)
                continue
            dest_path = (target_dir / f"{safe_doc_type}_{safe_stem}_{i}{ext}").resolve()

        try:
            atomic_write_bytes(dest_path, bytes(data))
        except OSError as e:
            logging.warning("archive_legal_docs: 写入失败 %s: %s", dest_path, e)
            continue

    return str(target_dir)
