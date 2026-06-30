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

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from lib.file_path import resolve_user_file

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_RACE_ENGINEER_MEMORY_FILE = "race_engineer_memory.json"
RACE_ENGINEER_MEMORY_SCHEMA = "pits-n-giggles.race-engineer.memory.v1"

_MAX_STYLE_NOTES = 24
_MAX_AVOID_PHRASES = 24
_MAX_FEEDBACK_LOG = 50
_DEFAULT_MAX_SENTENCES = 2
_DEFAULT_MAX_CHARS = 180
_CONCISE_MAX_SENTENCES = 1
_CONCISE_MAX_CHARS = 110
_VERBOSITIES = {"concise", "normal", "detailed"}
_LANGUAGES = {"", "ru", "en"}

_FEEDBACK_TRIGGERS = (
    "запомни",
    "не говори",
    "не надо",
    "не нужно",
    "не повторяй",
    "лучше говори",
    "лучше отвечай",
    "по русски",
    "по-русски",
    "на русском",
    "на английском",
    "короче",
    "кратко",
    "меньше информации",
    "слишком много",
    "remember",
    "do not say",
    "don't say",
    "dont say",
    "do not repeat",
    "don't repeat",
    "dont repeat",
    "too much",
    "less information",
    "shorter",
    "more concise",
    "be concise",
    "in english",
    "speak english",
    "say instead",
    "answer instead",
)

_CONCISE_TERMS = (
    "короче",
    "кратко",
    "меньше информации",
    "не так много",
    "слишком много",
    "много информации",
    "shorter",
    "too much",
    "less information",
    "more concise",
    "be concise",
)

_DETAIL_TERMS = (
    "подробнее",
    "больше деталей",
    "больше информации",
    "more detail",
    "more context",
)

_NO_REPEAT_TERMS = (
    "не повторяй",
    "не надо повторять",
    "не нужно повторять",
    "не повторять",
    "do not repeat",
    "don't repeat",
    "dont repeat",
)

_RUSSIAN_TERMS = (
    "по русски",
    "по-русски",
    "на русском",
    "говори рус",
    "отвечай рус",
)

_ENGLISH_TERMS = (
    "in english",
    "speak english",
    "answer english",
    "говори по английски",
    "говори по-английски",
    "на английском",
)

