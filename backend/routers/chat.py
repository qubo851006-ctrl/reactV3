import asyncio
import json
import logging
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
from openai import AsyncOpenAI

from config import (
    DATA_ROOT, ZHISHU_API_KEY, ZHISHU_BASE_URL, AI_HTTP_VERIFY_SSL,
    AIRCHINA_API_KEY, AIRCHINA_BASE_URL,
)
from file_store import atomic_write_text, file_lock, safe_child_path
from llm_client import format_llm_error, build_ai_http_headers
from model_routes import resolve_chat_model, resolve_intent_model, resolve_vision_model
from auth_utils import get_current_user
from models import User
from skills.registry import (
    ACTIONABLE_STAGES,
    INTENT_DESCRIPTIONS_WORKFLOW,
    INTENT_RESPONSES,
    VALID_INTENTS,
    WORKFLOW_HINTS,
    QCC_INTENT_DESCRIPTIONS,
)

_HISTORY_DIR = Path(DATA_ROOT) / "history"
_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# session_id 只允许 sess_ 开头 + 字母数字下划线，防止路径穿越
_SESSION_ID_RE = re.compile(r'^sess_[A-Za-z0-9_-]+$')

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 兼容旧测试和可能的外部导入；实际来源已迁移到 skills.registry。
_VALID_INTENTS = VALID_INTENTS
_ACTIONABLE_STAGES = ACTIONABLE_STAGES
_INTENT_DESCRIPTIONS_WORKFLOW = INTENT_DESCRIPTIONS_WORKFLOW
_WORKFLOW_HINTS = WORKFLOW_HINTS

# ── 辅助函数 ─────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    """格式化 SSE 事件行。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _append_and_save(history: list, user_msg: str, assistant_msg: str, user_id: int, session_id: str):
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    save_history(history, user_id, session_id)


def _chunk_delta_content(chunk) -> str | None:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return None
    delta = getattr(choices[0], "delta", None)
    return getattr(delta, "content", None)


def _is_model_status_question(message: str) -> bool:
    normalized = re.sub(r"\s+", "", message.lower())
    return any(
        keyword in normalized
        for keyword in [
            "你是什么模型",
            "当前模型",
            "用的什么模型",
            "模型是什么",
            "现在是什么模型",
        ]
    )


# ── 异步 LLM 调用函数 ─────────────────────────────────────────────

def _resolve_chat_model(requested: str | None, allowed_models: list[str] | None = None, default_model: str | None = None) -> str:
    if allowed_models is not None and default_model is not None:
        normalized = (requested or "").strip()
        if normalized and normalized in allowed_models:
            return normalized
        if default_model in allowed_models:
            return default_model
        return allowed_models[0] if allowed_models else default_model
    return resolve_chat_model(requested)


