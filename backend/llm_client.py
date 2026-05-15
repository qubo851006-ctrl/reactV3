import httpx
from openai import OpenAI, AsyncOpenAI
from config import AIRCHINA_API_KEY, AIRCHINA_BASE_URL, AI_HTTP_HOST_HEADER, AI_HTTP_VERIFY_SSL


def build_ai_http_headers(host_header: str = AI_HTTP_HOST_HEADER) -> dict[str, str]:
    return {"Host": host_header} if host_header else {}


def format_llm_error(error: Exception) -> str:
    text = str(error)
    if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text:
        return (
            "❌ AI 服务连接失败：证书校验失败。当前 AI 服务地址的 TLS 证书与访问地址不匹配。"
            "如果这是内网可信服务，请优先改用证书匹配的域名或更新服务端证书；"
            "临时处理可以在后端 .env 设置 AI_HTTP_VERIFY_SSL=false 后重启服务。"
        )
    return f"❌ AI 服务连接失败：{text}"


def get_llm_client() -> OpenAI:
    return OpenAI(
        api_key=AIRCHINA_API_KEY,
        base_url=AIRCHINA_BASE_URL,
        http_client=httpx.Client(
            verify=AI_HTTP_VERIFY_SSL,
            headers=build_ai_http_headers(),
        ),
    )


def get_async_llm_client() -> AsyncOpenAI:
    """返回异步 LLM 客户端（用于 async def 端点，不阻塞事件循环）。
    调用方应负责关闭 http_client，建议用 async with httpx.AsyncClient() as hc 包裹后传入。
    """
    return AsyncOpenAI(
        api_key=AIRCHINA_API_KEY,
        base_url=AIRCHINA_BASE_URL,
        http_client=httpx.AsyncClient(
            verify=AI_HTTP_VERIFY_SSL,
            headers=build_ai_http_headers(),
        ),
    )
