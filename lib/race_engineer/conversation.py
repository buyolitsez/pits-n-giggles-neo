# MIT License
#
# Copyright (c) [2026] [Ashwin Natarajan]
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# -------------------------------------- IMPORTS -----------------------------------------------------------------------

import asyncio
import json
import os
import shlex
from dataclasses import dataclass, replace
import time
from typing import Any, Dict, List, Optional, Protocol
import urllib.error
import urllib.request

from .agent_prompts import ADVICE_CATEGORIES, CATEGORY_ALL, normalise_agent_focus
from .brief import build_race_engineer_brief
from .memory import (
    RaceEngineerMemory,
    apply_race_engineer_memory_feedback,
    load_race_engineer_memory,
    race_engineer_memory_answer_limits,
    race_engineer_memory_has_preferences,
    race_engineer_memory_to_prompt_context,
    save_race_engineer_memory,
)

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_HTTP_CONVERSATION_USER_AGENT = "pits-n-giggles-race-engineer"
RADIO_ANSWER_MAX_SENTENCES = 2
RADIO_ANSWER_MAX_CHARS = 180

_FOCUS_KEYWORDS = {
    "pace": ("pace", "lap", "gap", "delta", "sector", "быстр", "темп", "круг", "сектор", "дельт"),
    "tyres": ("tyre", "tire", "wear", "compound", "шин", "резин", "износ", "компаунд"),
    "fuel": ("fuel", "lift", "coast", "топлив", "бенз", "эконом"),
    "ers": ("ers", "battery", "overtake", "drs", "батар", "обгон", "дрс"),
    "damage": ("damage", "wing", "engine", "floor", "повреж", "крыл", "мотор", "двиг"),
    "weather": ("weather", "rain", "dry", "wet", "погод", "дожд", "сух", "мокр"),
    "strategy": ("pit", "box", "stop", "undercut", "overcut", "стратег", "пит", "бокс", "андеркат"),
    "driving_coach": ("brake", "throttle", "coast", "trail", "тормоз", "газ", "коаст", "педал"),
}
_TYRE_STRATEGY_TERMS = (
    "tyre",
    "tire",
    "compound",
    "шин",
    "резин",
    "компаунд",
)
_TYRE_STRATEGY_DECISION_TERMS = (
    "take",
    "fit",
    "put",
    "use",
    "box",
    "pit",
    "stop",
    "став",
    "брать",
    "взять",
    "постав",
    "одеть",
    "выбрать",
    "пит",
    "бокс",
)

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RaceEngineerAnswer:
    """Answer returned for a driver question."""

    ok: bool
    question: str
    answer: str
    source: str
    focus: str = CATEGORY_ALL
    error: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None


@dataclass(frozen=True, slots=True)
class CodexConversationPromptPackage:
    """Compact prompt package for a Codex-backed race engineer answer."""

    question: str
    focus: str
    messages: List[Dict[str, str]]
    context: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "focus": self.focus,
            "messages": list(self.messages),
            "context": self.context,
        }


@dataclass(frozen=True, slots=True)
class HttpConversationConfig:
    """Configuration for a Codex-compatible HTTP conversation endpoint."""

    endpoint: str
    key_env_var: str = ""
    timeout_seconds: float = 10.0
    user_agent: str = DEFAULT_HTTP_CONVERSATION_USER_AGENT
    provider_name: str = "external_http"

    def resolved_key(self) -> Optional[str]:
        if not self.key_env_var:
            return None
        return os.getenv(self.key_env_var)


@dataclass(frozen=True, slots=True)
class HttpConversationResponse:
    """HTTP response details returned by an external conversation endpoint."""

    status_code: int
    body: bytes = b""
    error_text: Optional[str] = None


@dataclass(frozen=True, slots=True)
class CodexCliConversationConfig:
    """Configuration for a local Codex CLI compatible command."""

    command: str
    timeout_seconds: float = 10.0
    provider_name: str = "codex_cli"


@dataclass(frozen=True, slots=True)
class CommandConversationResponse:
    """Completed local command response."""

    exit_code: int
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False


class RaceEngineerConversationAgent(Protocol):
    """Protocol for components that answer driver questions."""

    async def answer(
        self,
        question: str,
        *,
        telemetry_update: Optional[Dict[str, Any]] = None,
    ) -> RaceEngineerAnswer:
        """Answer one driver question using current race context."""


class HttpConversationClient(Protocol):
    """Protocol for the small external race-engineer conversation surface."""

    async def answer(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout_seconds: float,
    ) -> HttpConversationResponse:
        """Send one compact prompt package and receive an answer."""


