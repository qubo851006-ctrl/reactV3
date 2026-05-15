"""
Skill plugin contract for the chat dispatcher.

Each business capability (intent classification → action) is implemented as a
Skill class. The dispatcher discovers skills, picks one based on the LLM's
intent classification, and runs it inside an SSE stream.

Design notes:
- Skills are async generators yielding raw event dicts; the dispatcher wraps
  them into SSE frames. Skills never format SSE themselves.
- All runtime dependencies (LLM client, models, tracer, history) reach skills
  through SkillContext — never via module-level globals — so unit tests can
  swap them out.
- The tracer is a no-op stub today; P0-2 will plug in the real LLMTracer
  without touching skill implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable

from openai import AsyncOpenAI

from models import User
from skills.tracer import LLMTracer


@dataclass
class Classification:
    """Result of LLM intent classification."""
    intent: str
    company: str | None = None
    claim_amount: float = 0.0
    next_stage: str | None = None


@dataclass
class SkillContext:
    """Everything a skill needs to run one turn of conversation."""
    user: User
    message: str
    history: list[dict]
    classification: Classification
    llm_client: AsyncOpenAI
    selected_chat_model: str
    selected_vision_model: str
    use_kb: bool
    kb_conversation_id: str
    session_id: str
    tracer: LLMTracer


# ── SSE event payload helpers ─────────────────────────────────────────
# Skills yield these dicts; dispatcher serialises them as SSE frames.

def chunk_event(text: str) -> dict:
    """Streaming token fragment."""
    return {"type": "chunk", "text": text}


def done_event(
    reply: str,
    next_stage: str = "idle",
    kb_conversation_id: str = "",
) -> dict:
    """Terminal event — dispatcher persists history after seeing this."""
    return {
        "type": "done",
        "reply": reply,
        "next_stage": next_stage,
        "kb_conversation_id": kb_conversation_id,
    }


@runtime_checkable
class Skill(Protocol):
    """Skill plugin contract.

    Implementations must be classes (not instances) exposing:
    - `intent`: the canonical intent string the classifier returns
    - `description`: one-line human-readable description, used to build the
      classifier prompt automatically
    - `handle(ctx)`: async generator yielding event dicts
    """

    intent: str
    description: str

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        ...


@dataclass
class SkillMeta:
    """Registration metadata exported by the dispatcher for prompt building."""
    intent: str
    description: str
    next_stage: str | None = None
    extra_fields: tuple[str, ...] = field(default_factory=tuple)
    """Extra JSON fields the classifier should emit for this intent
    (e.g. 'company' for query_company, 'claim_amount' for debt_recovery)."""
