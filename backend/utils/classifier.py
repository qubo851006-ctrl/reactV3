import os
import warnings
import httpx
from dotenv import load_dotenv
from openai import OpenAI
from config import AI_HTTP_VERIFY_SSL
from llm_client import build_ai_http_headers
from utils.llm_extract import extract_short_text

warnings.filterwarnings("ignore")  # 屏蔽内网 SSL 警告
load_dotenv(override=True)

MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", "qwen2.5-72b")

# 培训类别候选清单（提示词内 + 提取白名单兜底）
TRAINING_CATEGORIES = [
    "合规培训", "法律培训", "风险培训", "审计培训",
    "技术培训", "业务培训", "党建培训", "安全培训",
    "综合培训",
]


def classify_training(notice_text: str, sign_in_topic: str) -> str:
    """
    根据培训通知内容和签到表主题，判断培训类别。
    返回 4-8 字的中文短类别名，LLM 跑偏时兜底返回"其他"。
    """
    client = OpenAI(
        api_key=os.getenv("AIRCHINA_API_KEY"),
        base_url=os.getenv("AIRCHINA_BASE_URL"),
        http_client=httpx.Client(verify=AI_HTTP_VERIFY_SSL, headers=build_ai_http_headers()),
    )

    prompt = f"""你是培训分类专家。判断这次培训属于哪个类别。

# 输入
培训通知内容：
{notice_text}

签到表中的培训主题：
{sign_in_topic}

# 候选类别（优先从中选一个）
{"、".join(TRAINING_CATEGORIES)}

# 输出格式（严格遵守）
- 只输出一个 4-8 字的中文类别名称
- 不要输出 JSON、不要输出引号、不要复述输入、不要任何前缀或解释
- 不要使用 Markdown 代码块
- 如候选清单都不匹配，按实际内容自拟一个 4-8 字的简短名称

# 输出示例
合规培训
"""

    from llm_audit import traced_complete
    response = traced_complete(
        client,
        scene="classify_training_category",
        prompt_template_id="training.classify.v2",
        model=MODEL_CLASSIFY,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=32,
    )

    raw = response.choices[0].message.content
    # 防御性提取：LLM 可能吐 JSON / Markdown / 复述输入，统一在这里清洗
    return extract_short_text(
        raw,
        max_len=12,
        json_keys=("category", "类别", "分类", "training_category"),
        fallback="其他",
    )