class CommandConversationRunner(Protocol):
    """Protocol for local conversation command execution."""

    async def run(
        self,
        *,
        argv: List[str],
        stdin: bytes,
        timeout_seconds: float,
    ) -> CommandConversationResponse:
        """Run a local command and return captured output."""


class AioHttpConversationClient:
    """HTTP client implemented with aiohttp or a stdlib fallback."""

    async def answer(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout_seconds: float,
    ) -> HttpConversationResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            import aiohttp
        except ModuleNotFoundError:
            return await asyncio.to_thread(
                _post_conversation_with_urllib,
                url=url,
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds,
            )

        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=body) as response:
                response_body = await response.read()
                error_text = None
                if response.status >= 400:
                    error_text = response_body.decode("utf-8", errors="replace")
                return HttpConversationResponse(
                    status_code=response.status,
                    body=response_body,
                    error_text=error_text,
                )


class AsyncioCommandConversationRunner:
    """Run a local command without invoking a shell."""

    async def run(
        self,
        *,
        argv: List[str],
        stdin: bytes,
        timeout_seconds: float,
    ) -> CommandConversationResponse:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            return CommandConversationResponse(
                exit_code=process.returncode if process.returncode is not None else -1,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )
        return CommandConversationResponse(
            exit_code=process.returncode if process.returncode is not None else 0,
            stdout=stdout,
            stderr=stderr,
        )


class LocalBriefConversationAgent:
    """Answer driver questions from the current race engineer brief."""

    source = "local_brief"

    def __init__(
        self,
        *,
        agent_prompt_overrides: Optional[Dict[str, Dict[str, str]]] = None,
        memory_file: str = "",
    ) -> None:
        self.agent_prompt_overrides = agent_prompt_overrides or {}
        self.memory_file = memory_file

    async def answer(
        self,
        question: str,
        *,
        telemetry_update: Optional[Dict[str, Any]] = None,
    ) -> RaceEngineerAnswer:
        question = _clean_question(question)
        if not question:
            return RaceEngineerAnswer(
                ok=False,
                question="",
                answer="I did not catch the question.",
                source=self.source,
                error="empty question",
            )
        if not isinstance(telemetry_update, dict):
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="I do not have live telemetry yet.",
                source=self.source,
                error="missing telemetry",
            )

        memory = _load_memory_or_default(self.memory_file)
        focus = infer_question_focus(question)
        brief = build_race_engineer_brief(
            telemetry_update=telemetry_update,
            base_rsp={"available": False, "connected": True, "ok": False},
            focus=focus,
            max_items=5,
            agent_prompt_overrides=self.agent_prompt_overrides,
        )
        if not brief.get("ok"):
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="I cannot read the current telemetry snapshot yet.",
                source=self.source,
                focus=focus,
                error=str(brief.get("error") or "brief unavailable"),
            )

        advice = brief.get("advice") if isinstance(brief.get("advice"), list) else []
        prompt_package = build_codex_conversation_prompt_package(
            question,
            brief=brief,
            focus=focus,
            memory=memory,
        )
        if advice:
            answer = _answer_from_advice(advice[0], question=question, memory=memory)
        else:
            answer = _answer_from_context(brief, focus, question=question, memory=memory)

        memory_context = race_engineer_memory_to_prompt_context(memory)
        return RaceEngineerAnswer(
            ok=True,
            question=question,
            answer=answer,
            source=self.source,
            focus=focus,
            metrics={
                "advice_count": len(advice),
                "session_uid": brief.get("session_uid"),
                "focus": focus,
                "codex_prompt_focus": prompt_package.focus,
                "codex_prompt_context_keys": sorted(prompt_package.context.keys()),
                "memory_preferences": race_engineer_memory_has_preferences(memory),
                "memory_verbosity": memory_context.get("verbosity"),
                "codex_prompt_advice_ids": [
                    item.get("id")
                    for item in prompt_package.context.get("advice", [])
                    if isinstance(item, dict) and item.get("id")
                ],
            },
        )


