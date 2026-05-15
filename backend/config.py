import os
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv(override=True)

MODEL_CHAT   = os.getenv("MODEL_CHAT",   "qwen2.5-72b")
MODEL_INTENT = os.getenv("MODEL_INTENT", "qwen2.5-72b")
MODEL_VISION = os.getenv("MODEL_VISION", "qwen2.5-vl-72b")


def resolve_model(requested: str | None, allowed_models: list[str], default_model: str) -> str:
    normalized = (requested or "").strip()
    if normalized and normalized in allowed_models:
        return normalized
    if default_model in allowed_models:
        return default_model
    return allowed_models[0] if allowed_models else default_model


AI_CHAT_MODELS = [
    item.strip()
    for item in os.getenv("AI_CHAT_MODELS", "qwen2.5-72b,DeepSeek-V3,glm-5-outside").split(",")
    if item.strip()
]
if MODEL_CHAT and MODEL_CHAT not in AI_CHAT_MODELS:
    AI_CHAT_MODELS.insert(0, MODEL_CHAT)
AI_VISION_MODELS = [
    item.strip()
    for item in os.getenv("AI_VISION_MODELS", "qwen2.5-vl-72b").split(",")
    if item.strip()
]
if MODEL_VISION and MODEL_VISION not in AI_VISION_MODELS:
    AI_VISION_MODELS.insert(0, MODEL_VISION)

AIRCHINA_API_KEY  = os.getenv("AIRCHINA_API_KEY",  "")
AIRCHINA_BASE_URL = os.getenv("AIRCHINA_BASE_URL",  "")
AI_HTTP_HOST_HEADER = os.getenv("AI_HTTP_HOST_HEADER", "")
ZHISHU_API_KEY    = os.getenv("ZHISHU_API_KEY",     "")
ZHISHU_BASE_URL   = os.getenv("ZHISHU_BASE_URL",    "")
QCC_TOKEN         = os.getenv("QCC_TOKEN",           "")
OLLAMA_BASE_URL   = os.getenv("OLLAMA_BASE_URL",    "")
OLLAMA_API_KEY    = os.getenv("OLLAMA_API_KEY",     "ollama")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


AI_HTTP_VERIFY_SSL = _env_bool("AI_HTTP_VERIFY_SSL", True)

# Data directories — all user-generated content stored under the project's data/ folder
_BACKEND_DIR       = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT      = os.path.dirname(_BACKEND_DIR)
DATA_ROOT          = os.path.join(_PROJECT_ROOT, "data")
CHAT_HISTORY_PATH  = os.path.join(DATA_ROOT, "chat_history.json")
LEDGER_OUTPUT_DIR  = os.path.join(DATA_ROOT, "案件台账")
LEDGER_JSON_PATH   = os.path.join(DATA_ROOT, "案件台账", "cases.json")
LEDGER_EXCEL_PATH  = os.path.join(DATA_ROOT, "案件台账", "诉讼案件台账.xlsx")
LEGAL_ARCHIVE_ROOT = os.path.join(DATA_ROOT, "案件文书")
AUTH_LEDGER_DIR    = os.path.join(DATA_ROOT, "授权台账")
AUTH_LEDGER_PATH   = os.path.join(DATA_ROOT, "授权台账", "授权委托台账.xlsx")
COMPLIANCE_LEDGER_DIR = os.path.join(DATA_ROOT, "合规审查台账")
COMPLIANCE_LEDGER_JSON_PATH = os.path.join(COMPLIANCE_LEDGER_DIR, "records.json")
COMPLIANCE_LEDGER_EXCEL_PATH = os.path.join(COMPLIANCE_LEDGER_DIR, "合规审查工作台账.xlsx")
COMPLIANCE_RESPONSIBLE_PERSONS_PATH = os.path.join(COMPLIANCE_LEDGER_DIR, "responsible_persons.json")
