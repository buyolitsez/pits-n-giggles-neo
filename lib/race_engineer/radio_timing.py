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
from typing import Any, Optional

from .announcer import PRIORITY_RANK, RaceEngineerAnnouncement
from .lap_trace import DrivingTraceSample

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_RADIO_TIMING_ENABLED = True
DEFAULT_RADIO_TIMING_MAX_DELAY_SECONDS = 8.0
DEFAULT_RADIO_TIMING_CHECK_INTERVAL_SECONDS = 0.2

_CRITICAL_PRIORITY = "critical"
_BYPASS_CATEGORIES = {"system"}
_RECENT_SAMPLE_MAX_AGE_SECONDS = 2.5
_BUSY_BRAKE_PCT = 12.0
_BUSY_STEERING_PCT = 32.0
_SAFE_BRAKE_PCT = 6.0
_SAFE_STEERING_PCT = 18.0
_SAFE_THROTTLE_PCT = 35.0
_SAFE_SPEED_KMPH = 90.0

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RadioTimingConfig:
    """Runtime radio timing settings."""

    enabled: bool = DEFAULT_RADIO_TIMING_ENABLED
    max_delay_seconds: float = DEFAULT_RADIO_TIMING_MAX_DELAY_SECONDS
    check_interval_seconds: float = DEFAULT_RADIO_TIMING_CHECK_INTERVAL_SECONDS
    recent_sample_max_age_seconds: float = _RECENT_SAMPLE_MAX_AGE_SECONDS


@dataclass(frozen=True, slots=True)
class RadioTimingDecision:
    """Decision for one queued radio callout."""

    should_delay: bool
    reason: str
    forced: bool = False
    sample_age_seconds: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "should-delay": self.should_delay,
            "reason": self.reason,
            "forced": self.forced,
            "sample-age-seconds": self.sample_age_seconds,
        }


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def decide_radio_timing(
    announcement: Any,
    *,
    sample: Optional[DrivingTraceSample],
    now: float,
    queued_at: Optional[float],
    config: RadioTimingConfig,
    sample_received_at: Optional[float] = None,
) -> RadioTimingDecision:
    """Return whether a callout should wait for a calmer driving moment."""

    if not config.enabled:
        return RadioTimingDecision(False, "disabled")
    if not isinstance(announcement, RaceEngineerAnnouncement):
        return RadioTimingDecision(False, "unknown-announcement")
    if _priority(announcement.priority) <= _priority(_CRITICAL_PRIORITY):
        return RadioTimingDecision(False, "critical")
    if str(announcement.category or "").strip().lower() in _BYPASS_CATEGORIES:
        return RadioTimingDecision(False, "bypass-category")
    if sample is None:
        return RadioTimingDecision(False, "no-sample")

    sample_age_reference = sample_received_at if sample_received_at is not None else sample.timestamp_sec
    sample_age = max(0.0, now - sample_age_reference)
    if sample_age > config.recent_sample_max_age_seconds:
        return RadioTimingDecision(False, "stale-sample", sample_age_seconds=sample_age)

    if queued_at is not None and now - queued_at >= max(0.0, config.max_delay_seconds):
        return RadioTimingDecision(False, "max-delay", forced=True, sample_age_seconds=sample_age)

    if _is_busy(sample):
        return RadioTimingDecision(True, _busy_reason(sample), sample_age_seconds=sample_age)
    if _is_safe(sample):
        return RadioTimingDecision(False, "safe-window", sample_age_seconds=sample_age)
    return RadioTimingDecision(True, "not-yet-safe", sample_age_seconds=sample_age)


def normalise_radio_timing_config(
    *,
    enabled: Any = DEFAULT_RADIO_TIMING_ENABLED,
    max_delay_seconds: Any = DEFAULT_RADIO_TIMING_MAX_DELAY_SECONDS,
    check_interval_seconds: Any = DEFAULT_RADIO_TIMING_CHECK_INTERVAL_SECONDS,
) -> RadioTimingConfig:
    """Normalize loose runtime settings into a safe radio timing config."""

    return RadioTimingConfig(
        enabled=_bool(enabled, DEFAULT_RADIO_TIMING_ENABLED),
        max_delay_seconds=_bounded_float(max_delay_seconds, 0.0, 30.0, DEFAULT_RADIO_TIMING_MAX_DELAY_SECONDS),
        check_interval_seconds=_bounded_float(
            check_interval_seconds,
            0.05,
            2.0,
            DEFAULT_RADIO_TIMING_CHECK_INTERVAL_SECONDS,
        ),
    )


def _is_busy(sample: DrivingTraceSample) -> bool:
    steering = abs(sample.steering_pct) if sample.steering_pct is not None else 0.0
    return (
        sample.brake_pct >= _BUSY_BRAKE_PCT
        or steering >= _BUSY_STEERING_PCT
        or sample.speed_kmph < 45.0
    )


def _is_safe(sample: DrivingTraceSample) -> bool:
    steering = abs(sample.steering_pct) if sample.steering_pct is not None else 0.0
    return (
        sample.brake_pct <= _SAFE_BRAKE_PCT
        and steering <= _SAFE_STEERING_PCT
        and sample.throttle_pct >= _SAFE_THROTTLE_PCT
        and sample.speed_kmph >= _SAFE_SPEED_KMPH
    )


def _busy_reason(sample: DrivingTraceSample) -> str:
    steering = abs(sample.steering_pct) if sample.steering_pct is not None else 0.0
    if sample.brake_pct >= _BUSY_BRAKE_PCT:
        return "braking"
    if steering >= _BUSY_STEERING_PCT:
        return "cornering"
    return "low-speed"


def _priority(priority: str) -> int:
    return PRIORITY_RANK.get(str(priority or "").strip().lower(), 99)


def _bounded_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
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