class HttpConversationAgent:
    """Answer driver questions by sending compact context to an external endpoint."""

    def __init__(
        self,
        config: HttpConversationConfig,
        *,
        client: Optional[HttpConversationClient] = None,
        agent_prompt_overrides: Optional[Dict[str, Dict[str, str]]] = None,
        memory_file: str = "",
    ) -> None:
        self.config = config
        self.source = config.provider_name
        self.client = client or AioHttpConversationClient()
        self.agent_prompt_overrides = agent_prompt_overrides or {}
        self.memory_file = memory_file

    async def answer(
        self,
        question: str,
        *,
        telemetry_update: Optional[Dict[str, Any]] = None,
    ) -> RaceEngineerAnswer:
        started_at = time.perf_counter()
        question = _clean_question(question)
        if not question:
            return _empty_question_answer(source=self.source)
        if not isinstance(telemetry_update, dict):
            return _missing_telemetry_answer(question, source=self.source)

        validation_error = self._validate()
        if validation_error:
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="External race engineer is not configured.",
                source=self.source,
                error=validation_error,
                metrics={"duration_ms": _elapsed_ms(started_at)},
            )

        memory = _load_memory_or_default(self.memory_file)
        focus = infer_question_focus(question)
        brief = build_race_engineer_brief(
            telemetry_update=telemetry_update,
            base_rsp={"available": False, "connected": True, "ok": False},
            focus=focus,
            max_items=5,
            agent_prompt_overrides=self.agent_prompt_overrides,
        )
        if not brief.get("ok"):
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="I cannot read the current telemetry snapshot yet.",
                source=self.source,
                focus=focus,
                error=str(brief.get("error") or "brief unavailable"),
                metrics={"duration_ms": _elapsed_ms(started_at)},
            )

        prompt_package = build_codex_conversation_prompt_package(
            question,
            brief=brief,
            focus=focus,
            memory=memory,
        )
        payload = {
            **prompt_package.as_dict(),
            "metadata": {
                "provider": self.source,
                "schema": "pits-n-giggles.race-engineer.conversation.v1",
            },
        }

        try:
            response = await self.client.answer(
                url=self.config.endpoint.strip(),
                headers=build_http_conversation_headers(self.config),
                payload=payload,
                timeout_seconds=self.config.timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="External race engineer did not answer.",
                source=self.source,
                focus=focus,
                error=f"conversation request failed: {exc}",
                metrics={"duration_ms": _elapsed_ms(started_at)},
            )

        return _answer_from_http_conversation_response(
            response,
            question=question,
            focus=focus,
            source=self.source,
            duration_ms=_elapsed_ms(started_at),
            memory=memory,
        )

    def _validate(self) -> Optional[str]:
        if not self.config.endpoint or not self.config.endpoint.strip():
            return "conversation endpoint is missing"
        if self.config.timeout_seconds <= 0:
            return "conversation timeout must be greater than zero"
        return None


class CodexCliConversationAgent:
    """Answer driver questions by sending compact context to a local CLI command."""

    def __init__(
        self,
        config: CodexCliConversationConfig,
        *,
        runner: Optional[CommandConversationRunner] = None,
        agent_prompt_overrides: Optional[Dict[str, Dict[str, str]]] = None,
        memory_file: str = "",
    ) -> None:
        self.config = config
        self.source = config.provider_name
        self.runner = runner or AsyncioCommandConversationRunner()
        self.agent_prompt_overrides = agent_prompt_overrides or {}
        self.memory_file = memory_file

    async def answer(
        self,
        question: str,
        *,
        telemetry_update: Optional[Dict[str, Any]] = None,
    ) -> RaceEngineerAnswer:
        started_at = time.perf_counter()
        question = _clean_question(question)
        if not question:
            return _empty_question_answer(source=self.source)
        if not isinstance(telemetry_update, dict):
            return _missing_telemetry_answer(question, source=self.source)

        argv = parse_conversation_command(self.config.command)
        if not argv:
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="Codex CLI race engineer is not configured.",
                source=self.source,
                error="conversation command is missing",
                metrics={"duration_ms": _elapsed_ms(started_at)},
            )
        if self.config.timeout_seconds <= 0:
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="Codex CLI race engineer is not configured.",
                source=self.source,
                error="conversation timeout must be greater than zero",
                metrics={"duration_ms": _elapsed_ms(started_at)},
            )

        memory = _load_memory_or_default(self.memory_file)
        focus = infer_question_focus(question)
        brief = build_race_engineer_brief(
            telemetry_update=telemetry_update,
            base_rsp={"available": False, "connected": True, "ok": False},
            focus=focus,
            max_items=5,
            agent_prompt_overrides=self.agent_prompt_overrides,
        )
        if not brief.get("ok"):
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="I cannot read the current telemetry snapshot yet.",
                source=self.source,
                focus=focus,
                error=str(brief.get("error") or "brief unavailable"),
                metrics={"duration_ms": _elapsed_ms(started_at)},
            )

        prompt_package = build_codex_conversation_prompt_package(
            question,
            brief=brief,
            focus=focus,
            memory=memory,
        )
        payload = {
            **prompt_package.as_dict(),
            "metadata": {
                "provider": self.source,
                "schema": "pits-n-giggles.race-engineer.conversation.v1",
                "stdin_contract": "json",
            },
        }
        stdin = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        try:
            response = await self.runner.run(
                argv=argv,
                stdin=stdin,
                timeout_seconds=self.config.timeout_seconds,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="Codex CLI race engineer did not answer.",
                source=self.source,
                focus=focus,
                error=f"conversation command failed: {exc}",
                metrics={"duration_ms": _elapsed_ms(started_at)},
            )

        return _answer_from_command_conversation_response(
            response,
            question=question,
            focus=focus,
            source=self.source,
            duration_ms=_elapsed_ms(started_at),
            memory=memory,
        )


