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
from typing import Any, Dict, List, Optional, Tuple

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

_MIN_TRACE_SAMPLES = 6
_MIN_REFERENCE_COVERAGE_RATIO = 0.55
_EARLY_BRAKE_DELTA_M = 35.0
_BRAKE_THROTTLE_OVERLAP_PCT = 25.0
_MIN_CONSECUTIVE_BIN_PAIRS = {
    "brake_throttle_overlap": 2,
    "early_brake": 2,
    "long_coast": 2,
    "weak_throttle": 2,
    "speed_loss": 1,
}
_REFERENCE_OVERLAP_PCT = 5.0
_OVERLAP_SPEED_FLOOR_KMPH = 80.0
_OVERLAP_SPEED_LOSS_KMPH = 4.0
_OVERLAP_MIN_CONSECUTIVE_BINS = 2
_THROTTLE_DELTA_PCT = 25.0
_COASTING_THROTTLE_PCT = 5.0
_COASTING_BRAKE_PCT = 5.0
_COASTING_SPEED_LOSS_KMPH = 8.0
_SPEED_LOSS_KMPH = 12.0
_ISSUE_PRIORITY = {
    "brake_throttle_overlap": 5,
    "early_brake": 4,
    "long_coast": 3,
    "weak_throttle": 2,
    "speed_loss": 1,
}

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DrivingTraceSample:
    """One high-frequency driving sample for the reference car."""

    session_uid: Optional[str]
    circuit: Optional[str]
    current_lap: int
    lap_distance_m: float
    circuit_length_m: float
    timestamp_sec: float
    speed_kmph: float
    throttle_pct: float
    brake_pct: float
    steering_pct: Optional[float]
    gear: Optional[int]
    sector: Optional[str]
    location_label: Optional[str] = None
    location_voice_label: Optional[str] = None


@dataclass(frozen=True, slots=True)
class CompletedLapTrace:
    """Binned trace for one completed lap."""

    session_uid: Optional[str]
    circuit: Optional[str]
    lap_number: int
    circuit_length_m: float
    lap_duration_sec: Optional[float]
    samples_by_bin: Dict[int, DrivingTraceSample]

    @property
    def sample_count(self) -> int:
        return len(self.samples_by_bin)

    def coverage_ratio(self, bin_size_m: int) -> float:
        """Return approximate distance-bin coverage for this completed lap."""

        expected_bins = _expected_lap_bins(self.circuit_length_m, bin_size_m)
        if expected_bins <= 0:
            return 0.0
        return min(1.0, self.sample_count / expected_bins)


