"""Chat router — thin transport layer over the skill dispatcher.

Responsibilities kept here:
- Session and history persistence (file-backed)
- HTTP/SSE plumbing
- LLM client lifecycle (httpx connection management)

Everything intent-related lives in `skills.dispatcher` and `skills.implementations.*`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from auth_utils import get_current_user
from config import (
    AI_HTTP_VERIFY_SSL,
    AIRCHINA_API_KEY,
    AIRCHINA_BASE_URL,
    DATA_ROOT,
)
from file_store import atomic_write_text, file_lock, safe_child_path
from llm_client import build_ai_http_headers, format_llm_error
from model_routes import resolve_chat_model, resolve_vision_model
from models import User
from skills.base import Classification, SkillContext
from skills.dispatcher import Dispatcher
from skills.implementations.kb_query import SKILL as KB_SKILL


_HISTORY_DIR = Path(DATA_ROOT) / "history"
_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

_SESSION_ID_RE = re.compile(r"^sess_[A-Za-z0-9_-]+$")

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Single dispatcher instance shared across requests; skills are stateless.
_DISPATCHER = Dispatcher()


# ── SSE ────────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Session / history persistence (unchanged from V2) ──────────────────

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
        return safe_child_path(base, f"{session_id}.json")
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _auto_title(messages: list) -> str:
    for m in messages:
        if m.get("role") == "user":
            t = m["content"][:20]
            return (t + "…") if len(m["content"]) > 20 else t
    return "新对话"


def load_sessions(user_id: int) -> list:
    sp = _sessions_path(user_id)
    old_file = _HISTORY_DIR / f"user_{user_id}.json"
    if old_file.exists() and not sp.exists():
        try:
            old_msgs = json.loads(old_file.read_text(encoding="utf-8"))
        except Exception:
            old_msgs = []
        if old_msgs:
            migrated_path = _session_msg_path(user_id, "sess_migrated")
            with file_lock(migrated_path):
                atomic_write_text(
                    migrated_path,
                    json.dumps(old_msgs, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            now = _now_iso()
            init_sessions = [
                {"id": "sess_migrated", "title": _auto_title(old_msgs),
                 "created_at": now, "updated_at": now}
            ]
            with file_lock(sp):
                atomic_write_text(
                    sp,
                    json.dumps(init_sessions, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
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
            atomic_write_text(
                path, json.dumps(sessions, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
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
            atomic_write_text(
                path, json.dumps(messages, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
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
        logging.exception(
            "Failed to save chat history for user %s session %s",
            user_id, session_id,
        )
        raise RuntimeError(f"保存会话历史失败：{exc}") from exc


def _create_session(user_id: int) -> dict:
    session_id = f"sess_{int(_time.time() * 1000)}"
    now = _now_iso()
    meta = {"id": session_id, "title": "新对话",
            "created_at": now, "updated_at": now}
    sessions = load_sessions(user_id)
    sessions.insert(0, meta)
    save_sessions(sessions, user_id)
    return meta


def _append_and_save(history: list, user_msg: str, assistant_msg: str,
                     user_id: int, session_id: str) -> None:
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    save_history(history, user_id, session_id)


# ── Session HTTP endpoints ─────────────────────────────────────────────

@router.get("/sessions")
def list_sessions(user: User = Depends(get_current_user)):
    return {"sessions": load_sessions(user.id)}


@router.post("/sessions")
def create_session_ep(user: User = Depends(get_current_user)):
    meta = _create_session(user.id)
    return {"session_id": meta["id"], "title": meta["title"]}


class RenameRequest(BaseModel):
    title: str


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameRequest,
                   user: User = Depends(get_current_user)):
    _session_msg_path(user.id, session_id)
    sessions = load_sessions(user.id)
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = body.title.strip() or "新对话"
            break
    save_sessions(sessions, user.id)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str,
                   user: User = Depends(get_current_user)):
    msg_file = _session_msg_path(user.id, session_id)
    sessions = load_sessions(user.id)
    sessions = [s for s in sessions if s["id"] != session_id]
    save_sessions(sessions, user.id)
    if msg_file.exists():
        with file_lock(msg_file):
            msg_file.unlink()
    return {"ok": True}


@router.get("/history")
def get_history(session_id: str,
                user: User = Depends(get_current_user)):
    saved = load_history(user.id, session_id)
    if not saved:
        saved = [{
            "role": "assistant",
            "content": "你好！我是**法务合规部智能助手**，可以帮您完成培训统计、案件台账、授权请示、企业信息查询等工作，也可以回答您的各类问题。",
        }]
    return {"messages": saved}


@router.delete("/history")
def clear_history(session_id: str,
                  user: User = Depends(get_current_user)):
    save_history([], user.id, session_id)
    sessions = load_sessions(user.id)
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = "新对话"
            break
    save_sessions(sessions, user.id)
    return {"ok": True}


# ── Main chat endpoint ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    use_kb: bool = False
    kb_conversation_id: str = ""
    session_id: str = ""
    model: str | None = None
    vision_model: str | None = None


@router.post("")
async def chat(req: ChatRequest, user: User = Depends(get_current_user)):
    """Stream one chat turn through the skill dispatcher."""
    uid = user.id
    sid = req.session_id
    selected_chat_model = resolve_chat_model(req.model)
    selected_vision_model = resolve_vision_model(req.vision_model)

    async def generate():
        history = await asyncio.to_thread(load_history, uid, sid)
        accumulated_text = ""

        async with httpx.AsyncClient(
            verify=AI_HTTP_VERIFY_SSL,
            headers=build_ai_http_headers(),
        ) as http_client:
            client = AsyncOpenAI(
                api_key=AIRCHINA_API_KEY,
                base_url=AIRCHINA_BASE_URL,
                http_client=http_client,
            )

            def make_ctx(classification: Classification) -> SkillContext:
                return SkillContext(
                    user=user,
                    message=req.message,
                    history=history,
                    classification=classification,
                    llm_client=client,
                    selected_chat_model=selected_chat_model,
                    selected_vision_model=selected_vision_model,
                    use_kb=req.use_kb,
                    kb_conversation_id=req.kb_conversation_id,
                    session_id=sid,
                    tracer=_DISPATCHER.tracer,
                )

            # KB short-circuit: KB selection is request-flag-based, not
            # intent-based, so we route directly without classifier.
            if req.use_kb:
                ctx = make_ctx(Classification(intent=KB_SKILL.intent))
                event_iter = KB_SKILL.handle(ctx)
            else:
                event_iter = _DISPATCHER.dispatch(
                    make_ctx, client, req.message,
                    user_id=uid, session_id=sid,
                )

            try:
                async for event in event_iter:
                    if event.get("type") == "chunk":
                        accumulated_text += event.get("text", "")
                        yield _sse(event)
                    elif event.get("type") == "done":
                        final_text = event.get("reply") or accumulated_text
                        if final_text:
                            await asyncio.to_thread(
                                _append_and_save,
                                history, req.message, final_text, uid, sid,
                            )
                        yield _sse(event)
                    else:
                        yield _sse(event)
            except Exception as e:
                err = format_llm_error(e)
                if accumulated_text:
                    accumulated_text += f"\n\n{err}"
                    yield _sse({"type": "chunk", "text": f"\n\n{err}"})
                else:
                    accumulated_text = err
                await asyncio.to_thread(
                    _append_and_save,
                    history, req.message, accumulated_text, uid, sid,
                )
                yield _sse({"type": "done", "reply": "", "next_stage": "idle",
                            "kb_conversation_id": ""})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