class FallbackConversationAgent:
    """Use a primary conversation agent, then fall back to a local answer."""

    def __init__(
        self,
        primary: RaceEngineerConversationAgent,
        fallback: RaceEngineerConversationAgent,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    async def answer(
        self,
        question: str,
        *,
        telemetry_update: Optional[Dict[str, Any]] = None,
    ) -> RaceEngineerAnswer:
        primary_answer = await self.primary.answer(
            question,
            telemetry_update=telemetry_update,
        )
        if primary_answer.ok:
            return primary_answer

        fallback_answer = await self.fallback.answer(
            question,
            telemetry_update=telemetry_update,
        )
        metrics = dict(fallback_answer.metrics or {})
        metrics["fallback_from"] = primary_answer.source
        metrics["fallback_error"] = primary_answer.error
        metrics["fallback_answer_ok"] = fallback_answer.ok
        return replace(
            fallback_answer,
            source=f"{fallback_answer.source}_fallback",
            metrics=metrics,
        )


class MemoryConversationAgent:
    """Persist driver calibration feedback before normal question answering."""

    source = "memory"

    def __init__(
        self,
        wrapped: RaceEngineerConversationAgent,
        *,
        memory_file: str,
    ) -> None:
        self.wrapped = wrapped
        self.memory_file = memory_file

    async def answer(
        self,
        question: str,
        *,
        telemetry_update: Optional[Dict[str, Any]] = None,
    ) -> RaceEngineerAnswer:
        question = _clean_question(question)
        if not question:
            return await self.wrapped.answer(question, telemetry_update=telemetry_update)
        try:
            memory = load_race_engineer_memory(self.memory_file)
            update = apply_race_engineer_memory_feedback(memory, question)
            if not update.applied:
                return await self.wrapped.answer(question, telemetry_update=telemetry_update)
            save_race_engineer_memory(update.memory, self.memory_file)
            return RaceEngineerAnswer(
                ok=True,
                question=question,
                answer=update.acknowledgement,
                source=self.source,
                focus="memory",
                metrics={
                    "memory_updated": True,
                    "memory_file": self.memory_file,
                    "rules": list(update.rules),
                    "verbosity": update.memory.verbosity,
                    "max_sentences": update.memory.max_sentences,
                    "max_chars": update.memory.max_chars,
                },
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="I could not update race engineer memory.",
                source=self.source,
                focus="memory",
                error=str(exc),
            )


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def infer_question_focus(question: str) -> str:
    """Infer the best brief category for a short driver question."""

    normalised = question.lower()
    if _is_tyre_strategy_question(normalised):
        return "strategy"
    for category in ADVICE_CATEGORIES:
        for keyword in _FOCUS_KEYWORDS.get(category, ()):
            if keyword in normalised:
                return category
    return CATEGORY_ALL


def _load_memory_or_default(memory_file: str) -> RaceEngineerMemory:
    try:
        return load_race_engineer_memory(memory_file)
    except (OSError, ValueError, json.JSONDecodeError):
        return RaceEngineerMemory()


def _is_tyre_strategy_question(normalised_question: str) -> bool:
    return (
        any(term in normalised_question for term in _TYRE_STRATEGY_TERMS)
        and any(term in normalised_question for term in _TYRE_STRATEGY_DECISION_TERMS)
    )


def build_codex_conversation_prompt_package(
    question: str,
    *,
    brief: Dict[str, Any],
    focus: Optional[str] = None,
    memory: Optional[RaceEngineerMemory] = None,
) -> CodexConversationPromptPackage:
    """Build the compact context a Codex-backed answer provider should receive."""

    clean_question = _clean_question(question)
    selected_focus = focus or infer_question_focus(clean_question)
    selected_focus = normalise_agent_focus(selected_focus)
    context = _compact_brief_context(brief, selected_focus)
    context["driver_memory"] = race_engineer_memory_to_prompt_context(memory)
    context["answer_contract"] = _answer_contract(clean_question, memory=memory)
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    max_sentences, max_chars = race_engineer_memory_answer_limits(memory)
    messages = [
        {
            "role": "system",
            "content": (
                "You are the in-race Pits n' Giggles race engineer. "
                "Answer the driver's question from the supplied compact telemetry context only. "
                "Do not invent lap times, gaps, tyre state, damage, weather, strategy, or setup facts. "
                "Follow driver_memory style preferences unless safety-critical evidence requires otherwise. "
                "Answer in the same language as the driver's question unless driver_memory sets a language. "
                f"Use race-radio style: maximum {max_sentences} short sentences, "
                f"maximum {max_chars} characters, no markdown, no bullets. "
                "If evidence is missing, say that the call is not reliable yet."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Driver question: {clean_question}\n"
                f"Focus: {selected_focus}\n"
                f"Compact context JSON: {context_json}"
            ),
        },
    ]
    return CodexConversationPromptPackage(
        question=clean_question,
        focus=selected_focus,
        messages=messages,
        context=context,
    )


def build_http_conversation_headers(config: HttpConversationConfig) -> Dict[str, str]:
    """Build headers for an external conversation endpoint."""

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": config.user_agent,
    }
    if key := config.resolved_key():
        headers["Authorization"] = f"Bearer {key}"
    return headers


