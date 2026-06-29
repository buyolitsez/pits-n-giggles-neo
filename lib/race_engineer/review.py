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

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List

from .agent_prompts import ADVICE_CATEGORIES

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

VALID_PRIORITIES = {"critical", "warning", "advisory", "info"}
VALID_ADVICE_CATEGORIES = set(ADVICE_CATEGORIES)
REQUIRED_ADVICE_FIELDS = (
    "id",
    "category",
    "priority",
    "title",
    "message",
    "voice_callout",
    "cooldown_key",
    "evidence",
    "metrics",
)

MAX_MESSAGE_LEN = 360
MAX_VOICE_CALLOUT_LEN = 180
MAX_EVIDENCE_ITEMS = 12
MAX_EVIDENCE_ITEM_LEN = 160
RAW_MILLISECONDS_RE = re.compile(r"\bms\b|\bmilliseconds?\b", re.IGNORECASE)
ADVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,80}$")
COOLDOWN_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_:.-]{1,120}$")

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdviceReviewIssue:
    """One validation issue found in an advice item."""

    advice_id: str
    code: str
    message: str
    severity: str = "error"

    def as_dict(self) -> Dict[str, str]:
        return {
            "advice_id": self.advice_id,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class AdviceReviewResult:
    """Review result for a list of candidate advice items."""

    accepted_advice: List[Dict[str, Any]]
    rejected_advice_ids: List[str]
    issues: List[AdviceReviewIssue]

    @property
    def ok(self) -> bool:
        return not self.rejected_advice_ids

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "accepted_count": len(self.accepted_advice),
            "rejected_count": len(self.rejected_advice_ids),
            "rejected_advice_ids": list(self.rejected_advice_ids),
            "issues": [issue.as_dict() for issue in self.issues],
        }


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def review_race_engineer_advice(advice_items: Iterable[Dict[str, Any]]) -> AdviceReviewResult:
    """Validate advice items before they are exposed to MCP or voice output."""

    accepted_advice: List[Dict[str, Any]] = []
    rejected_advice_ids: List[str] = []
    issues: List[AdviceReviewIssue] = []

    for index, advice in enumerate(advice_items):
        item_issues = _review_one_advice(advice, index)
        issues.extend(item_issues)
        advice_id = _advice_id(advice, index)
        if item_issues:
            rejected_advice_ids.append(advice_id)
        else:
            accepted_advice.append(advice)

    return AdviceReviewResult(
        accepted_advice=accepted_advice,
        rejected_advice_ids=rejected_advice_ids,
        issues=issues,
    )


def _review_one_advice(advice: Dict[str, Any], index: int) -> List[AdviceReviewIssue]:
    advice_id = _advice_id(advice, index)
    issues: List[AdviceReviewIssue] = []

    if not isinstance(advice, dict):
        return [
            AdviceReviewIssue(
                advice_id=advice_id,
                code="invalid-advice-type",
                message="Advice item must be an object.",
            )
        ]

    for field in REQUIRED_ADVICE_FIELDS:
        if field not in advice:
            issues.append(_issue(advice_id, "missing-field", f"Missing required field: {field}."))

    if issues:
        return issues

    _validate_non_empty_string(issues, advice_id, advice, "id")
    _validate_non_empty_string(issues, advice_id, advice, "title")
    _validate_non_empty_string(issues, advice_id, advice, "message")
    _validate_non_empty_string(issues, advice_id, advice, "voice_callout")
    _validate_non_empty_string(issues, advice_id, advice, "cooldown_key")

    item_id = advice.get("id")
    if isinstance(item_id, str) and not ADVICE_ID_RE.fullmatch(item_id):
        issues.append(_issue(advice_id, "invalid-id", "Advice id must be short, lowercase, and stable."))

    cooldown_key = advice.get("cooldown_key")
    if isinstance(cooldown_key, str) and not COOLDOWN_KEY_RE.fullmatch(cooldown_key):
        issues.append(_issue(advice_id, "invalid-cooldown-key", "Cooldown key contains unsupported characters."))

    category = advice.get("category")
    if category not in VALID_ADVICE_CATEGORIES:
        issues.append(_issue(advice_id, "invalid-category", f"Invalid advice category: {category}."))

    priority = advice.get("priority")
    if priority not in VALID_PRIORITIES:
        issues.append(_issue(advice_id, "invalid-priority", f"Invalid priority: {priority}."))

    evidence = advice.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
        issues.append(_issue(advice_id, "missing-evidence", "Advice must include at least one non-empty evidence string."))
    elif len(evidence) > MAX_EVIDENCE_ITEMS:
        issues.append(_issue(advice_id, "too-much-evidence", "Advice has too many evidence items for a concise call."))
    else:
        for evidence_item in evidence:
            if len(evidence_item) > MAX_EVIDENCE_ITEM_LEN:
                issues.append(_issue(advice_id, "evidence-too-long", "Evidence item is too long."))
                break

    if not isinstance(advice.get("metrics"), dict):
        issues.append(_issue(advice_id, "invalid-metrics", "Advice metrics must be an object."))

    message = advice.get("message")
    voice_callout = advice.get("voice_callout")
    if isinstance(message, str) and len(message) > MAX_MESSAGE_LEN:
        issues.append(_issue(advice_id, "message-too-long", "Advice message is too long for race engineer use."))
    if isinstance(voice_callout, str) and len(voice_callout) > MAX_VOICE_CALLOUT_LEN:
        issues.append(_issue(advice_id, "voice-too-long", "Voice callout is too long for in-race delivery."))
    if isinstance(voice_callout, str) and "\n" in voice_callout:
        issues.append(_issue(advice_id, "voice-newline", "Voice callout must be a single line."))
    if isinstance(message, str) and "\n" in message:
        issues.append(_issue(advice_id, "message-newline", "Advice message must be a single line."))

    for field_name in ("message", "voice_callout"):
        value = advice.get(field_name)
        if isinstance(value, str) and RAW_MILLISECONDS_RE.search(value):
            issues.append(_issue(
                advice_id,
                "raw-milliseconds",
                f"{field_name} must use driver-friendly seconds or lap-time strings, not raw milliseconds.",
            ))

    return issues


def _validate_non_empty_string(
    issues: List[AdviceReviewIssue],
    advice_id: str,
    advice: Dict[str, Any],
    field: str,
) -> None:
    value = advice.get(field)
    if not isinstance(value, str) or not value.strip():
        issues.append(_issue(advice_id, "empty-string", f"{field} must be a non-empty string."))


def _issue(advice_id: str, code: str, message: str) -> AdviceReviewIssue:
    return AdviceReviewIssue(advice_id=advice_id, code=code, message=message)


def _advice_id(advice: Any, index: int) -> str:
    if isinstance(advice, dict):
        advice_id = advice.get("id")
        if isinstance(advice_id, str) and advice_id.strip():
            return advice_id
    return f"advice[{index}]"
