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

# ------------------------- IMPORTS ------------------------------------------------------------------------------------

from pathlib import Path
import time
from typing import Any, Dict, Optional

from ..base import BaseAPI

# ------------------------- MODULE VARIABLES ---------------------------------------------------------------------------

_TRACK_SEGMENTS_DB: Optional[Any] = None
_TRACK_SEGMENTS_DB_LOAD_ATTEMPTED = False

# ------------------------- API - CLASSES ------------------------------------------------------------------------------

class RaceEngineerTraceData(BaseAPI):
    """Compact high-frequency driving trace sample for the race engineer."""

    def __init__(self, session_state: Any) -> None:
        self.m_timestamp = time.time()
        self.m_session_info = session_state.m_session_info
        self.m_ref_index = self._get_ref_index(session_state)
        self.m_ref_obj = (
            session_state.m_driver_data[self.m_ref_index]
            if self.m_ref_index is not None and 0 <= self.m_ref_index < len(session_state.m_driver_data)
            else None
        )

    def toJSON(self) -> Dict[str, Any]:
        """Return a compact sample built directly from CarTelemetryData + LapData."""

        if not self.m_session_info:
            return self._unavailable("session info unavailable")
        if not self.m_ref_obj:
            return self._unavailable("reference driver unavailable")

        packet_copies = self.m_ref_obj.m_packet_copies
        car_telemetry = packet_copies.m_packet_car_telemetry
        lap_data = packet_copies.m_packet_lap_data
        if not car_telemetry or not lap_data:
            return self._unavailable("car telemetry or lap data unavailable")

        circuit_len = self.m_session_info.m_track_len
        if not circuit_len:
            return self._unavailable("track length unavailable")

        lap_distance = _wrap_lap_distance(lap_data.m_lapDistance, circuit_len)
        segment_info = _segment_payload(
            self.m_session_info.m_track.value if self.m_session_info.m_track is not None else None,
            lap_distance,
        )

        return {
            "ok": True,
            "source": "backend-session-state",
            "timestamp": self.m_timestamp,
            "session-uid": self.m_session_info.m_session_uid,
            "ref-index": self.m_ref_index,
            "circuit-enum-name": (
                self.m_session_info.m_track.name
                if self.m_session_info.m_track is not None
                else None
            ),
            "circuit-enum-value": (
                self.m_session_info.m_track.value
                if self.m_session_info.m_track is not None
                else None
            ),
            "current-lap": lap_data.m_currentLapNum,
            "current-lap-time-ms": lap_data.m_currentLapTimeInMS,
            "current-lap-invalid": lap_data.m_currentLapInvalid,
            "pit-status": str(lap_data.m_pitStatus),
            "pit-lane-timer-active": lap_data.m_pitLaneTimerActive,
            "lap-distance-m": lap_distance,
            "circuit-length-m": circuit_len,
            "sector": str(lap_data.m_sector),
            **segment_info,
            "speed-kmph": car_telemetry.m_speed,
            "throttle-pct": car_telemetry.m_throttle * 100.0,
            "brake-pct": car_telemetry.m_brake * 100.0,
            "steering-pct": car_telemetry.m_steer * 100.0,
            "gear": car_telemetry.m_gear,
            "drs-enabled": car_telemetry.m_drs,
        }

    def _unavailable(self, reason: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "source": "backend-session-state",
            "timestamp": self.m_timestamp,
            "session-uid": self.m_session_info.m_session_uid if self.m_session_info else None,
            "ref-index": self.m_ref_index,
            "reason": reason,
        }

    @staticmethod
    def _get_ref_index(session_state: Any) -> Optional[int]:
        session_info = session_state.m_session_info
        if not session_info:
            return None
        return (
            session_info.m_spectator_car_index
            if session_info.m_is_spectating
            else session_state.m_player_index
        )

# ------------------------- FUNCTIONS ----------------------------------------------------------------------------------

def _wrap_lap_distance(lap_distance: float, circuit_len: float) -> Optional[float]:
    if circuit_len is None or circuit_len <= 0 or lap_distance is None:
        return None
    if lap_distance < 0:
        return None
    return lap_distance % circuit_len


def _segment_payload(circuit_number: Optional[int], lap_distance: Optional[float]) -> Dict[str, Optional[str]]:
    result = {
        "segment-type": None,
        "segment-name": None,
        "segment-turns": None,
        "segment-label": None,
        "segment-voice-label": None,
    }
    if circuit_number is None or lap_distance is None:
        return result

    db = _get_track_segments_db()
    if db is None:
        return result

    segment = db.get_segment_info(circuit_number, lap_distance)
    if segment is None:
        return result

    rendered = segment.render()
    name = rendered.get("name") or None
    turns = rendered.get("turns") or None
    result.update({
        "segment-type": rendered.get("type"),
        "segment-name": name,
        "segment-turns": turns,
        "segment-label": _segment_label(name, turns),
        "segment-voice-label": _segment_voice_label(name, turns),
    })
    return result


def _get_track_segments_db() -> Optional[Any]:
    global _TRACK_SEGMENTS_DB, _TRACK_SEGMENTS_DB_LOAD_ATTEMPTED # pylint: disable=global-statement

    if _TRACK_SEGMENTS_DB_LOAD_ATTEMPTED:
        return _TRACK_SEGMENTS_DB

    _TRACK_SEGMENTS_DB_LOAD_ATTEMPTED = True
    try:
        from lib.track_segment_info import TrackSegmentsDatabase
        _TRACK_SEGMENTS_DB = TrackSegmentsDatabase(
            Path(__file__).resolve().parents[5] / "assets" / "track-segments"
        )
    except Exception: # pylint: disable=broad-exception-caught
        _TRACK_SEGMENTS_DB = None
    return _TRACK_SEGMENTS_DB


def _segment_label(name: Optional[str], turns: Optional[str]) -> Optional[str]:
    if name:
        return name
    if turns:
        return turns.replace("Turns ", "T").replace("Turn ", "T")
    return None


def _segment_voice_label(name: Optional[str], turns: Optional[str]) -> Optional[str]:
    if name:
        return name
    if turns:
        return turns.lower()
    return None