def parse_conversation_command(command: str) -> List[str]:
    """Split a configured conversation command without invoking a shell."""

    command = str(command or "").strip()
    if not command:
        return []
    return [part.strip("\"'") for part in shlex.split(command, posix=False) if part.strip("\"'")]


def _answer_from_advice(
    advice: Dict[str, Any],
    *,
    question: str = "",
    memory: Optional[RaceEngineerMemory] = None,
) -> str:
    if _answer_language(question, memory) == "ru":
        russian = _russian_answer_from_advice(advice)
        if russian:
            return _normalise_radio_answer(russian, memory=memory)

    voice = _safe_text(advice.get("voice_callout"))
    if voice:
        return _normalise_radio_answer(voice, memory=memory)
    message = _safe_text(advice.get("message"))
    if message:
        return _normalise_radio_answer(message, memory=memory)
    title = _safe_text(advice.get("title"))
    if title:
        return _normalise_radio_answer(title, memory=memory)
    return "No clear call right now."


def _answer_from_context(
    brief: Dict[str, Any],
    focus: str,
    *,
    question: str = "",
    memory: Optional[RaceEngineerMemory] = None,
) -> str:
    if _answer_language(question, memory) == "ru":
        return "Срочного сигнала нет. Держи ритм."

    categories = (
        brief.get("agent_context", {})
        if isinstance(brief.get("agent_context"), dict)
        else {}
    ).get("categories", {})
    context = categories.get(focus) if isinstance(categories, dict) else None
    if not isinstance(context, dict) and focus == CATEGORY_ALL and isinstance(categories, dict):
        context = _first_context_with_facts(categories)

    facts = context.get("facts") if isinstance(context, dict) else None
    if isinstance(facts, list) and facts:
        return _normalise_radio_answer(_safe_text(facts[0]) or "No urgent call right now.", memory=memory)
    return "No urgent call right now."


def _first_context_with_facts(categories: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for category in ADVICE_CATEGORIES:
        context = categories.get(category)
        if isinstance(context, dict) and context.get("facts"):
            return context
    return None


def _compact_brief_context(brief: Dict[str, Any], focus: str) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "session": _compact_session_context(brief),
        "reference_driver": _copy_dict(brief.get("reference_driver")),
        "nearby": _copy_dict(brief.get("nearby")),
        "advice": _compact_advice(brief.get("advice")),
        "review": _copy_dict(brief.get("advice_review")),
    }

    agent_context = _copy_dict(brief.get("agent_context"))
    categories = _copy_dict(agent_context.get("categories"))
    if focus != CATEGORY_ALL and focus in categories:
        categories = {focus: categories[focus]}
    context["agent_context"] = {
        "agent_order": agent_context.get("agent_order", []),
        "active_categories": agent_context.get("active_categories", []),
        "categories": categories,
        "review": agent_context.get("review", {}),
    }

    prompt_specs = _copy_dict(brief.get("agent_prompt_specs"))
    if focus != CATEGORY_ALL and focus in prompt_specs:
        prompt_specs = {focus: prompt_specs[focus]}
    elif focus == CATEGORY_ALL:
        active_categories = context["agent_context"].get("active_categories") or []
        selected = {
            category: prompt_specs[category]
            for category in active_categories
            if category in prompt_specs
        }
        prompt_specs = selected or prompt_specs
    context["prompt_specs"] = prompt_specs
    return context


