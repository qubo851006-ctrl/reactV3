import base64
import os
import warnings
import httpx
from dotenv import load_dotenv
from openai import OpenAI
from config import AI_HTTP_VERIFY_SSL, OLLAMA_BASE_URL, OLLAMA_API_KEY
from llm_client import build_ai_http_headers
from model_routes import resolve_vision_model

_OLLAMA_MODELS = {"qwen3-vl:8b"}

warnings.filterwarnings("ignore")  # 屏蔽内网 SSL 警告
load_dotenv(override=True)


def encode_image(image_path: str) -> str:
    """将图片转为 base64 字符串"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_client() -> OpenAI:
    return OpenAI(
        api_key=os.getenv("AIRCHINA_API_KEY"),
        base_url=os.getenv("AIRCHINA_BASE_URL"),
        http_client=httpx.Client(verify=AI_HTTP_VERIFY_SSL, headers=build_ai_http_headers()),
    )


def get_ollama_client() -> OpenAI:
    return OpenAI(
        api_key=OLLAMA_API_KEY,
        base_url=OLLAMA_BASE_URL,
        http_client=httpx.Client(verify=False),
    )


def get_vision_client(model: str) -> OpenAI:
    if model in _OLLAMA_MODELS and OLLAMA_BASE_URL:
        return get_ollama_client()
    return get_client()


def _call_vision(client: OpenAI, image_url: str, prompt: str, model: str) -> str:
    """向视觉模型发送一次请求，返回原始文本"""
    from llm_audit import traced_complete
    response = traced_complete(
        client,
        scene="vision_analyze_image",
        prompt_template_id="vision.analyze.v1",
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return response.choices[0].message.content.strip()


def count_attendees(image_path: str, model: str | None = None) -> dict:
    """
    分析签到表图片，统计参与人数及提取抬头信息。

    返回: {count, topic, location, date, confidence, reflection_note}
    """
    selected_model = resolve_vision_model(model)
    client = get_vision_client(selected_model)

    image_data = encode_image(image_path)
    ext = image_path.split(".")[-1].lower()
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
    mime_type = mime_map.get(ext, "image/jpeg")
    image_url = f"data:{mime_type};base64,{image_data}"

    prompt = """这是一张培训签到表图片。

第一步：提取抬头信息
- 培训主题、培训地点、培训时间

第二步：逐行列出所有有内容的姓名格
签到表分左右两栏，请从第1行开始，逐行检查左栏姓名格和右栏姓名格：
- 有手写内容的格子：写"有"
- 空白的格子：写"空"
格式示例：
行1：左=有，右=有
行2：左=有，右=空
行3：左=空，右=空（遇到连续空行可停止）

第三步：统计
把所有标记为"有"的格子数量加总，就是总人数。
注意：忽略表格底部任何手写的合计/估计数字。

请按以下格式输出，不要有多余内容：
主题：xxx
地点：xxx
时间：xxx
明细：（粘贴第二步的逐行结果）
人数：数字
"""

    result_text = _call_vision(client, image_url, prompt, selected_model)
    result = parse_sign_in_result(result_text)

    return {
        "topic": result["topic"],
        "location": result["location"],
        "date": result["date"],
        "count": result["count"],
        "confidence": "high",
        "reflection_note": "",
    }


def parse_sign_in_result(text: str) -> dict:
    """解析 AI 返回的签到表信息"""
    result = {"topic": "", "location": "", "date": "", "count": 0}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("主题："):
            result["topic"] = line.replace("主题：", "").strip()
        elif line.startswith("地点："):
            result["location"] = line.replace("地点：", "").strip()
        elif line.startswith("时间："):
            result["date"] = line.replace("时间：", "").strip()
        elif line.startswith("人数："):
            count_str = line.replace("人数：", "").strip()
            try:
                result["count"] = int("".join(filter(str.isdigit, count_str)))
            except ValueError:
                result["count"] = 0
    return result
