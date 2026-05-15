import os
import re
from pathlib import Path


class UploadValidationError(ValueError):
    pass


_WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)

PDF_MAX_BYTES = int(os.getenv("UPLOAD_PDF_MAX_BYTES", str(50 * 1024 * 1024)))
IMAGE_MAX_BYTES = int(os.getenv("UPLOAD_IMAGE_MAX_BYTES", str(20 * 1024 * 1024)))
EXCEL_MAX_BYTES = int(os.getenv("UPLOAD_EXCEL_MAX_BYTES", str(50 * 1024 * 1024)))
LEGAL_MAX_BYTES = int(os.getenv("LEGAL_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))

_PDF_CTYPES = {"application/pdf", "application/octet-stream", ""}
_IMAGE_CTYPES = {
    ".jpg": {"image/jpeg", "application/octet-stream", ""},
    ".jpeg": {"image/jpeg", "application/octet-stream", ""},
    ".png": {"image/png", "application/octet-stream", ""},
}
_EXCEL_CTYPES = {
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/octet-stream",
        "",
    },
    ".xls": {"application/vnd.ms-excel", "application/octet-stream", ""},
}
_LEGAL_CTYPES = {
    ".pdf": _PDF_CTYPES,
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
        "",
    },
    ".doc": {"application/msword", "application/octet-stream", ""},
}


def _normalized_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def safe_upload_name(filename: str, allowed_exts: set[str]) -> str:
    name = Path(str(filename or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise UploadValidationError("Invalid upload filename")

    path = Path(name)
    ext = path.suffix.lower()
    if ext not in allowed_exts:
        raise UploadValidationError("Unsupported file type")

    stem = re.sub(r'[\\/:*?"<>|]', "_", path.stem).strip() or "file"
    stem = re.sub(r"\s+", " ", stem)[:200]
    if _WINDOWS_RESERVED.match(stem):
        stem = f"_{stem}"
    return f"{stem}{ext}"


def _validate_common(filename: str, content_type: str | None, data: bytes, allowed_types: dict[str, set[str]], max_bytes: int) -> tuple[str, str]:
    safe_name = safe_upload_name(filename, set(allowed_types))
    ext = Path(safe_name).suffix.lower()

    if not data:
        raise UploadValidationError("Uploaded file is empty")
    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise UploadValidationError(f"Uploaded file is too large. Max size is {max_mb} MB")

    if _normalized_content_type(content_type) not in allowed_types[ext]:
        raise UploadValidationError("Uploaded file content type does not match the allowed types")

    return safe_name, ext


def validate_pdf_upload(filename: str, content_type: str | None, data: bytes, max_bytes: int = PDF_MAX_BYTES) -> str:
    safe_name, _ = _validate_common(filename, content_type, data, {".pdf": _PDF_CTYPES}, max_bytes)
    if not data.lstrip().startswith(b"%PDF-"):
        raise UploadValidationError("Uploaded PDF file has an invalid header")
    return safe_name


def validate_image_upload(filename: str, content_type: str | None, data: bytes, max_bytes: int = IMAGE_MAX_BYTES) -> str:
    safe_name, ext = _validate_common(filename, content_type, data, _IMAGE_CTYPES, max_bytes)
    if ext == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UploadValidationError("Uploaded PNG file has an invalid header")
    if ext in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8\xff"):
        raise UploadValidationError("Uploaded JPEG file has an invalid header")
    return safe_name


def validate_excel_upload(filename: str, content_type: str | None, data: bytes, max_bytes: int = EXCEL_MAX_BYTES) -> str:
    safe_name, ext = _validate_common(filename, content_type, data, _EXCEL_CTYPES, max_bytes)
    if ext == ".xlsx" and not data.startswith(b"PK"):
        raise UploadValidationError("Uploaded XLSX file has an invalid header")
    if ext == ".xls" and not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise UploadValidationError("Uploaded XLS file has an invalid header")
    return safe_name


def validate_legal_upload(filename: str, content_type: str | None, data: bytes, max_bytes: int = LEGAL_MAX_BYTES) -> str:
    safe_name, ext = _validate_common(filename, content_type, data, _LEGAL_CTYPES, max_bytes)
    if ext == ".pdf" and not data.lstrip().startswith(b"%PDF-"):
        raise UploadValidationError("Uploaded PDF file has an invalid header")
    if ext == ".docx" and not data.startswith(b"PK"):
        raise UploadValidationError("Uploaded DOCX file has an invalid header")
    if ext == ".doc" and not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise UploadValidationError("Uploaded DOC file has an invalid header")
    return safe_name