def _answer_contract(question: str, *, memory: Optional[RaceEngineerMemory] = None) -> Dict[str, Any]:
    max_sentences, max_chars = race_engineer_memory_answer_limits(memory)
    language = _answer_language(question, memory)
    memory_context = race_engineer_memory_to_prompt_context(memory)
    return {
        "style": "race-radio",
        "language": language,
        "same_language_as_question": not bool(memory_context.get("language_preference")),
        "max_sentences": max_sentences,
        "max_chars": max_chars,
        "avoid_repeating": bool(memory_context.get("avoid_repeating")),
        "avoid_phrases": list(memory_context.get("avoid_phrases") or []),
        "no_markdown": True,
        "no_bullets": True,
    }


def _compact_session_context(brief: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "session_uid": brief.get("session_uid"),
        "event_type": brief.get("event_type"),
        "formula": brief.get("formula"),
        "circuit": brief.get("circuit"),
        "current_lap": brief.get("current_lap"),
        "total_laps": brief.get("total_laps"),
        "race_ended": brief.get("race_ended"),
        "focus": brief.get("focus"),
    }


def _compact_advice(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        result.append({
            "id": item.get("id"),
            "category": item.get("category"),
            "priority": item.get("priority"),
            "title": item.get("title"),
            "message": item.get("message"),
            "voice_callout": item.get("voice_callout"),
            "evidence": item.get("evidence", []),
            "metrics": item.get("metrics", {}),
        })
    return result


def _copy_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean_question(question: str) -> str:
    return str(question or "").replace("\r", " ").replace("\n", " ").strip()


def _safe_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None


def _question_language(question: str) -> str:
    return "ru" if any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in str(question or "")) else "en"


def _answer_language(question: str, memory: Optional[RaceEngineerMemory] = None) -> str:
    if memory is not None and memory.language_preference in {"ru", "en"}:
        return memory.language_preference
    return _question_language(question)


def _normalise_radio_answer(text: str, *, memory: Optional[RaceEngineerMemory] = None) -> str:
    max_sentences, max_chars = race_engineer_memory_answer_limits(memory)
    answer = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split()).strip()
    while answer.startswith(("-", "*", "•")):
        answer = answer[1:].strip()
    answer = _remove_avoided_phrases(answer, memory)
    answer = _limit_sentences(answer, max_sentences)
    if len(answer) > max_chars:
        answer = answer[:max_chars].rstrip(" ,;:")
        if "." in answer:
            answer = answer.rsplit(".", 1)[0].strip() or answer
        if not answer.endswith((".", "!", "?")):
            answer += "."
    return answer or "No clear call right now."


def _remove_avoided_phrases(text: str, memory: Optional[RaceEngineerMemory]) -> str:
    if memory is None or not memory.avoid_phrases:
        return text
    answer = text
    for phrase in memory.avoid_phrases:
        phrase_text = _safe_text(phrase)
        if phrase_text:
            answer = answer.replace(phrase_text, "").replace("  ", " ").strip(" ,;:-")
    return answer.strip()


def _limit_sentences(text: str, max_sentences: int) -> str:
    if max_sentences <= 0:
        return text
    sentence_end_count = 0
    for index, char in enumerate(text):
        if char in ".!?…":
            if (
                char == "."
                and index > 0
                and index + 1 < len(text)
                and text[index - 1].isdigit()
                and text[index + 1].isdigit()
            ):
                continue
            sentence_end_count += 1
            if sentence_end_count >= max_sentences:
                return text[:index + 1].strip()
    return text


def _russian_answer_from_advice(advice: Dict[str, Any]) -> Optional[str]:
    advice_id = _safe_text(advice.get("id")) or ""
    category = _safe_text(advice.get("category")) or ""
    metrics = _copy_dict(advice.get("metrics"))
    if advice_id.startswith("fuel-"):
        surplus = _num(metrics.get("surplus_laps"))
        if surplus is not None and surplus < -0.5:
            return f"Топливо критично: {_format_ru_lap_surplus(surplus)}. Лифт-энд-коуст сейчас."
        if surplus is not None and surplus < 0:
            return f"Топливо {_format_ru_lap_surplus(surplus)}. Начинай экономить."
        return "По топливу срочного сигнала нет."
    if advice_id == "pace-battle-attack-drs":
        return "Окно атаки: впереди в DRS. Готовь выход."
    if advice_id == "pace-battle-defend-drs":
        return "Защита: сзади в DRS и быстрее. Береги выход."
    if category == "pace":
        voice = _safe_text(advice.get("voice_callout"))
        return voice
    if category == "tyres":
        fastest_compound = _safe_text(metrics.get("fastest_live_compound"))
        recommended = _safe_text(metrics.get("recommended_next_compound"))
        if fastest_compound and recommended:
            return f"По темпу быстрее {fastest_compound}. На пит целевой {recommended}."
        if fastest_compound:
            return f"По темпу сейчас быстрее {fastest_compound}."
        worst = _safe_text(metrics.get("worst_tyre") or metrics.get("fastest_wear_rate_tyre"))
        wear = _num(metrics.get("worst_wear_pct") or metrics.get("current_wear_pct"))
        if worst and wear is not None:
            return f"Шины: {_label_ru_tyre(worst)} {wear:.0f} процентов. Береги выходы."
        return "По шинам срочного сигнала нет."
    if category == "ers":
        return "Смотри батарею и DRS. Используй ERS только под атаку или защиту."
    if category == "weather":
        return _safe_text(advice.get("voice_callout"))
    if category == "strategy":
        strategy_answer = _russian_strategy_answer_from_advice(advice_id, metrics)
        if strategy_answer:
            return strategy_answer
        return _safe_text(advice.get("voice_callout"))
    if category == "damage":
        return _safe_text(advice.get("voice_callout"))
    return None


