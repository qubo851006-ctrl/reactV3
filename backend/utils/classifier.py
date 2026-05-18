import os
import warnings
import httpx
from dotenv import load_dotenv
from openai import OpenAI
from config import AI_HTTP_VERIFY_SSL
from llm_client import build_ai_http_headers

warnings.filterwarnings("ignore")  # 屏蔽内网 SSL 警告
load_dotenv(override=True)

MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", "qwen2.5-72b")


def classify_training(notice_text: str, sign_in_topic: str) -> str:
    """
    根据培训通知内容和签到表主题，判断培训类别
    返回: 培训类别字符串
    """
    client = OpenAI(
        api_key=os.getenv("AIRCHINA_API_KEY"),
        base_url=os.getenv("AIRCHINA_BASE_URL"),
        http_client=httpx.Client(verify=AI_HTTP_VERIFY_SSL, headers=build_ai_http_headers()),
    )

    prompt = f"""你是一个培训分类专家。请根据以下信息判断这次培训属于哪个类别。

培训通知内容：
{notice_text}

签到表中的培训主题：
{sign_in_topic}

常见培训类别包括（但不限于）：合规培训、法律培训、风险培训、审计培训。
如果不属于以上类别，请根据实际内容给出最合适的类别名称。

请只输出类别名称，不要有任何解释，例如：合规培训
"""

    from llm_audit import traced_complete
    response = traced_complete(
        client,
        scene="classify_training_category",
        prompt_template_id="training.classify.v1",
        model=MODEL_CLASSIFY,
        messages=[{"role": "user", "content": prompt}],
    )

    category = response.choices[0].message.content.strip()
    # 清理可能的多余字符
    category = category.replace("：", "").replace(":", "").strip()
    return category