class DrivingTraceRecorder:
    """Collect per-distance driving traces and emit driving-coach advice."""

    def __init__(
        self,
        *,
        bin_size_m: int = 10,
        min_samples: int = _MIN_TRACE_SAMPLES,
        min_reference_coverage_ratio: float = _MIN_REFERENCE_COVERAGE_RATIO,
        max_reference_laps: int = 5,
    ) -> None:
        self.bin_size_m = max(1, bin_size_m)
        self.min_samples = max(2, min_samples)
        self.min_reference_coverage_ratio = max(0.0, min(1.0, min_reference_coverage_ratio))
        self.max_reference_laps = max(1, max_reference_laps)
        self._session_uid: Optional[str] = None
        self._active_lap: Optional[int] = None
        self._active_samples_by_bin: Dict[int, DrivingTraceSample] = {}
        self._reference_laps: List[CompletedLapTrace] = []
        self._last_completed_lap: Optional[CompletedLapTrace] = None

    def update_from_stream_overlay(self, stream_overlay_update: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Record a stream-overlay sample and return advice when a lap completes."""

        sample = sample_from_stream_overlay(stream_overlay_update)
        return self.update_sample(sample)

    def update_from_trace_update(self, trace_update: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Record a backend race-engineer-trace-update sample."""

        sample = sample_from_trace_update(trace_update)
        return self.update_sample(sample)

    def update_sample(self, sample: Optional[DrivingTraceSample]) -> List[Dict[str, Any]]:
        """Record one sample and return advice when a lap completes."""

        if not sample:
            return []

        if sample.session_uid != self._session_uid:
            self.clear()
            self._session_uid = sample.session_uid

        if self._active_lap is None:
            self._start_lap(sample)
            return []

        if sample.current_lap != self._active_lap:
            completed = self._complete_active_lap()
            self._start_lap(sample)
            if completed is None:
                return []
            self._last_completed_lap = completed
            if not self._is_reference_quality_lap(completed):
                return []
            advice = self._compare_to_reference(completed)
            self._add_reference_lap(completed)
            return advice

        self._record_sample(sample)
        return []

    def clear(self) -> None:
        """Clear active and reference trace state."""

        self._session_uid = None
        self._active_lap = None
        self._active_samples_by_bin.clear()
        self._reference_laps.clear()
        self._last_completed_lap = None

    @property
    def reference_lap_count(self) -> int:
        return len(self._reference_laps)

    @property
    def last_completed_lap(self) -> Optional[CompletedLapTrace]:
        return self._last_completed_lap

    def _start_lap(self, sample: DrivingTraceSample) -> None:
        self._active_lap = sample.current_lap
        self._active_samples_by_bin = {}
        self._record_sample(sample)

    def _record_sample(self, sample: DrivingTraceSample) -> None:
        if not (0 <= sample.lap_distance_m <= sample.circuit_length_m):
            return
        bin_index = int(sample.lap_distance_m // self.bin_size_m)
        self._active_samples_by_bin[bin_index] = sample

    def _complete_active_lap(self) -> Optional[CompletedLapTrace]:
        if self._active_lap is None or len(self._active_samples_by_bin) < self.min_samples:
            return None

        samples = list(self._active_samples_by_bin.values())
        samples.sort(key=lambda sample: sample.timestamp_sec)
        lap_duration_sec = samples[-1].timestamp_sec - samples[0].timestamp_sec
        if lap_duration_sec <= 0:
            lap_duration_sec = None

        first = samples[0]
        return CompletedLapTrace(
            session_uid=first.session_uid,
            circuit=first.circuit,
            lap_number=self._active_lap,
            circuit_length_m=first.circuit_length_m,
            lap_duration_sec=lap_duration_sec,
            samples_by_bin=dict(self._active_samples_by_bin),
        )

    def _add_reference_lap(self, lap: CompletedLapTrace) -> None:
        if not self._is_reference_quality_lap(lap):
            return
        self._reference_laps.append(lap)
        self._reference_laps.sort(key=lambda item: item.lap_duration_sec or float("inf"))
        del self._reference_laps[self.max_reference_laps:]

    def _is_reference_quality_lap(self, lap: CompletedLapTrace) -> bool:
        return (
            lap.sample_count >= self.min_samples
            and lap.coverage_ratio(self.bin_size_m) >= self.min_reference_coverage_ratio
        )

    def _compare_to_reference(self, lap: CompletedLapTrace) -> List[Dict[str, Any]]:
        reference = self._best_reference_lap()
        if reference is None:
            return []

        issues = _find_trace_issues(lap, reference, self.bin_size_m)
        return [_issue_to_advice(issue, lap, reference, self.bin_size_m) for issue in issues[:1]]

    def _best_reference_lap(self) -> Optional[CompletedLapTrace]:
        return self._reference_laps[0] if self._reference_laps else None


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def sample_from_stream_overlay(stream_overlay_update: Optional[Dict[str, Any]]) -> Optional[DrivingTraceSample]:
    """Extract one driving trace sample from a stream-overlay-update payload."""

    if not isinstance(stream_overlay_update, dict):
        return None

    hud = _dict(stream_overlay_update.get("hud"))
    car_telemetry = _dict(stream_overlay_update.get("car-telemetry"))
    current_lap = _int_or_none(stream_overlay_update.get("current-lap"))
    lap_distance_m = _num(hud.get("circuit-position"))
    circuit_length_m = _num(hud.get("circuit-length"))
    speed_kmph = _num(hud.get("speed-kmph"))
    throttle_pct = _input_pct(hud.get("throttle"), car_telemetry.get("throttle"))
    brake_pct = _input_pct(hud.get("brake"), car_telemetry.get("brake"))

    if None in (current_lap, lap_distance_m, circuit_length_m, speed_kmph, throttle_pct, brake_pct):
        return None
    if current_lap <= 0 or circuit_length_m <= 0:
        return None

    return DrivingTraceSample(
        session_uid=_safe_key(stream_overlay_update.get("session-uid")),
        circuit=_safe_key(stream_overlay_update.get("circuit-enum-name")),
        current_lap=current_lap,
        lap_distance_m=lap_distance_m,
        circuit_length_m=circuit_length_m,
        timestamp_sec=_num(stream_overlay_update.get("timestamp")) or time.time(),
        speed_kmph=speed_kmph,
        throttle_pct=throttle_pct,
        brake_pct=brake_pct,
        steering_pct=_signed_pct(car_telemetry.get("steering")),
        gear=_int_or_none(hud.get("gear")),
        sector=_safe_key(hud.get("sector")),
        location_label=_safe_key(stream_overlay_update.get("segment-label")),
        location_voice_label=_safe_key(stream_overlay_update.get("segment-voice-label")),
    )


def sample_from_trace_update(trace_update: Optional[Dict[str, Any]]) -> Optional[DrivingTraceSample]:
    """Extract one driving trace sample from a race-engineer-trace-update payload."""

    if not isinstance(trace_update, dict) or trace_update.get("ok") is False:
        return None

    current_lap = _int_or_none(trace_update.get("current-lap"))
    lap_distance_m = _num(trace_update.get("lap-distance-m"))
    circuit_length_m = _num(trace_update.get("circuit-length-m"))
    speed_kmph = _num(trace_update.get("speed-kmph"))
    throttle_pct = _input_pct(trace_update.get("throttle-pct"), None)
    brake_pct = _input_pct(trace_update.get("brake-pct"), None)

    if None in (current_lap, lap_distance_m, circuit_length_m, speed_kmph, throttle_pct, brake_pct):
        return None
    if current_lap <= 0 or circuit_length_m <= 0:
        return None
    if trace_update.get("current-lap-invalid") is True:
        return None
    if _is_pit_trace_update(trace_update):
        return None

    return DrivingTraceSample(
        session_uid=_safe_key(trace_update.get("session-uid")),
        circuit=_safe_key(trace_update.get("circuit-enum-name")),
        current_lap=current_lap,
        lap_distance_m=lap_distance_m,
        circuit_length_m=circuit_length_m,
        timestamp_sec=_num(trace_update.get("timestamp")) or time.time(),
        speed_kmph=speed_kmph,
        throttle_pct=throttle_pct,
        brake_pct=brake_pct,
        steering_pct=_signed_pct(trace_update.get("steering-pct")),
        gear=_int_or_none(trace_update.get("gear")),
        sector=_safe_key(trace_update.get("sector")),
        location_label=_safe_key(trace_update.get("segment-label")),
        location_voice_label=_safe_key(trace_update.get("segment-voice-label")),
    )


def _find_trace_issues(
    lap: CompletedLapTrace,
    reference: CompletedLapTrace,
    bin_size_m: int,
) -> List[Dict[str, Any]]:
    common_bins = sorted(set(lap.samples_by_bin).intersection(reference.samples_by_bin))
    brake_throttle_overlap_candidates: List[Tuple[int, DrivingTraceSample, DrivingTraceSample]] = []
    early_brake: List[Tuple[DrivingTraceSample, DrivingTraceSample]] = []
    long_coast: List[Tuple[DrivingTraceSample, DrivingTraceSample]] = []
    weak_throttle: List[Tuple[DrivingTraceSample, DrivingTraceSample]] = []
    speed_loss: List[Tuple[DrivingTraceSample, DrivingTraceSample]] = []

    for bin_index in common_bins:
        current = lap.samples_by_bin[bin_index]
        ref = reference.samples_by_bin[bin_index]
        current_overlap = min(current.throttle_pct, current.brake_pct)
        reference_overlap = min(ref.throttle_pct, ref.brake_pct)
        if (
            current_overlap >= _BRAKE_THROTTLE_OVERLAP_PCT
            and reference_overlap <= _REFERENCE_OVERLAP_PCT
            and ref.speed_kmph - current.speed_kmph >= _OVERLAP_SPEED_LOSS_KMPH
            and current.speed_kmph >= _OVERLAP_SPEED_FLOOR_KMPH
        ):
            brake_throttle_overlap_candidates.append((bin_index, current, ref))
        if current.brake_pct >= 35 and ref.brake_pct <= 5 and current.speed_kmph <= ref.speed_kmph - 5:
            early_brake.append((current, ref))
        if (
            current.throttle_pct <= _COASTING_THROTTLE_PCT
            and current.brake_pct <= _COASTING_BRAKE_PCT
            and (ref.throttle_pct >= 35 or ref.brake_pct >= 25)
            and current.speed_kmph <= ref.speed_kmph - _COASTING_SPEED_LOSS_KMPH
        ):
            long_coast.append((current, ref))
        if ref.throttle_pct - current.throttle_pct >= _THROTTLE_DELTA_PCT and current.speed_kmph <= ref.speed_kmph - 4:
            weak_throttle.append((current, ref))
        if ref.speed_kmph - current.speed_kmph >= _SPEED_LOSS_KMPH:
            speed_loss.append((current, ref))

    issues = []
    brake_throttle_overlap = _consecutive_sample_pairs(
        brake_throttle_overlap_candidates,
        min_consecutive_bins=_OVERLAP_MIN_CONSECUTIVE_BINS,
    )
    early_brake = _consecutive_sample_pairs(
        early_brake,
        min_consecutive_bins=_MIN_CONSECUTIVE_BIN_PAIRS["early_brake"],
    )
    long_coast = _consecutive_sample_pairs(
        long_coast,
        min_consecutive_bins=_MIN_CONSECUTIVE_BIN_PAIRS["long_coast"],
    )
    weak_throttle = _consecutive_sample_pairs(
        weak_throttle,
        min_consecutive_bins=_MIN_CONSECUTIVE_BIN_PAIRS["weak_throttle"],
    )
    speed_loss = _consecutive_sample_pairs(
        speed_loss,
        min_consecutive_bins=_MIN_CONSECUTIVE_BIN_PAIRS["speed_loss"],
    )

    if brake_throttle_overlap:
        issues.append(_summarise_issue("brake_throttle_overlap", brake_throttle_overlap, bin_size_m))
    if early_brake:
        issues.append(_summarise_issue("early_brake", early_brake, bin_size_m))
    if long_coast:
        issues.append(_summarise_issue("long_coast", long_coast, bin_size_m))
    if weak_throttle:
        issues.append(_summarise_issue("weak_throttle", weak_throttle, bin_size_m))
    if speed_loss:
        issues.append(_summarise_issue("speed_loss", speed_loss, bin_size_m))

    return sorted(
        issues,
        key=lambda issue: (_ISSUE_PRIORITY.get(issue["type"], 0), issue["score"]),
        reverse=True,
    )


def _summarise_issue(
    issue_type: str,
    samples: List[Tuple[DrivingTraceSample, DrivingTraceSample]],
    bin_size_m: int,
) -> Dict[str, Any]:
    current_samples = [sample for sample, _ref in samples]
    ref_samples = [ref for _sample, ref in samples]
    start = min(sample.lap_distance_m for sample in current_samples)
    end = max(sample.lap_distance_m for sample in current_samples) + bin_size_m
    sector = _dominant_sector(current_samples)
    location_label, location_voice_label = _dominant_location(current_samples)
    avg_speed_loss = sum(ref.speed_kmph - sample.speed_kmph for sample, ref in samples) / len(samples)
    avg_throttle_loss = sum(ref.throttle_pct - sample.throttle_pct for sample, ref in samples) / len(samples)
    avg_brake_extra = sum(sample.brake_pct - ref.brake_pct for sample, ref in samples) / len(samples)
    avg_overlap = sum(min(sample.throttle_pct, sample.brake_pct) for sample in current_samples) / len(current_samples)
    return {
        "type": issue_type,
        "sector": sector,
        "location_label": location_label,
        "location_voice_label": location_voice_label,
        "distance_start_m": start,
        "distance_end_m": end,
        "sample_count": len(samples),
        "avg_speed_loss_kmph": avg_speed_loss,
        "avg_throttle_loss_pct": avg_throttle_loss,
        "avg_brake_extra_pct": avg_brake_extra,
        "avg_overlap_pct": avg_overlap,
        "score": (avg_speed_loss * 2.0) + len(samples),
    }


def _issue_to_advice(
    issue: Dict[str, Any],
    lap: CompletedLapTrace,
    reference: CompletedLapTrace,
    bin_size_m: int,
) -> Dict[str, Any]:
    sector_text = _sector_text(issue.get("sector"))
    distance_text = f"{issue['distance_start_m']:.0f}-{issue['distance_end_m']:.0f}m"
    location_text = _location_text(issue, sector_text, distance_text)
    voice_location = _voice_location_text(issue, sector_text)
    if issue["type"] == "brake_throttle_overlap":
        title = "Brake and throttle overlap"
        message = (
            f"Lap {lap.lap_number}: you held brake and throttle together around {location_text}, "
            f"losing about {issue['avg_speed_loss_kmph']:.0f} km/h."
        )
        voice = f"{voice_location}: brake and throttle are overlapping. Separate the inputs."
    elif issue["type"] == "early_brake":
        title = "Braking too early"
        message = (
            f"Lap {lap.lap_number}: you braked earlier than the reference around {location_text}, "
            f"losing about {issue['avg_speed_loss_kmph']:.0f} km/h."
        )
        voice = f"{voice_location}: you are braking early. Carry a little more speed."
    elif issue["type"] == "long_coast":
        title = "Coasting too long"
        message = (
            f"Lap {lap.lap_number}: you coasted longer than the reference around {location_text}, "
            f"losing about {issue['avg_speed_loss_kmph']:.0f} km/h."
        )
        voice = f"{voice_location}: you are coasting too long. Commit to brake or throttle."
    elif issue["type"] == "weak_throttle":
        title = "Throttle pickup"
        message = (
            f"Lap {lap.lap_number}: throttle pickup was {issue['avg_throttle_loss_pct']:.0f} percentage points "
            f"lower than the reference around {location_text}."
        )
        voice = f"{voice_location}: throttle pickup is weak. Open the car earlier."
    else:
        title = "Speed loss"
        message = (
            f"Lap {lap.lap_number}: speed was about {issue['avg_speed_loss_kmph']:.0f} km/h lower than the "
            f"reference around {location_text}."
        )
        voice = f"{voice_location}: you are losing speed versus the reference."

    return {
        "id": f"driving-coach-{issue['type'].replace('_', '-')}",
        "category": "driving_coach",
        "priority": "advisory",
        "title": title,
        "message": message,
        "voice_callout": voice,
        "cooldown_key": f"driving_coach:{issue['type']}:{lap.lap_number}",
        "evidence": [
            f"lap={lap.lap_number}",
            f"reference-lap={reference.lap_number}",
            f"lap-coverage={lap.coverage_ratio(bin_size_m):.2f}",
            f"reference-coverage={reference.coverage_ratio(bin_size_m):.2f}",
            f"sector={issue.get('sector')}",
            f"location={issue.get('location_label') or '---'}",
            f"distance={distance_text}",
            f"avg-speed-loss-kmph={issue['avg_speed_loss_kmph']:.1f}",
            f"avg-overlap-pct={issue['avg_overlap_pct']:.1f}",
        ],
        "metrics": {
            "lap_number": lap.lap_number,
            "reference_lap_number": reference.lap_number,
            "lap_coverage_ratio": lap.coverage_ratio(bin_size_m),
            "reference_coverage_ratio": reference.coverage_ratio(bin_size_m),
            "sector": issue.get("sector"),
            "location_label": issue.get("location_label"),
            "location_voice_label": issue.get("location_voice_label"),
            "distance_start_m": issue["distance_start_m"],
            "distance_end_m": issue["distance_end_m"],
            "avg_speed_loss_kmph": issue["avg_speed_loss_kmph"],
            "avg_throttle_loss_pct": issue["avg_throttle_loss_pct"],
            "avg_brake_extra_pct": issue["avg_brake_extra_pct"],
            "avg_overlap_pct": issue["avg_overlap_pct"],
        },
    }


def _consecutive_sample_pairs(
    candidates: List[Tuple[int, DrivingTraceSample, DrivingTraceSample]],
    *,
    min_consecutive_bins: int,
) -> List[Tuple[DrivingTraceSample, DrivingTraceSample]]:
    """Return candidate sample pairs that belong to a long enough consecutive run."""

    if not candidates:
        return []

    selected: List[Tuple[DrivingTraceSample, DrivingTraceSample]] = []
    run: List[Tuple[int, DrivingTraceSample, DrivingTraceSample]] = []

    for candidate in candidates:
        if not run or candidate[0] == run[-1][0] + 1:
            run.append(candidate)
            continue

        if len(run) >= min_consecutive_bins:
            selected.extend((sample, ref) for _bin_index, sample, ref in run)
        run = [candidate]

    if len(run) >= min_consecutive_bins:
        selected.extend((sample, ref) for _bin_index, sample, ref in run)

    return selected


def _expected_lap_bins(circuit_length_m: float, bin_size_m: int) -> int:
    if circuit_length_m <= 0 or bin_size_m <= 0:
        return 0
    return max(1, int(circuit_length_m // bin_size_m) + 1)


def _dominant_sector(samples: List[DrivingTraceSample]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for sample in samples:
        if sample.sector:
            counts[sample.sector] = counts.get(sample.sector, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _dominant_location(samples: List[DrivingTraceSample]) -> Tuple[Optional[str], Optional[str]]:
    counts: Dict[str, int] = {}
    voice_by_label: Dict[str, str] = {}
    for sample in samples:
        if sample.location_label:
            counts[sample.location_label] = counts.get(sample.location_label, 0) + 1
            if sample.location_voice_label:
                voice_by_label[sample.location_label] = sample.location_voice_label
    if not counts:
        return None, None
    label = max(counts.items(), key=lambda item: item[1])[0]
    return label, voice_by_label.get(label, label)


def _location_text(issue: Dict[str, Any], sector_text: str, distance_text: str) -> str:
    location_label = issue.get("location_label")
    if isinstance(location_label, str) and location_label.strip():
        return location_label
    return f"{sector_text}, {distance_text}"


def _voice_location_text(issue: Dict[str, Any], sector_text: str) -> str:
    location_label = issue.get("location_voice_label") or issue.get("location_label")
    if isinstance(location_label, str) and location_label.strip():
        return location_label[:1].upper() + location_label[1:]
    return sector_text.title()


def _sector_text(sector: Optional[str]) -> str:
    if not sector:
        return "this part of the lap"
    sector = str(sector).strip()
    if sector.isdigit():
        return f"sector {sector}"
    lowered = sector.lower()
    if lowered.startswith("sector"):
        return lowered
    return f"sector {sector}"


def _input_pct(primary: Any, fallback: Any) -> Optional[float]:
    value = _num(primary)
    if value is None:
        value = _num(fallback)
    if value is None:
        return None
    if 0 <= value <= 1:
        value *= 100.0
    return max(0.0, min(value, 100.0))


def _signed_pct(value: Any) -> Optional[float]:
    number = _num(value)
    if number is None:
        return None
    if -1 <= number <= 1:
        number *= 100.0
    return max(-100.0, min(number, 100.0))


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    number = _num(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_key(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_pit_trace_update(trace_update: Dict[str, Any]) -> bool:
    if trace_update.get("pit-lane-timer-active") is True:
        return True
    pit_status = _safe_key(trace_update.get("pit-status"))
    if pit_status is None:
        return False
    pit_status = pit_status.lower().replace(" ", "_")
    return (
        pit_status in {"1", "2"}
        or "pitting" in pit_status
        or "pit_area" in pit_status
        or "in_pit" in pit_status
    )