def _format_ru_lap_surplus(value: float) -> str:
    prefix = "плюс" if value >= 0 else "минус"
    return f"{prefix} {abs(value):.1f} круга"


def _russian_strategy_answer_from_advice(
    advice_id: str,
    metrics: Dict[str, Any],
) -> Optional[str]:
    tyre_call = _safe_text(metrics.get("recommended_next_compound"))
    tyre_suffix = f" Ставим {tyre_call}." if tyre_call else ""
    if advice_id == "strategy-safety-car-box":
        return f"Safety Car окно. Можно пититься, если въезд открыт.{tyre_suffix}"
    if advice_id in {"strategy-pit-clear-air", "strategy-pit-window"}:
        return f"Пит-окно открыто.{tyre_suffix} Проверь трафик на выезде."
    if advice_id == "strategy-pit-traffic-risk":
        return f"Пит-окно открыто, но есть риск трафика.{tyre_suffix} Проверь gap перед въездом."
    if advice_id.startswith("strategy-tyre-stint-"):
        laps = _num(metrics.get("projected_laps_to_threshold"))
        threshold = _num(metrics.get("projected_threshold_pct"))
        if laps is not None and threshold is not None:
            return f"Шины дойдут до {threshold:.0f} процентов примерно через {laps:.1f} круга.{tyre_suffix}"
        return f"Планируй пит по шинам.{tyre_suffix}"
    if advice_id == "strategy-hold-for-rain":
        return "Дождь близко. Не спеши с сухим комплектом."
    if advice_id == "strategy-hold-for-rain-risk":
        return "Риск дождя высокий. Держим сухой стинт гибким."
    if advice_id == "strategy-drying-crossover":
        return "Трасса подсыхает. Не спеши с новым wet-комплектом."
    if advice_id == "strategy-cover-undercut":
        return "Сзади давление undercut. Готовься закрывать пит."
    if advice_id == "strategy-undercut-threat":
        return "Undercut угроза сзади. Следи за pit delta."
    if advice_id == "strategy-undercut-opportunity":
        return "Есть окно undercut впереди. Можно готовить ранний пит."
    return None


def _label_ru_tyre(name: str) -> str:
    return {
        "front-left": "передняя левая",
        "front-right": "передняя правая",
        "rear-left": "задняя левая",
        "rear-right": "задняя правая",
    }.get(name, name)


def _empty_question_answer(*, source: str) -> RaceEngineerAnswer:
    return RaceEngineerAnswer(
        ok=False,
        question="",
        answer="I did not catch the question.",
        source=source,
        error="empty question",
    )


def _missing_telemetry_answer(question: str, *, source: str) -> RaceEngineerAnswer:
    return RaceEngineerAnswer(
        ok=False,
        question=question,
        answer="I do not have live telemetry yet.",
        source=source,
        error="missing telemetry",
    )