_AVOID_PHRASE_PATTERNS = (
    re.compile(r"не\s+(?:говори|используй)\s+[\"'«](.*?)[\"'»]", re.IGNORECASE),
    re.compile(r"(?:do not|don't|dont)\s+(?:say|use)\s+[\"'](.*?)[\"']", re.IGNORECASE),
)

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RaceEngineerMemory:
    """Editable long-lived driver preferences for the race engineer."""

    schema: str = RACE_ENGINEER_MEMORY_SCHEMA
    version: int = 1
    language_preference: str = ""
    verbosity: str = "normal"
    max_sentences: int = _DEFAULT_MAX_SENTENCES
    max_chars: int = _DEFAULT_MAX_CHARS
    avoid_repeating: bool = False
    avoid_phrases: Tuple[str, ...] = ()
    style_notes: Tuple[str, ...] = ()
    updated_at: str = ""
    feedback_log: Tuple[Dict[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Return memory as editable JSON data."""

        return {
            "schema": self.schema,
            "version": self.version,
            "language_preference": self.language_preference,
            "verbosity": self.verbosity,
            "max_sentences": self.max_sentences,
            "max_chars": self.max_chars,
            "avoid_repeating": self.avoid_repeating,
            "avoid_phrases": list(self.avoid_phrases),
            "style_notes": list(self.style_notes),
            "updated_at": self.updated_at,
            "feedback_log": [dict(item) for item in self.feedback_log],
        }


@dataclass(frozen=True, slots=True)
class RaceEngineerMemoryUpdate:
    """Result of applying a spoken calibration request."""

    applied: bool
    memory: RaceEngineerMemory
    acknowledgement: str = ""
    rules: Tuple[str, ...] = ()


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def default_race_engineer_memory_path() -> str:
    """Return the default editable memory JSON path."""

    return resolve_user_file(DEFAULT_RACE_ENGINEER_MEMORY_FILE)


def load_race_engineer_memory(path: Optional[str] = None) -> RaceEngineerMemory:
    """Load editable race engineer memory, falling back to defaults if absent."""

    path = str(path or "").strip() or default_race_engineer_memory_path()
    if not Path(path).exists():
        return RaceEngineerMemory()
    with Path(path).open("r", encoding="utf-8") as file_obj:
        raw = json.load(file_obj)
    return race_engineer_memory_from_dict(raw)


def save_race_engineer_memory(memory: RaceEngineerMemory, path: Optional[str] = None) -> str:
    """Persist editable race engineer memory and return the written path."""

    path = str(path or "").strip() or default_race_engineer_memory_path()
    target = Path(path)
    if target.parent != Path("."):
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file_obj:
        json.dump(memory.to_dict(), file_obj, ensure_ascii=False, indent=4)
    return str(target)


def save_race_engineer_memory_template(path: Optional[str] = None, *, overwrite: bool = False) -> str:
    """Create an editable memory JSON template."""

    path = str(path or "").strip() or default_race_engineer_memory_path()
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Race engineer memory file already exists: {path}")
    return save_race_engineer_memory(RaceEngineerMemory(), path)


def race_engineer_memory_from_dict(value: Any) -> RaceEngineerMemory:
    """Validate and normalize an editable memory dictionary."""

    if not isinstance(value, dict):
        raise ValueError("Race engineer memory JSON must be an object.")
    schema = _text(value.get("schema")) or RACE_ENGINEER_MEMORY_SCHEMA
    if schema != RACE_ENGINEER_MEMORY_SCHEMA:
        raise ValueError(f"Unsupported race engineer memory schema: {schema}")
    language = _choice(_text(value.get("language_preference")).lower(), _LANGUAGES, "")
    verbosity = _choice(_text(value.get("verbosity")).lower(), _VERBOSITIES, "normal")
    max_sentences = _bounded_int(value.get("max_sentences"), 1, 3, _DEFAULT_MAX_SENTENCES)
    max_chars = _bounded_int(value.get("max_chars"), 60, 260, _DEFAULT_MAX_CHARS)
    if verbosity == "concise":
        max_sentences = min(max_sentences, _CONCISE_MAX_SENTENCES)
        max_chars = min(max_chars, _CONCISE_MAX_CHARS)
    return RaceEngineerMemory(
        schema=schema,
        version=_bounded_int(value.get("version"), 1, 1, 1),
        language_preference=language,
        verbosity=verbosity,
        max_sentences=max_sentences,
        max_chars=max_chars,
        avoid_repeating=_bool(value.get("avoid_repeating"), False),
        avoid_phrases=tuple(_text_list(value.get("avoid_phrases"), _MAX_AVOID_PHRASES)),
        style_notes=tuple(_text_list(value.get("style_notes"), _MAX_STYLE_NOTES)),
        updated_at=_text(value.get("updated_at")),
        feedback_log=tuple(_feedback_log(value.get("feedback_log"))),
    )


def apply_race_engineer_memory_feedback(
    memory: RaceEngineerMemory,
    feedback_text: str,
) -> RaceEngineerMemoryUpdate:
    """Apply a spoken calibration command if the text looks like driver feedback."""

    text = _text(feedback_text)
    if not text or not _looks_like_feedback(text):
        return RaceEngineerMemoryUpdate(applied=False, memory=memory)

    lowered = text.lower()
    rules: List[str] = []
    next_memory = memory

    if _contains_any(lowered, _CONCISE_TERMS):
        next_memory = replace(
            next_memory,
            verbosity="concise",
            max_sentences=_CONCISE_MAX_SENTENCES,
            max_chars=_CONCISE_MAX_CHARS,
            avoid_repeating=True,
        )
        rules.append("shorter_answers")

    if _contains_any(lowered, _DETAIL_TERMS):
        next_memory = replace(
            next_memory,
            verbosity="normal",
            max_sentences=_DEFAULT_MAX_SENTENCES,
            max_chars=_DEFAULT_MAX_CHARS,
        )
        rules.append("allow_more_context")

    if _contains_any(lowered, _NO_REPEAT_TERMS):
        next_memory = replace(next_memory, avoid_repeating=True)
        rules.append("avoid_repeating")

    if _contains_any(lowered, _RUSSIAN_TERMS):
        next_memory = replace(next_memory, language_preference="ru")
        rules.append("language_ru")
    elif _contains_any(lowered, _ENGLISH_TERMS):
        next_memory = replace(next_memory, language_preference="en")
        rules.append("language_en")

    avoid_phrases = list(next_memory.avoid_phrases)
    for phrase in _extract_avoid_phrases(text):
        if phrase not in avoid_phrases:
            avoid_phrases.append(phrase)
            rules.append("avoid_phrase")
    avoid_phrases = avoid_phrases[-_MAX_AVOID_PHRASES:]
    next_memory = replace(next_memory, avoid_phrases=tuple(avoid_phrases))

    style_notes = _append_unique(
        list(next_memory.style_notes),
        _style_note_from_feedback(text, rules),
        limit=_MAX_STYLE_NOTES,
    )
    feedback_log = _append_feedback_log(next_memory.feedback_log, text, rules)
    next_memory = replace(
        next_memory,
        style_notes=tuple(style_notes),
        updated_at=_now_utc(),
        feedback_log=tuple(feedback_log),
    )

    acknowledgement = _acknowledgement_for_feedback(text, rules)
    return RaceEngineerMemoryUpdate(
        applied=True,
        memory=next_memory,
        acknowledgement=acknowledgement,
        rules=tuple(_dedupe(rules) or ["style_note"]),
    )


def race_engineer_memory_answer_limits(memory: Optional[RaceEngineerMemory]) -> tuple[int, int]:
    """Return max sentences and chars for radio answers under current memory."""

    if memory is None:
        return _DEFAULT_MAX_SENTENCES, _DEFAULT_MAX_CHARS
    return (
        _bounded_int(memory.max_sentences, 1, 3, _DEFAULT_MAX_SENTENCES),
        _bounded_int(memory.max_chars, 60, 260, _DEFAULT_MAX_CHARS),
    )


def race_engineer_memory_to_prompt_context(memory: Optional[RaceEngineerMemory]) -> Dict[str, Any]:
    """Return compact memory context for an answer provider."""

    memory = memory or RaceEngineerMemory()
    return {
        "schema": memory.schema,
        "language_preference": memory.language_preference,
        "verbosity": memory.verbosity,
        "max_sentences": memory.max_sentences,
        "max_chars": memory.max_chars,
        "avoid_repeating": memory.avoid_repeating,
        "avoid_phrases": list(memory.avoid_phrases),
        "style_notes": list(memory.style_notes),
        "updated_at": memory.updated_at,
    }


def race_engineer_memory_has_preferences(memory: Optional[RaceEngineerMemory]) -> bool:
    """Return True if memory carries non-default driver preferences."""

    if memory is None:
        return False
    return memory != RaceEngineerMemory()


def _looks_like_feedback(text: str) -> bool:
    lowered = text.lower()
    return _contains_any(lowered, _FEEDBACK_TRIGGERS)


def _style_note_from_feedback(text: str, rules: List[str]) -> str:
    if rules:
        return _text(text)[:180]
    return f"Driver feedback: {_text(text)[:160]}"


def _acknowledgement_for_feedback(text: str, rules: List[str]) -> str:
    language = "ru" if _looks_russian(text) else "en"
    rule_set = set(rules)
    if language == "ru":
        if "shorter_answers" in rule_set:
            return "Запомнил. Дальше короче."
        if "avoid_repeating" in rule_set:
            return "Запомнил. Не буду повторяться."
        if "language_ru" in rule_set:
            return "Запомнил. Буду отвечать по-русски."
        if "language_en" in rule_set:
            return "Copy. I will answer in English."
        return "Запомнил. Подстроюсь."
    if "shorter_answers" in rule_set:
        return "Copy. Shorter from now on."
    if "avoid_repeating" in rule_set:
        return "Copy. I will avoid repeats."
    if "language_ru" in rule_set:
        return "Запомнил. Буду отвечать по-русски."
    if "language_en" in rule_set:
        return "Copy. I will answer in English."
    return "Copy. I will adjust."


def _extract_avoid_phrases(text: str) -> List[str]:
    result: List[str] = []
    for pattern in _AVOID_PHRASE_PATTERNS:
        for match in pattern.finditer(text):
            phrase = _text(match.group(1))[:80]
            if phrase:
                result.append(phrase)
    return _dedupe(result)


def _append_feedback_log(
    current: Tuple[Dict[str, str], ...],
    text: str,
    rules: List[str],
) -> List[Dict[str, str]]:
    log = [dict(item) for item in current if isinstance(item, dict)]
    log.append({
        "at": _now_utc(),
        "feedback": _text(text)[:220],
        "rules": ",".join(_dedupe(rules) or ["style_note"]),
    })
    return log[-_MAX_FEEDBACK_LOG:]


def _feedback_log(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        feedback = _text(item.get("feedback"))[:220]
        if not feedback:
            continue
        result.append({
            "at": _text(item.get("at"))[:40],
            "feedback": feedback,
            "rules": _text(item.get("rules"))[:120],
        })
    return result[-_MAX_FEEDBACK_LOG:]


def _append_unique(values: List[str], value: str, *, limit: int) -> List[str]:
    value = _text(value)
    if not value:
        return values[-limit:]
    values = [item for item in values if item != value]
    values.append(value)
    return values[-limit:]


def _text_list(value: Any, limit: int) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        text = _text(item)[:180]
        if text and text not in result:
            result.append(text)
    return result[-limit:]


def _text(value: Any) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _choice(value: str, choices: set[str], default: str) -> str:
    return value if value in choices else default


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalised in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _contains_any(text: str, terms: Tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _looks_russian(text: str) -> bool:
    return any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in str(text or ""))


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