async def _classify_async(client: AsyncOpenAI, message: str) -> dict:
    """
    异步意图分类（不阻塞事件循环）。
    单次 LLM 调用同时完成意图识别、公司名提取、next_stage 判断。
    """
    system_prompt = f"""你是法务合规部的智能助手意图分析器。只返回 JSON，不要其他内容。

【工作流意图】格式：{{"intent": "意图名"}}
{INTENT_DESCRIPTIONS_WORKFLOW}

{QCC_INTENT_DESCRIPTIONS}

【普通对话】格式：{{"intent": "other", "next_stage": null}}
next_stage 可选值（仅当用户有明确操作需求时填入，否则填 null）：
waiting_files / waiting_ledger_files / waiting_auth_file / waiting_compliance_file / waiting_ledger_merge_files / waiting_audit_file"""

    resp = await client.chat.completions.create(
        model=resolve_intent_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        max_tokens=80,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        data = json.loads(raw)
        intent = data.get("intent", "other")
        if intent not in VALID_INTENTS:
            intent = "other"
        try:
            claim_amount = float(data.get("claim_amount") or 0)
        except (TypeError, ValueError):
            claim_amount = 0.0
        return {
            "intent": intent,
            "company": data.get("company"),
            "claim_amount": claim_amount,
            "next_stage": data.get("next_stage"),
        }
    except Exception:
        return {"intent": "other", "company": None, "claim_amount": 0.0, "next_stage": None}


async def _stream_reply_async(client: AsyncOpenAI, message: str, history: list, model: str):
    """
    异步流式回复生成器（不阻塞事件循环）。
    """
    system_prompt = f"""你是法务合规部的智能助手，请用中文简洁友好地回答用户问题。

可以引导用户使用的功能：
{WORKFLOW_HINTS}

直接输出回复内容，不需要 JSON 格式。"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=500,
    )
    async for chunk in stream:
        delta = _chunk_delta_content(chunk)
        if delta:
            yield delta
            await asyncio.sleep(0)  # 主动让出事件循环，避免高频 token 流饿死其他协程


# ── Session 存储（每用户独立目录，每 session 一个文件）─────────

def _user_dir(user_id: int) -> Path:
    d = _HISTORY_DIR / f"user_{user_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _sessions_path(user_id: int) -> Path:
    return _user_dir(user_id) / "sessions.json"

def _session_msg_path(user_id: int, session_id: str) -> Path:
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="无效的 session_id 格式")
    base = _user_dir(user_id).resolve()
    try:
        p = safe_child_path(base, f"{session_id}.json")
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id")
    return p

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _auto_title(messages: list) -> str:
    for m in messages:
        if m.get("role") == "user":
            t = m["content"][:20]
            return (t + "…") if len(m["content"]) > 20 else t
    return "新对话"

def load_sessions(user_id: int) -> list:
    """加载会话元数据列表，首次自动迁移旧版单文件。"""
    sp = _sessions_path(user_id)
    old_file = _HISTORY_DIR / f"user_{user_id}.json"
    # 迁移旧格式：history/user_{id}.json → user_{id}/sess_migrated.json
    if old_file.exists() and not sp.exists():
        try:
            old_msgs = json.loads(old_file.read_text(encoding="utf-8"))
        except Exception:
            old_msgs = []
        if old_msgs:
            migrated_path = _session_msg_path(user_id, "sess_migrated")
            with file_lock(migrated_path):
                atomic_write_text(migrated_path, json.dumps(old_msgs, ensure_ascii=False, indent=2), encoding="utf-8")
            now = _now_iso()
            init_sessions = [{"id": "sess_migrated", "title": _auto_title(old_msgs),
                               "created_at": now, "updated_at": now}]
            with file_lock(sp):
                atomic_write_text(sp, json.dumps(init_sessions, ensure_ascii=False, indent=2), encoding="utf-8")
        old_file.rename(old_file.with_suffix(".bak"))
    if not sp.exists():
        return []
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_sessions(sessions: list, user_id: int):
    path = _sessions_path(user_id)
    try:
        with file_lock(path):
            atomic_write_text(path, json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to save sessions for user %s", user_id)
        raise RuntimeError(f"保存会话列表失败：{exc}") from exc

def load_history(user_id: int, session_id: str) -> list:
    if not session_id:
        return []
    p = _session_msg_path(user_id, session_id)
    if not p.exists():
        return []
    try:
        with file_lock(p):
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_history(messages: list, user_id: int, session_id: str):
    if not session_id:
        return
    try:
        path = _session_msg_path(user_id, session_id)
        with file_lock(path):
            atomic_write_text(path, json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
        # 同步更新 sessions.json 的 updated_at 和自动标题
        sessions = load_sessions(user_id)
        now = _now_iso()
        for s in sessions:
            if s["id"] == session_id:
                s["updated_at"] = now
                if s["title"] == "新对话":
                    s["title"] = _auto_title(messages)
                break
        sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        save_sessions(sessions, user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to save chat history for user %s session %s", user_id, session_id)
        raise RuntimeError(f"保存会话历史失败：{exc}") from exc

def _create_session(user_id: int) -> dict:
    session_id = f"sess_{int(_time.time() * 1000)}"
    now = _now_iso()
    meta = {"id": session_id, "title": "新对话", "created_at": now, "updated_at": now}
    sessions = load_sessions(user_id)
    sessions.insert(0, meta)
    save_sessions(sessions, user_id)
    return meta


# ── HTTP 端点 ────────────────────────────────────────────────────

@router.get("/sessions")
def list_sessions(user: User = Depends(get_current_user)):
    sessions = load_sessions(user.id)
    return {"sessions": sessions}

@router.post("/sessions")
def create_session_ep(user: User = Depends(get_current_user)):
    meta = _create_session(user.id)
    return {"session_id": meta["id"], "title": meta["title"]}

class RenameRequest(BaseModel):
    title: str

@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameRequest, user: User = Depends(get_current_user)):
    _session_msg_path(user.id, session_id)
    sessions = load_sessions(user.id)
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = body.title.strip() or "新对话"
            break
    save_sessions(sessions, user.id)
    return {"ok": True}

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: User = Depends(get_current_user)):
    msg_file = _session_msg_path(user.id, session_id)
    sessions = load_sessions(user.id)
    sessions = [s for s in sessions if s["id"] != session_id]
    save_sessions(sessions, user.id)
    if msg_file.exists():
        with file_lock(msg_file):
            msg_file.unlink()
    return {"ok": True}

@router.get("/history")
def get_history(session_id: str, user: User = Depends(get_current_user)):
    saved = load_history(user.id, session_id)
    if not saved:
        saved = [{
            "role": "assistant",
            "content": "你好！我是**法务合规部智能助手**，可以帮您完成培训统计、案件台账、授权请示、企业信息查询等工作，也可以回答您的各类问题。"
        }]
    return {"messages": saved}

@router.delete("/history")
def clear_history(session_id: str, user: User = Depends(get_current_user)):
    save_history([], user.id, session_id)
    sessions = load_sessions(user.id)
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = "新对话"
            break
    save_sessions(sessions, user.id)
    return {"ok": True}


class ChatRequest(BaseModel):
    message: str
    use_kb: bool = False
    kb_conversation_id: str = ""
    session_id: str = ""
    model: str | None = None
    vision_model: str | None = None


@router.post("")
async def chat(req: ChatRequest, user: User = Depends(get_current_user)):
    """
    聊天主端点（异步）。
    使用 AsyncOpenAI 和 async for，LLM 调用完全非阻塞，
    事件循环可在两个 token 之间处理其他会话的请求（新建会话、切换会话等）。
    """
    uid = user.id
    sid = req.session_id
    selected_model = _resolve_chat_model(req.model)
    selected_vision_model = resolve_vision_model(req.vision_model)

    async def generate():
        # 文件 I/O 也卸载到线程，保持事件循环畅通
        history = await asyncio.to_thread(load_history, uid, sid)

        # ── 模型状态查询（直接返回，无需 LLM）─────────────────────
        if _is_model_status_question(req.message):
            reply = f"当前文字模型：{selected_model}\n当前图像模型：{selected_vision_model}"
            await asyncio.to_thread(_append_and_save, history, req.message, reply, uid, sid)
            yield _sse({"type": "done", "reply": reply, "next_stage": "idle", "kb_conversation_id": ""})
            return


        # ── 知识库模式（异步 HTTP，不再阻塞）──────────────────────
        if req.use_kb:
            try:
                async with httpx.AsyncClient(verify=AI_HTTP_VERIFY_SSL, timeout=120) as hc:
                    resp = await hc.post(
                        f"{ZHISHU_BASE_URL}/chat-messages",
                        json={
                            "query": req.message,
                            "inputs": {},
                            "response_mode": "blocking",
                            "user": "training-manager",
                            "conversation_id": req.kb_conversation_id,
                        },
                        headers={
                            "Authorization": f"Bearer {ZHISHU_API_KEY}",
                            "Content-Type": "application/json",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data.get("answer", "（知识库未返回内容）")
                    new_conv_id = data.get("conversation_id", "")
            except Exception as e:
                reply = f"❌ 知识库查询失败：{e}"
                new_conv_id = ""
            await asyncio.to_thread(_append_and_save, history, req.message, reply, uid, sid)
            yield _sse({"type": "done", "reply": reply, "next_stage": "idle", "kb_conversation_id": new_conv_id})
            return

        # ── 异步 LLM 客户端（整个生命周期由 async with 管理）──────
        async with httpx.AsyncClient(
            verify=AI_HTTP_VERIFY_SSL,
            headers=build_ai_http_headers(),
        ) as http_client:
            client = AsyncOpenAI(
                api_key=AIRCHINA_API_KEY,
                base_url=AIRCHINA_BASE_URL,
                http_client=http_client,
            )

            # ── 意图分类（异步，不占线程池）──────────────────────
            try:
                cls = await _classify_async(client, req.message)
            except Exception as e:
                reply = format_llm_error(e)
                await asyncio.to_thread(_append_and_save, history, req.message, reply, uid, sid)
                yield _sse({"type": "done", "reply": reply, "next_stage": "idle", "kb_conversation_id": ""})
                return
            intent = cls["intent"]

            # ── 固定回复意图 ──────────────────────────────────────
            if intent in INTENT_RESPONSES:
                reply, next_stage = INTENT_RESPONSES[intent]
                await asyncio.to_thread(_append_and_save, history, req.message, reply, uid, sid)
                yield _sse({"type": "done", "reply": reply, "next_stage": next_stage, "kb_conversation_id": ""})
                return

            # ── 企业查询（同步库，卸载到线程）───────────────────
            if intent == "query_company":
                company = cls.get("company") or req.message
                try:
                    # 优先使用企查查 MCP；失败时回退到旧 mcpmarket 端点
                    from utils.qcc_mcp_client import (
                        query_company as qcc_query,
                        format_company_markdown as qcc_format,
                    )
                    try:
                        result = await asyncio.to_thread(qcc_query, company)
                        reply = qcc_format(result)
                    except Exception:
                        from utils.mcp_client import query_company, format_company_markdown
                        result = await asyncio.to_thread(query_company, company)
                        reply = format_company_markdown(result)
                except ValueError as e:
                    reply = f"❌ 未找到匹配企业：{e}"
                except Exception as e:
                    reply = f"❌ 企业信息查询失败：{e}"
                await asyncio.to_thread(_append_and_save, history, req.message, reply, uid, sid)
                yield _sse({"type": "done", "reply": reply, "next_stage": "idle", "kb_conversation_id": ""})
                return

            # ── 债务清偿能力评估（同步，卸载到线程）──────────────
            if intent == "debt_recovery_assessment":
                company = cls.get("company") or req.message
                claim_amount = cls.get("claim_amount") or 0.0
                try:
                    from utils.qcc_debt_assessment import (
                        assess_debt_recovery,
                        format_assessment_markdown,
                    )
                    result = await asyncio.to_thread(
                        assess_debt_recovery, company, float(claim_amount)
                    )
                    reply = format_assessment_markdown(result)
                except Exception as e:
                    reply = f"❌ 债务清偿评估失败：{e}"
                await asyncio.to_thread(_append_and_save, history, req.message, reply, uid, sid)
                yield _sse({"type": "done", "reply": reply, "next_stage": "idle", "kb_conversation_id": ""})
                return

            # ── 通用对话（异步流式，每个 token await 后事件循环可响应其他请求）
            next_stage = cls.get("next_stage") or "idle"
            if next_stage not in ACTIONABLE_STAGES:
                next_stage = "idle"

            accumulated = ""
            try:
                async for chunk in _stream_reply_async(client, req.message, history, selected_model):
                    accumulated += chunk
                    yield _sse({"type": "chunk", "text": chunk})
            except Exception as e:
                reply = format_llm_error(e)
                if accumulated:
                    accumulated = f"{accumulated}\n\n{reply}"
                    yield _sse({"type": "chunk", "text": f"\n\n{reply}"})
                    reply = ""
                else:
                    accumulated = reply
                await asyncio.to_thread(_append_and_save, history, req.message, accumulated, uid, sid)
                yield _sse({"type": "done", "reply": reply, "next_stage": "idle", "kb_conversation_id": ""})
                return

            await asyncio.to_thread(_append_and_save, history, req.message, accumulated, uid, sid)
            yield _sse({"type": "done", "reply": "", "next_stage": next_stage, "kb_conversation_id": ""})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx/代理层缓冲，确保 chunk 实时到达客户端
        },
    )