def _answer_from_http_conversation_response(
    response: HttpConversationResponse,
    *,
    question: str,
    focus: str,
    source: str,
    duration_ms: float,
    memory: Optional[RaceEngineerMemory] = None,
) -> RaceEngineerAnswer:
    if response.status_code not in {200, 201}:
        return RaceEngineerAnswer(
            ok=False,
            question=question,
            answer="External race engineer did not answer.",
            source=source,
            focus=focus,
            error=_format_http_conversation_error(response),
            metrics={
                "duration_ms": duration_ms,
                "http_status_code": response.status_code,
            },
        )

    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return RaceEngineerAnswer(
            ok=False,
            question=question,
            answer="External race engineer returned an unreadable answer.",
            source=source,
            focus=focus,
            error=f"conversation response was not valid JSON: {exc}",
            metrics={
                "duration_ms": duration_ms,
                "http_status_code": response.status_code,
            },
        )

    answer_text = _external_answer_text(payload)
    if not answer_text:
        return RaceEngineerAnswer(
            ok=False,
            question=question,
            answer="External race engineer returned no answer.",
            source=source,
            focus=focus,
            error="conversation response did not include answer text",
            metrics={
                "duration_ms": duration_ms,
                "http_status_code": response.status_code,
            },
        )

    answer = _normalise_radio_answer(answer_text, memory=memory)
    payload_metrics = payload.get("metrics") if isinstance(payload, dict) else None
    return RaceEngineerAnswer(
        ok=True,
        question=question,
        answer=answer,
        source=source,
        focus=_safe_text(payload.get("focus")) or focus if isinstance(payload, dict) else focus,
        metrics={
            **(payload_metrics if isinstance(payload_metrics, dict) else {}),
            "duration_ms": duration_ms,
            "http_status_code": response.status_code,
        },
    )


def _answer_from_command_conversation_response(
    response: CommandConversationResponse,
    *,
    question: str,
    focus: str,
    source: str,
    duration_ms: float,
    memory: Optional[RaceEngineerMemory] = None,
) -> RaceEngineerAnswer:
    if response.timed_out:
        return RaceEngineerAnswer(
            ok=False,
            question=question,
            answer="Codex CLI race engineer timed out.",
            source=source,
            focus=focus,
            error="conversation command timed out",
            metrics={
                "duration_ms": duration_ms,
                "exit_code": response.exit_code,
            },
        )
    if response.exit_code != 0:
        return RaceEngineerAnswer(
            ok=False,
            question=question,
            answer="Codex CLI race engineer did not answer.",
            source=source,
            focus=focus,
            error=_format_command_conversation_error(response),
            metrics={
                "duration_ms": duration_ms,
                "exit_code": response.exit_code,
            },
        )

    text = response.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return RaceEngineerAnswer(
            ok=False,
            question=question,
            answer="Codex CLI race engineer returned no answer.",
            source=source,
            focus=focus,
            error="conversation command returned empty stdout",
            metrics={
                "duration_ms": duration_ms,
                "exit_code": response.exit_code,
            },
        )

    payload_metrics: Dict[str, Any] = {}
    answer = _normalise_radio_answer(text, memory=memory)
    answer_focus = focus
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        parsed_answer = _external_answer_text(payload)
        if not parsed_answer:
            return RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="Codex CLI race engineer returned no answer.",
                source=source,
                focus=focus,
                error="conversation command JSON did not include answer text",
                metrics={
                    "duration_ms": duration_ms,
                    "exit_code": response.exit_code,
                },
            )
        answer = _normalise_radio_answer(parsed_answer, memory=memory)
        payload_focus = _safe_text(payload.get("focus"))
        if payload_focus:
            answer_focus = payload_focus
        metrics = payload.get("metrics")
        if isinstance(metrics, dict):
            payload_metrics = metrics

    return RaceEngineerAnswer(
        ok=True,
        question=question,
        answer=answer,
        source=source,
        focus=answer_focus,
        metrics={
            **payload_metrics,
            "duration_ms": duration_ms,
            "exit_code": response.exit_code,
        },
    )


def _external_answer_text(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("answer", "text", "voice_callout"):
        if text := _safe_text(payload.get(key)):
            return text

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and (text := _safe_text(message.get("content"))):
                return text
            if text := _safe_text(first.get("text")):
                return text
    return None


def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _format_http_conversation_error(response: HttpConversationResponse) -> str:
    detail = ""
    if response.error_text:
        detail = f": {response.error_text[:200]}"
    return f"conversation endpoint returned HTTP {response.status_code}{detail}"


def _format_command_conversation_error(response: CommandConversationResponse) -> str:
    detail = response.stderr.decode("utf-8", errors="replace").strip()
    if detail:
        return f"conversation command exited with {response.exit_code}: {detail[:200]}"
    return f"conversation command exited with {response.exit_code}"


def _post_conversation_with_urllib(
    *,
    url: str,
    headers: Dict[str, str],
    body: bytes,
    timeout_seconds: float,
) -> HttpConversationResponse:
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read()
            return HttpConversationResponse(
                status_code=int(response.getcode()),
                body=response_body,
            )
    except urllib.error.HTTPError as exc:
        response_body = exc.read()
        return HttpConversationResponse(
            status_code=int(exc.code),
            body=response_body,
            error_text=response_body.decode("utf-8", errors="replace"),
        )


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)
