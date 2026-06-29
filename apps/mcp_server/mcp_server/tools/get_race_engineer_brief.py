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

import logging
from typing import Any, Dict

from lib.race_engineer import (
    RACE_ENGINEER_BRIEF_OUTPUT_SCHEMA,
    build_race_engineer_brief,
    load_agent_prompt_overrides_from_env,
)

from .common import _get_race_engineer_trace_advice_context, _get_race_table_context

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------

def get_race_engineer_brief(
    logger: logging.Logger,
    focus: str = "all",
    max_items: int = 5,
) -> Dict[str, Any]:
    """Get a deterministic race engineer brief from MCP state."""
    telemetry_update, base_rsp = _get_race_table_context(logger)
    session_uid = telemetry_update.get("session-uid") if isinstance(telemetry_update, dict) else None
    trace_advice, trace_context = _get_race_engineer_trace_advice_context(
        logger,
        current_session_uid=session_uid,
    )
    try:
        agent_prompt_overrides = load_agent_prompt_overrides_from_env()
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring race engineer agent prompt overrides: %s", exc)
        agent_prompt_overrides = {}
    return build_race_engineer_brief(
        telemetry_update=telemetry_update,
        base_rsp=base_rsp,
        focus=focus,
        max_items=max_items,
        extra_advice=trace_advice,
        trace_context=trace_context,
        agent_prompt_overrides=agent_prompt_overrides,
    )
