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

from typing import Any, Mapping

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

RACE_ENGINEER_LAUNCHER_STATUS_LABELS = {
    "online": "Online",
    "waiting-for-telemetry": "No Telemetry",
    "listening": "Listening",
    "speaking": "Speaking",
    "voice-queued": "Queued",
    "muted": "Muted",
    "voice-error": "Voice Error",
    "speech-error": "Speech Error",
    "question-error": "Question Error",
}

RACE_ENGINEER_LAUNCHER_ATTENTION_STATUSES = {
    "voice-error",
    "speech-error",
    "question-error",
}

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------

def race_engineer_launcher_status_from_stats(stats: Mapping[str, Any] | None) -> str:
    """Return the short status label shown on the launcher subsystem card."""

    if not stats:
        return "Running"

    assistant_status = _normalise_status(stats.get("assistant-status"))
    if assistant_status in RACE_ENGINEER_LAUNCHER_STATUS_LABELS:
        return RACE_ENGINEER_LAUNCHER_STATUS_LABELS[assistant_status]

    if stats.get("enabled") is False:
        return RACE_ENGINEER_LAUNCHER_STATUS_LABELS["muted"]

    return "Running"


def race_engineer_launcher_status_is_attention(stats: Mapping[str, Any] | None) -> bool:
    """Return true when the assistant should be presented as needing attention."""

    if not stats:
        return False
    return _normalise_status(stats.get("assistant-status")) in RACE_ENGINEER_LAUNCHER_ATTENTION_STATUSES


def _normalise_status(value: Any) -> str:
    return str(value or "").strip().lower()
