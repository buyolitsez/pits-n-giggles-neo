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
import time
from typing import Any, Dict, List, Optional

from .agent_prompts import ADVICE_CATEGORIES
from .brief import build_race_engineer_brief
from .history import RaceEngineerHistory
from .review import review_race_engineer_advice

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

PRIORITY_RANK = {
    "critical": 0,
    "warning": 1,
    "advisory": 2,
    "info": 3,
}

_CATEGORY_ALL = "all"
_VALID_CATEGORIES = {_CATEGORY_ALL, *ADVICE_CATEGORIES}
_LAP_PACE_ADVICE_IDS = {
    "pace-catching-ahead",
    "pace-losing-ahead",
    "pace-threat-behind",
}
_LIVE_BATTLE_PACE_ADVICE_IDS = {
    "pace-battle-attack-drs",
    "pace-battle-defend-drs",
}

# -------------------------------------- CLASSES -----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RaceEngineerAnnouncement:
    """A single message selected for speech or dry-run logging."""

    text: str
    priority: str
    category: str
    cooldown_key: str
    advice_id: str
    evidence: List[str]
    metrics: Dict[str, Any]
    session_generation: int = 0


class RaceEngineerAnnouncer:
    """Select speech-worthy race engineer messages from telemetry snapshots."""

    def __init__(
        self,
        *,
        min_priority: str = "warning",
        cooldown_seconds: int = 20,
        max_items: int = 5,
        history: Optional[RaceEngineerHistory] = None,
    ) -> None:
        self.min_priority = _normalise_priority(min_priority)
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.max_items = max(1, min(max_items, 10))
        self.history = history
        self._last_announced_at: Dict[str, float] = {}

    def process_snapshot(
        self,
        telemetry_update: Optional[Dict[str, Any]],
        *,
        now: Optional[float] = None,
        focus: str = "all",
    ) -> List[RaceEngineerAnnouncement]:
        """Return announcements selected from one telemetry snapshot."""
        if now is None:
            now = time.time()

        brief = build_race_engineer_brief(
            telemetry_update=telemetry_update,
            base_rsp={"available": False, "connected": True, "ok": False},
            focus=focus,
            max_items=self.max_items,
        )
        if not brief.get("ok"):
            return []

        advice_items = list(brief.get("advice", []))
        history_advice = self.history.update(telemetry_update) if self.history else []
        suppressed_cooldown_keys: List[str] = []
        if self.history:
            suppressed_ids = set(_LAP_PACE_ADVICE_IDS)
            if history_advice:
                suppressed_ids.update(_LIVE_BATTLE_PACE_ADVICE_IDS)
                suppressed_cooldown_keys = [
                    str(advice.get("cooldown_key"))
                    for advice in advice_items
                    if advice.get("id") in _LIVE_BATTLE_PACE_ADVICE_IDS and advice.get("cooldown_key")
                ]
            advice_items = [
                advice
                for advice in advice_items
                if advice.get("id") not in suppressed_ids
            ]
            for cooldown_key in suppressed_cooldown_keys:
                self._last_announced_at[cooldown_key] = now
        if history_advice:
            advice_items.extend(history_advice)
        advice_items = review_race_engineer_advice(advice_items).accepted_advice
        advice_items = _filter_and_sort_advice(advice_items, focus, self.max_items)

        announcements: List[RaceEngineerAnnouncement] = []
        for advice in advice_items:
            if not _is_priority_allowed(advice.get("priority"), self.min_priority):
                continue
            cooldown_key = advice["cooldown_key"]
            if self._is_in_cooldown(cooldown_key, now):
                continue
            announcements.append(_announcement_from_advice(advice))
            self._last_announced_at[cooldown_key] = now

        return announcements

    def process_advice_items(
        self,
        advice_items: List[Dict[str, Any]],
        *,
        now: Optional[float] = None,
        focus: str = "all",
    ) -> List[RaceEngineerAnnouncement]:
        """Return announcements selected from pre-built advice items."""
        if now is None:
            now = time.time()

        advice_items = review_race_engineer_advice(advice_items).accepted_advice
        advice_items = _filter_and_sort_advice(advice_items, focus, self.max_items)

        announcements: List[RaceEngineerAnnouncement] = []
        for advice in advice_items:
            if not _is_priority_allowed(advice.get("priority"), self.min_priority):
                continue
            cooldown_key = advice["cooldown_key"]
            if self._is_in_cooldown(cooldown_key, now):
                continue
            announcements.append(_announcement_from_advice(advice))
            self._last_announced_at[cooldown_key] = now

        return announcements

    def clear(self) -> None:
        """Clear cooldown history."""
        self._last_announced_at.clear()
        if self.history:
            self.history.clear()

    def _is_in_cooldown(self, cooldown_key: str, now: float) -> bool:
        last = self._last_announced_at.get(cooldown_key)
        if last is None:
            return False
        return (now - last) < self.cooldown_seconds


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------

def _announcement_from_advice(advice: Dict[str, Any]) -> RaceEngineerAnnouncement:
    return RaceEngineerAnnouncement(
        text=advice["voice_callout"],
        priority=advice["priority"],
        category=advice["category"],
        cooldown_key=advice["cooldown_key"],
        advice_id=advice["id"],
        evidence=list(advice.get("evidence", [])),
        metrics=dict(advice.get("metrics", {})),
    )


def _normalise_priority(priority: str) -> str:
    priority = (priority or "warning").strip().lower()
    if priority not in PRIORITY_RANK:
        return "warning"
    return priority


def _is_priority_allowed(priority: Optional[str], min_priority: str) -> bool:
    if priority not in PRIORITY_RANK:
        return False
    return PRIORITY_RANK[priority] <= PRIORITY_RANK[min_priority]


def _normalise_focus(focus: str) -> str:
    focus = (focus or _CATEGORY_ALL).strip().lower().replace("-", "_")
    if focus not in _VALID_CATEGORIES:
        return _CATEGORY_ALL
    return focus


def _filter_and_sort_advice(
    advice: List[Dict[str, Any]],
    focus: str,
    max_items: int,
) -> List[Dict[str, Any]]:
    focus = _normalise_focus(focus)
    if focus != _CATEGORY_ALL:
        advice = [item for item in advice if item.get("category") == focus]
    return sorted(
        advice,
        key=lambda item: (PRIORITY_RANK.get(item.get("priority"), 99), item.get("id", "")),
    )[:max_items]
