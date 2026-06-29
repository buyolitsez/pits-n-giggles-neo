# MIT License
#
# Copyright (c) [2025] [Ashwin Natarajan]
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

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from lib.ipc import IpcDealerAsync

from apps.mcp_server.state import get_state_data

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

_DRIVER_INFO_REQ_STATUS_SCHEMA = {
    "status": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "error": {"type": ["string", "null"]},
            "status": {"type": ["integer", "null"]},
            "details": {"type": ["string", "null"]},
        },
        "required": ["ok"],
        "additionalProperties": False,
    },
}

_RACE_ENGINEER_TRACE_ADVICE_MAX_AGE_SEC = 120.0

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------
def _get_race_table_context(
    logger: logging.Logger,
) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Common preflight for race-table-derived tools.

    Returns:
        telemetry_update (Dict | None)
        base_response    (Dict)
    """
    telemetry_update_entry = get_state_data("race-table-update")
    connected_entry = get_state_data("connected")
    connected = bool(connected_entry.data) if connected_entry is not None else False

    base_rsp: Dict[str, Any] = {
        "available": False,
        "connected": connected,
        "last-update-timestamp": None,
        "ok": False,
    }

    if telemetry_update_entry is None:
        logger.debug("_get_race_table_context: telemetry update entry is None")
        return None, base_rsp

    telemetry_update = telemetry_update_entry.data
    base_rsp["last-update-timestamp"] = telemetry_update_entry.ts
    if not isinstance(telemetry_update, dict):
        logger.debug("_get_race_table_context: telemetry update entry is not a dict")
        base_rsp["status"] = "error"
        base_rsp["error"] = "Telemetry update is not an object."
        return None, base_rsp

    session_uid = telemetry_update.get("session-uid")
    if not session_uid:
        logger.debug("_get_race_table_context: session UID missing")
        return None, base_rsp

    base_rsp["available"] = True
    return telemetry_update, base_rsp


def _get_race_engineer_trace_advice_context(
    logger: logging.Logger,
    current_session_uid: Optional[Any] = None,
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    """Return the latest driving coach advice produced from race-engineer trace samples."""

    trace_advice_entry = get_state_data("race-engineer-driving-advice-update")
    trace_context: Dict[str, Any] = {
        "available": False,
        "source": None,
        "session_uid": None,
        "session_mismatch": False,
        "last_update_timestamp": None,
        "age_seconds": None,
        "stale": False,
        "invalid_payload": False,
        "reference_lap_count": None,
        "last_completed_lap": None,
    }
    if trace_advice_entry is None:
        return [], trace_context

    payload = trace_advice_entry.data
    if not isinstance(payload, dict):
        trace_context.update({
            "last_update_timestamp": trace_advice_entry.ts,
            "age_seconds": max(0.0, time.time() - trace_advice_entry.ts),
            "invalid_payload": True,
        })
        logger.debug("_get_race_engineer_trace_advice_context: payload is not a dict")
        return [], trace_context

    age_seconds = max(0.0, time.time() - trace_advice_entry.ts)
    is_stale = age_seconds > _RACE_ENGINEER_TRACE_ADVICE_MAX_AGE_SEC
    trace_session_uid = payload.get("session-uid")
    session_mismatch = (
        current_session_uid not in (None, "")
        and trace_session_uid not in (None, "")
        and str(current_session_uid) != str(trace_session_uid)
    )

    trace_context.update({
        "available": True,
        "source": payload.get("source"),
        "session_uid": trace_session_uid,
        "session_mismatch": session_mismatch,
        "last_update_timestamp": trace_advice_entry.ts,
        "age_seconds": age_seconds,
        "stale": is_stale,
        "reference_lap_count": payload.get("reference-lap-count"),
        "last_completed_lap": payload.get("last-completed-lap"),
    })
    if is_stale:
        trace_context["available"] = False
        logger.debug("_get_race_engineer_trace_advice_context: advice is stale")
        return [], trace_context
    if session_mismatch:
        trace_context["available"] = False
        logger.debug("_get_race_engineer_trace_advice_context: session UID mismatch")
        return [], trace_context

    advice = payload.get("advice")
    if not isinstance(advice, list):
        trace_context["available"] = False
        trace_context["invalid_payload"] = True
        logger.debug("_get_race_engineer_trace_advice_context: advice is not a list")
        return [], trace_context

    return [item for item in advice if isinstance(item, dict)], trace_context


async def fetch_driver_info(
        dealer: "IpcDealerAsync",
        logger: logging.Logger,
        driver_index: int,
) -> Dict[str, Any]:
    """
    Fetch driver info from the backend via ZMQ DEALER request-response.

    Never raises.
    Centralizes all transport and backend errors.
    """
    from lib.ipc import PngAppId

    reply = await dealer.send(
        str(PngAppId.BACKEND),
        "driver-info-request",
        {"index": driver_index},
    )

    if reply.get("status") == "error":
        reason = reply.get("reason", "unknown")
        error_key = "core_server_timeout" if "timeout" in reason else "core_server_unreachable"
        logger.error("[fetch_driver_info] dealer error: %s", reason)
        return {
            "status": {"ok": False, "error": error_key, "status": None, "details": reason},
            "data": None,
        }

    if not reply.get("ok"):
        logger.error("[fetch_driver_info] backend returned not-ok: %s", reply)
        return {
            "status": {"ok": False, "error": "backend_error", "status": None, "details": str(reply)},
            "data": None,
        }

    return {
        "status": {"ok": True, "error": None, "status": 200, "details": None},
        "data": reply.get("data"),
    }
