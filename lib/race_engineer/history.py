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

from collections import defaultdict, deque
from dataclasses import dataclass
import time
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

_MIN_SIGNIFICANT_LAP_DELTA_MS = 250.0
_MIN_THREAT_LAP_DELTA_MS = 500.0
_BATTLE_GAP_WINDOW_MS = 5000.0
_MIN_GAP_TREND_MS = 100.0
_ROLLING_PACE_LAPS = 3

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LapRecord:
    """One completed lap extracted from a race-table snapshot."""

    driver_index: int
    driver_name: str
    lap_number: int
    lap_time_ms: float
    position: Optional[int]
    gap_to_front_ms: Optional[float]
    car_ahead_index: Optional[int]
    timestamp: float


class RaceEngineerHistory:
    """Rolling per-driver lap memory for lap-to-lap race engineer calls."""

    def __init__(
        self,
        *,
        max_laps_per_driver: int = 20,
        emit_on_first_update: bool = False,
    ) -> None:
        self.max_laps_per_driver = max(2, max_laps_per_driver)
        self.emit_on_first_update = emit_on_first_update
        self._records_by_driver: Dict[int, Deque[LapRecord]] = defaultdict(
            lambda: deque(maxlen=self.max_laps_per_driver)
        )
        self._seen_laps: Set[Tuple[int, int]] = set()
        self._has_seeded = False
        self._session_uid: Optional[str] = None

    def update(self, telemetry_update: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Record completed laps and return any new pace-trend advice."""

        if not isinstance(telemetry_update, dict):
            return []

        session_uid = _session_uid(telemetry_update)
        if session_uid != self._session_uid:
            self._clear_records()
            self._session_uid = session_uid

        rows = _list_of_dicts(telemetry_update.get("table-entries", []))
        if not rows:
            return []

        timestamp = _num(telemetry_update.get("timestamp")) or time.time()
        nearby_by_driver = _nearby_indices_by_driver(rows)
        new_records = self._extract_new_records(rows, nearby_by_driver, timestamp)
        if not self._has_seeded and not self.emit_on_first_update:
            self._has_seeded = True
            for record in new_records:
                self._append_record(record)
            return []

        self._has_seeded = True
        for record in new_records:
            self._append_record(record)

        ref_row = _get_ref_row(telemetry_update)
        if not ref_row:
            return []

        ref_index = _driver_index(ref_row)
        if ref_index is None:
            return []

        player_records = [record for record in new_records if record.driver_index == ref_index]
        if not player_records:
            return []

        return self._build_pace_trends(player_records[-1], rows, nearby_by_driver)

    def clear(self) -> None:
        """Clear all rolling history."""

        self._records_by_driver.clear()
        self._seen_laps.clear()
        self._has_seeded = False
        self._session_uid = None

    def latest_laps(self, driver_index: int, count: int = 3) -> List[LapRecord]:
        """Return recent completed laps for one driver."""

        records = list(self._records_by_driver.get(driver_index, []))
        return records[-count:]

    def _extract_new_records(
        self,
        rows: List[Dict[str, Any]],
        nearby_by_driver: Dict[int, Dict[str, Optional[int]]],
        timestamp: float,
    ) -> List[LapRecord]:
        records: List[LapRecord] = []
        for row in rows:
            record = _lap_record_from_row(row, nearby_by_driver, timestamp)
            if not record:
                continue
            key = (record.driver_index, record.lap_number)
            if key in self._seen_laps:
                continue
            self._seen_laps.add(key)
            records.append(record)
        return records

    def _append_record(self, record: LapRecord) -> None:
        self._records_by_driver[record.driver_index].append(record)

    def _clear_records(self) -> None:
        self._records_by_driver.clear()
        self._seen_laps.clear()
        self._has_seeded = False

    def _build_pace_trends(
        self,
        player_record: LapRecord,
        rows: List[Dict[str, Any]],
        nearby_by_driver: Dict[int, Dict[str, Optional[int]]],
    ) -> List[Dict[str, Any]]:
        advice: List[Dict[str, Any]] = []
        player_nearby = nearby_by_driver.get(player_record.driver_index, {})
        ahead_index = player_nearby.get("ahead")
        behind_index = player_nearby.get("behind")
        previous_player_record = self._previous_record(player_record.driver_index, player_record.lap_number)

        if ahead_index is not None:
            ahead_record = self._latest_record_for_lap_or_recent(ahead_index, player_record.lap_number)
            ahead_row = _row_by_driver_index(rows, ahead_index)
            if ahead_record and ahead_row:
                advice.extend(_pace_to_ahead_advice(
                    player_record,
                    ahead_record,
                    ahead_row,
                    previous_player_record,
                    self.latest_laps(player_record.driver_index, _ROLLING_PACE_LAPS),
                    self.latest_laps(ahead_index, _ROLLING_PACE_LAPS),
                ))

        if behind_index is not None:
            behind_record = self._latest_record_for_lap_or_recent(behind_index, player_record.lap_number)
            behind_row = _row_by_driver_index(rows, behind_index)
            if behind_record and behind_row:
                previous_behind_record = self._previous_record(behind_index, player_record.lap_number)
                behind_advice = _pace_to_behind_advice(
                    player_record,
                    behind_record,
                    behind_row,
                    previous_behind_record,
                    self.latest_laps(player_record.driver_index, _ROLLING_PACE_LAPS),
                    self.latest_laps(behind_index, _ROLLING_PACE_LAPS),
                )
                if behind_advice:
                    if (
                        behind_advice[0].get("id") == "pace-trend-threat-behind"
                        and len(advice) == 1
                        and advice[0].get("id") == "pace-trend-battle-ahead"
                    ):
                        advice = []
                    if not advice or behind_advice[0].get("id") != "pace-trend-holding-behind":
                        advice.extend(behind_advice)

        return advice

    def _latest_record_for_lap_or_recent(self, driver_index: int, lap_number: int) -> Optional[LapRecord]:
        records = list(self._records_by_driver.get(driver_index, []))
        for record in reversed(records):
            if record.lap_number == lap_number:
                return record
        return records[-1] if records else None

    def _previous_record(self, driver_index: int, lap_number: int) -> Optional[LapRecord]:
        records = list(self._records_by_driver.get(driver_index, []))
        for record in reversed(records):
            if record.lap_number < lap_number:
                return record
        return None


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def _lap_record_from_row(
    row: Dict[str, Any],
    nearby_by_driver: Dict[int, Dict[str, Optional[int]]],
    timestamp: float,
) -> Optional[LapRecord]:
    driver_index = _driver_index(row)
    if driver_index is None:
        return None

    lap_info = _dict(row.get("lap-info", {}))
    current_lap = _int_or_none(lap_info.get("current-lap") or lap_info.get("curr-lap-number"))
    if current_lap is None:
        current_lap = _int_or_none(row.get("current-lap"))
    if current_lap is None:
        return None

    completed_lap = current_lap - 1
    if completed_lap <= 0:
        return None

    last_lap = _dict(lap_info.get("last-lap", {}))
    if last_lap.get("is-valid") is False:
        return None

    lap_time_ms = _num(last_lap.get("lap-time-ms"))
    if lap_time_ms is None or lap_time_ms <= 0:
        return None

    driver = _dict(row.get("driver-info", {}))
    return LapRecord(
        driver_index=driver_index,
        driver_name=_safe_text(driver.get("name")) or f"Driver {driver_index}",
        lap_number=completed_lap,
        lap_time_ms=lap_time_ms,
        position=_int_or_none(driver.get("position")),
        gap_to_front_ms=_num(_dict(row.get("delta-info", {})).get("delta-to-car-in-front")),
        car_ahead_index=nearby_by_driver.get(driver_index, {}).get("ahead"),
        timestamp=timestamp,
    )


def _pace_to_ahead_advice(
    player: LapRecord,
    ahead: LapRecord,
    ahead_row: Dict[str, Any],
    previous_player: Optional[LapRecord],
    player_recent: List[LapRecord],
    ahead_recent: List[LapRecord],
) -> List[Dict[str, Any]]:
    diff_ms = player.lap_time_ms - ahead.lap_time_ms
    gap_ms = player.gap_to_front_ms
    gap_text = _format_gap_ms(gap_ms)
    gap_trend_ms = _gap_trend_ms(gap_ms, previous_player.gap_to_front_ms if previous_player else None)
    gap_trend_text = _format_gap_trend(gap_trend_ms, subject="ahead")
    player_lap_text = _format_lap_time_ms(player.lap_time_ms)
    ahead_lap_text = _format_lap_time_ms(ahead.lap_time_ms)
    ahead_name = ahead.driver_name
    is_battle = _is_battle_gap(gap_ms)
    rolling = _rolling_pace_summary(
        player_recent,
        ahead_recent,
        rival_key="ahead",
        rival_label="ahead",
    )

    if diff_ms <= -_MIN_SIGNIFICANT_LAP_DELTA_MS:
        return [_advice_item(
            item_id="pace-trend-catching-ahead",
            priority="advisory",
            title="Catching the car ahead",
            message=(
                f"Lap {player.lap_number}: you were {_format_gap_ms(abs(diff_ms))} faster than {ahead_name}. "
                f"Your lap was {player_lap_text}, their lap was {ahead_lap_text}. "
                f"Gap ahead is {gap_text}; {gap_trend_text}.{rolling['message']}"
            ),
            voice_callout=(
                f"Lap {player.lap_number}: you {player_lap_text}, ahead {ahead_lap_text}. "
                f"Faster by {_format_gap_ms(abs(diff_ms))}, gap {gap_text}.{rolling['voice']}"
            ),
            cooldown_key=f"pace_trend:catching_ahead:{player.lap_number}:{ahead.driver_index}",
            evidence=[
                f"player-lap={_format_lap_time_ms(player.lap_time_ms)}",
                f"car-ahead-lap={_format_lap_time_ms(ahead.lap_time_ms)}",
                f"gap-ahead={gap_text}",
                f"gap-trend-ahead={_format_signed_gap_ms(gap_trend_ms)}",
                *rolling["evidence"],
            ],
            metrics={
                "lap_number": player.lap_number,
                "player_lap_ms": player.lap_time_ms,
                "ahead_lap_ms": ahead.lap_time_ms,
                "last_lap_delta_to_ahead_ms": diff_ms,
                "gap_ahead_ms": gap_ms,
                "gap_trend_ahead_ms": gap_trend_ms,
                "battle_window": is_battle,
                "ahead_driver_index": ahead.driver_index,
                "ahead_position": _int_or_none(_dict(ahead_row.get("driver-info", {})).get("position")),
                **rolling["metrics"],
            },
        )]

    if diff_ms >= _MIN_THREAT_LAP_DELTA_MS:
        return [_advice_item(
            item_id="pace-trend-losing-ahead",
            priority="advisory" if is_battle else "info",
            title="Pace to car ahead",
            message=(
                f"Lap {player.lap_number}: {ahead_name} was {_format_gap_ms(diff_ms)} quicker. "
                f"Your lap was {player_lap_text}, their lap was {ahead_lap_text}. "
                f"Gap ahead is {gap_text}; {gap_trend_text}.{rolling['message']}"
            ),
            voice_callout=(
                f"Lap {player.lap_number}: you {player_lap_text}, ahead {ahead_lap_text}. "
                f"Ahead quicker by {_format_gap_ms(diff_ms)}.{rolling['voice']}"
            ),
            cooldown_key=f"pace_trend:losing_ahead:{player.lap_number}:{ahead.driver_index}",
            evidence=[
                f"player-lap={_format_lap_time_ms(player.lap_time_ms)}",
                f"car-ahead-lap={_format_lap_time_ms(ahead.lap_time_ms)}",
                f"gap-ahead={gap_text}",
                f"gap-trend-ahead={_format_signed_gap_ms(gap_trend_ms)}",
                *rolling["evidence"],
            ],
            metrics={
                "lap_number": player.lap_number,
                "player_lap_ms": player.lap_time_ms,
                "ahead_lap_ms": ahead.lap_time_ms,
                "last_lap_delta_to_ahead_ms": diff_ms,
                "gap_ahead_ms": gap_ms,
                "gap_trend_ahead_ms": gap_trend_ms,
                "battle_window": is_battle,
                "ahead_driver_index": ahead.driver_index,
                **rolling["metrics"],
            },
        )]

    if is_battle:
        return [_advice_item(
            item_id="pace-trend-battle-ahead",
            priority="advisory",
            title="Battle pace to car ahead",
            message=(
                f"Lap {player.lap_number}: you are in the battle window to {ahead_name}. "
                f"Your lap was {player_lap_text}, their lap was {ahead_lap_text}. "
                f"Gap ahead is {gap_text}; {gap_trend_text}.{rolling['message']}"
            ),
            voice_callout=(
                f"Lap {player.lap_number}: battle ahead. You {player_lap_text}, ahead {ahead_lap_text}. "
                f"Gap {gap_text}.{rolling['voice']}"
            ),
            cooldown_key=f"pace_trend:battle_ahead:{player.lap_number}:{ahead.driver_index}",
            evidence=[
                f"player-lap={player_lap_text}",
                f"car-ahead-lap={ahead_lap_text}",
                f"gap-ahead={gap_text}",
                f"gap-trend-ahead={_format_signed_gap_ms(gap_trend_ms)}",
                *rolling["evidence"],
            ],
            metrics={
                "lap_number": player.lap_number,
                "player_lap_ms": player.lap_time_ms,
                "ahead_lap_ms": ahead.lap_time_ms,
                "last_lap_delta_to_ahead_ms": diff_ms,
                "gap_ahead_ms": gap_ms,
                "gap_trend_ahead_ms": gap_trend_ms,
                "battle_window": True,
                "ahead_driver_index": ahead.driver_index,
                **rolling["metrics"],
            },
        )]

    return []


def _pace_to_behind_advice(
    player: LapRecord,
    behind: LapRecord,
    behind_row: Dict[str, Any],
    previous_behind: Optional[LapRecord],
    player_recent: List[LapRecord],
    behind_recent: List[LapRecord],
) -> List[Dict[str, Any]]:
    diff_ms = player.lap_time_ms - behind.lap_time_ms
    gap_ms = _num(_dict(behind_row.get("delta-info", {})).get("delta-to-car-in-front"))
    gap_trend_ms = _gap_trend_ms(gap_ms, previous_behind.gap_to_front_ms if previous_behind else None)
    gap_text = _format_gap_ms(gap_ms)
    gap_trend_text = _format_gap_trend(gap_trend_ms, subject="behind")
    player_lap_text = _format_lap_time_ms(player.lap_time_ms)
    behind_lap_text = _format_lap_time_ms(behind.lap_time_ms)
    is_battle = _is_battle_gap(gap_ms)
    rolling = _rolling_pace_summary(
        player_recent,
        behind_recent,
        rival_key="behind",
        rival_label="behind",
    )

    if diff_ms < _MIN_THREAT_LAP_DELTA_MS:
        if not is_battle:
            return []
        pace_text = (
            f"you were {_format_gap_ms(abs(diff_ms))} faster"
            if diff_ms < -_MIN_SIGNIFICANT_LAP_DELTA_MS
            else "pace is matched"
        )
        return [_advice_item(
            item_id="pace-trend-holding-behind",
            priority="advisory",
            title="Holding the car behind",
            message=(
                f"Lap {player.lap_number}: {pace_text} against {behind.driver_name}. "
                f"Your lap was {player_lap_text}, their lap was {behind_lap_text}. "
                f"Gap behind is {gap_text}; {gap_trend_text}.{rolling['message']}"
            ),
            voice_callout=(
                f"Lap {player.lap_number}: car behind {behind_lap_text}. "
                f"Your lap {player_lap_text}, gap {gap_text}.{rolling['voice']}"
            ),
            cooldown_key=f"pace_trend:holding_behind:{player.lap_number}:{behind.driver_index}",
            evidence=[
                f"player-lap={player_lap_text}",
                f"car-behind-lap={behind_lap_text}",
                f"gap-behind={gap_text}",
                f"gap-trend-behind={_format_signed_gap_ms(gap_trend_ms)}",
                *rolling["evidence"],
            ],
            metrics={
                "lap_number": player.lap_number,
                "player_lap_ms": player.lap_time_ms,
                "behind_lap_ms": behind.lap_time_ms,
                "last_lap_delta_to_behind_ms": diff_ms,
                "gap_behind_ms": gap_ms,
                "gap_trend_behind_ms": gap_trend_ms,
                "battle_window": True,
                "behind_driver_index": behind.driver_index,
                **rolling["metrics"],
            },
        )]

    return [_advice_item(
        item_id="pace-trend-threat-behind",
        priority="warning",
        title="Car behind has pace",
        message=(
            f"Lap {player.lap_number}: {behind.driver_name} was {_format_gap_ms(diff_ms)} faster. "
            f"Your lap was {player_lap_text}, their lap was {behind_lap_text}. "
            f"Gap behind is {gap_text}; {gap_trend_text}.{rolling['message']}"
        ),
        voice_callout=(
            f"Lap {player.lap_number}: behind {behind_lap_text}, you {player_lap_text}. "
            f"They were {_format_gap_ms(diff_ms)} faster, gap {gap_text}.{rolling['voice']}"
        ),
        cooldown_key=f"pace_trend:threat_behind:{player.lap_number}:{behind.driver_index}",
        evidence=[
            f"player-lap={_format_lap_time_ms(player.lap_time_ms)}",
            f"car-behind-lap={_format_lap_time_ms(behind.lap_time_ms)}",
            f"gap-behind={gap_text}",
            f"gap-trend-behind={_format_signed_gap_ms(gap_trend_ms)}",
            *rolling["evidence"],
        ],
        metrics={
            "lap_number": player.lap_number,
            "player_lap_ms": player.lap_time_ms,
            "behind_lap_ms": behind.lap_time_ms,
            "last_lap_delta_to_behind_ms": diff_ms,
            "gap_behind_ms": gap_ms,
            "gap_trend_behind_ms": gap_trend_ms,
            "battle_window": is_battle,
            "behind_driver_index": behind.driver_index,
            **rolling["metrics"],
        },
    )]


def _rolling_pace_summary(
    player_records: List[LapRecord],
    rival_records: List[LapRecord],
    *,
    rival_key: str,
    rival_label: str,
) -> Dict[str, Any]:
    count = min(len(player_records), len(rival_records), _ROLLING_PACE_LAPS)
    if count < 2:
        return {"message": "", "voice": "", "evidence": [], "metrics": {}}

    player_avg_ms = _average_lap_time(player_records[-count:])
    rival_avg_ms = _average_lap_time(rival_records[-count:])
    if player_avg_ms is None or rival_avg_ms is None:
        return {"message": "", "voice": "", "evidence": [], "metrics": {}}

    delta_ms = player_avg_ms - rival_avg_ms
    label = f"{count}-lap avg"
    player_text = _format_lap_time_ms(player_avg_ms)
    rival_text = _format_lap_time_ms(rival_avg_ms)
    delta_text = _format_rolling_delta(delta_ms, rival_label)
    return {
        "message": f" {label}: you {player_text}, {rival_label} {rival_text}; {delta_text}.",
        "voice": f" {label}: you {player_text}, {rival_label} {rival_text}.",
        "evidence": [
            f"{count}-lap-player-avg={player_text}",
            f"{count}-lap-{rival_key}-avg={rival_text}",
            f"{count}-lap-delta-to-{rival_key}={_format_signed_gap_ms(delta_ms)}",
        ],
        "metrics": {
            f"recent_lap_count_to_{rival_key}": count,
            "player_recent_avg_ms": player_avg_ms,
            f"{rival_key}_recent_avg_ms": rival_avg_ms,
            f"recent_avg_delta_to_{rival_key}_ms": delta_ms,
        },
    }


def _average_lap_time(records: List[LapRecord]) -> Optional[float]:
    if not records:
        return None
    return sum(record.lap_time_ms for record in records) / len(records)


def _format_rolling_delta(delta_ms: float, rival_label: str) -> str:
    if abs(delta_ms) < _MIN_SIGNIFICANT_LAP_DELTA_MS:
        return "recent pace is matched"
    if delta_ms < 0:
        return f"you are {_format_gap_ms(delta_ms)} faster on recent pace"
    return f"{rival_label} is {_format_gap_ms(delta_ms)} faster on recent pace"


def _advice_item(
    *,
    item_id: str,
    priority: str,
    title: str,
    message: str,
    voice_callout: str,
    cooldown_key: str,
    evidence: List[str],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "id": item_id,
        "category": "pace",
        "priority": priority,
        "title": title,
        "message": message,
        "voice_callout": voice_callout,
        "cooldown_key": cooldown_key,
        "evidence": evidence,
        "metrics": metrics,
    }


def _nearby_indices_by_driver(rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Optional[int]]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: _num(_dict(row.get("driver-info", {})).get("position"), default=999),
    )
    result: Dict[int, Dict[str, Optional[int]]] = {}
    for index, row in enumerate(sorted_rows):
        driver_index = _driver_index(row)
        if driver_index is None:
            continue
        ahead = _driver_index(sorted_rows[index - 1]) if index > 0 else None
        behind = _driver_index(sorted_rows[index + 1]) if index + 1 < len(sorted_rows) else None
        result[driver_index] = {"ahead": ahead, "behind": behind}
    return result


def _get_ref_row(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    table_entries = _list_of_dicts(data.get("table-entries"))
    if not table_entries:
        return None

    ref_index = data.get("ref-row-index")
    if isinstance(ref_index, int) and not isinstance(ref_index, bool) and 0 <= ref_index < len(table_entries):
        return table_entries[ref_index]

    if data.get("is-spectating", False):
        spectator_index = _int_or_none(data.get("spectator-car-index"))
        if spectator_index is not None:
            return _row_by_driver_index(table_entries, spectator_index)

    return next(
        (
            row
            for row in table_entries
            if _dict(row.get("driver-info", {})).get("is-player") is True
        ),
        None,
    )


def _row_by_driver_index(rows: List[Dict[str, Any]], driver_index: int) -> Optional[Dict[str, Any]]:
    return next((row for row in rows if _driver_index(row) == driver_index), None)


def _driver_index(row: Dict[str, Any]) -> Optional[int]:
    return _int_or_none(_dict(row.get("driver-info", {})).get("index"))


def _int_or_none(value: Any) -> Optional[int]:
    number = _num(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_text(value: Any, *, max_len: int = 80) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return None
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def _session_uid(telemetry_update: Dict[str, Any]) -> Optional[str]:
    value = telemetry_update.get("session-uid")
    if value is None:
        return None
    return str(value)


def _format_gap_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "unavailable"
    return f"{abs(ms) / 1000.0:.1f}s"


def _format_signed_gap_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "unavailable"
    sign = "+" if ms > 0 else ""
    return f"{sign}{ms / 1000.0:.1f}s"


def _is_battle_gap(ms: Optional[float]) -> bool:
    return ms is not None and 0 < ms <= _BATTLE_GAP_WINDOW_MS


def _gap_trend_ms(current_ms: Optional[float], previous_ms: Optional[float]) -> Optional[float]:
    if current_ms is None or previous_ms is None:
        return None
    return current_ms - previous_ms


def _format_gap_trend(trend_ms: Optional[float], *, subject: str) -> str:
    if trend_ms is None:
        return "gap trend unavailable"
    if abs(trend_ms) < _MIN_GAP_TREND_MS:
        return "gap stable"
    if subject == "behind":
        return (
            f"car behind closing by {_format_gap_ms(trend_ms)}"
            if trend_ms < 0
            else f"gap opened by {_format_gap_ms(trend_ms)}"
        )
    return (
        f"closing by {_format_gap_ms(trend_ms)}"
        if trend_ms < 0
        else f"gap opened by {_format_gap_ms(trend_ms)}"
    )


def _format_lap_time_ms(ms: Optional[float]) -> Optional[str]:
    if ms is None or ms <= 0:
        return None
    total_ms = int(round(ms))
    minutes = total_ms // 60000
    seconds_ms = total_ms % 60000
    seconds = seconds_ms // 1000
    millis = seconds_ms % 1000
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"
