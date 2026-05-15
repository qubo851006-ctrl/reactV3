"""
Skill dispatcher: discovers skills, classifies intent, routes to a skill.

Auto-discovery scans `skills.implementations` for any module exporting `SKILL`
or `SKILLS`. Each yielded value must be a Skill instance. The dispatcher keeps
them indexed by intent and exposes their metadata to the classifier.

Two extension hooks:
- `fast_match(message)` on a Skill (optional) lets it claim a turn without
  going through the LLM classifier — used by short-circuit skills like model
  status queries.
- A skill registered under intent `"other"` becomes the fallback for messages
  the classifier marks as plain conversation. Exactly one fallback expected.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import AsyncIterator

from openai import AsyncOpenAI

from skills import implementations as _impl_pkg
from skills.base import Classification, Skill, SkillContext, SkillMeta
from skills.classifier import classify
from skills.tracer import DEFAULT_TRACER, LLMTracer

_FALLBACK_INTENT = "other"


def _default_production_tracer() -> LLMTracer:
    """Use PersistentTracer when llm_audit is importable, else fall back."""
    try:
        from llm_audit.tracer import PersistentTracer
        return PersistentTracer()
    except Exception:  # noqa: BLE001 — tracing must never break boot
        logging.exception("PersistentTracer unavailable; using NoopTracer")
        return DEFAULT_TRACER


def _iter_skill_modules():
    for mod_info in pkgutil.iter_modules(_impl_pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        yield importlib.import_module(f"{_impl_pkg.__name__}.{mod_info.name}")


def _extract_skills(module) -> list[Skill]:
    skills: list[Skill] = []
    obj = getattr(module, "SKILL", None)
    if obj is not None:
        skills.append(obj)
    obj_list = getattr(module, "SKILLS", None)
    if obj_list:
        skills.extend(obj_list)
    return skills


def discover_skills() -> list[Skill]:
    """Load every Skill exported by `skills.implementations.*`."""
    found: list[Skill] = []
    for module in _iter_skill_modules():
        try:
            found.extend(_extract_skills(module))
        except Exception:
            logging.exception("failed to load skill module %s", module.__name__)
    return found


def _skill_meta(skill: Skill) -> SkillMeta:
    """Read class-level metadata from a Skill instance."""
    return SkillMeta(
        intent=skill.intent,
        description=skill.description,
        next_stage=getattr(skill, "next_stage", None),
        extra_fields=tuple(getattr(skill, "extra_fields", ()) or ()),
    )


class Dispatcher:
    """Owns the skill registry and runs one turn end-to-end."""

    def __init__(
        self,
        skills: list[Skill] | None = None,
        tracer: LLMTracer | None = None,
    ) -> None:
        loaded = skills if skills is not None else discover_skills()
        self._by_intent: dict[str, Skill] = {}
        for s in loaded:
            if s.intent in self._by_intent:
                logging.warning(
                    "duplicate skill intent %r: %s overrides %s",
                    s.intent, type(s).__name__, type(self._by_intent[s.intent]).__name__,
                )
            self._by_intent[s.intent] = s
        if _FALLBACK_INTENT not in self._by_intent:
            logging.warning(
                "no fallback skill registered (intent=%r); 'other' messages will fail",
                _FALLBACK_INTENT,
            )
        self._tracer = tracer or _default_production_tracer()

    @property
    def tracer(self) -> LLMTracer:
        return self._tracer

    @property
    def skills(self) -> list[Skill]:
        return list(self._by_intent.values())

    def metas_for_classifier(self) -> list[SkillMeta]:
        """Skills exposed to the intent classifier (excludes fallback)."""
        return [
            _skill_meta(s)
            for intent, s in self._by_intent.items()
            if intent != _FALLBACK_INTENT
        ]

    def _fast_match(self, message: str) -> Skill | None:
        for skill in self._by_intent.values():
            matcher = getattr(skill, "fast_match", None)
            if matcher is None:
                continue
            try:
                if matcher(message):
                    return skill
            except Exception:
                logging.exception("fast_match raised in %s", type(skill).__name__)
        return None

    def _resolve(self, intent: str) -> Skill:
        return self._by_intent.get(intent) or self._by_intent[_FALLBACK_INTENT]

    async def classify_only(
        self,
        client: AsyncOpenAI,
        message: str,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
    ) -> Classification:
        """Expose classifier without dispatching — useful for tests / debug."""
        return await classify(
            client,
            message,
            self.metas_for_classifier(),
            tracer=self._tracer,
            user_id=user_id,
            session_id=session_id,
        )

    async def dispatch(
        self,
        ctx_factory,
        client: AsyncOpenAI,
        message: str,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Run one turn.

        `ctx_factory(classification: Classification) -> SkillContext` is
        provided by the caller so transport-layer concerns (history loading,
        model resolution, KB toggle) stay outside the dispatcher.
        """
        fast = self._fast_match(message)
        if fast is not None:
            classification = Classification(intent=fast.intent)
            skill = fast
        else:
            classification = await self.classify_only(
                client, message, user_id=user_id, session_id=session_id,
            )
            skill = self._resolve(classification.intent)

        ctx = ctx_factory(classification)
        async for event in skill.handle(ctx):
            yield event
