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

import asyncio
from typing import Any, Dict, List, Optional

from lib.logger import PngLogger
from lib.race_engineer import DrivingTraceRecorder
from lib.wdt import WatchDogTimerAsync

from .state import delete_state_data, set_state_data

# -------------------------------------- CLASSES -----------------------------------------------------------------------

class McpSubscriber:
    def __init__(self, logger: PngLogger, port: int, timeout: float) -> None:
        """Initialize the IPC server.

        Args:
            logger (PngLogger): Logger
            port (int): IPC port
            timeout (float): Connection timeout in seconds
        """
        from lib.ipc import IpcSubscriberAsync

        self.m_ipc_sub = IpcSubscriberAsync(port=port, logger=logger)
        self.m_trace_recorder = DrivingTraceRecorder()
        self.m_trace_session_uid: Optional[Any] = None
        set_state_data("connected", False)
        self.m_wdt = WatchDogTimerAsync(
            status_callback=self._wdt_callback,
            timeout=timeout
        )
        self._init_routes()
        self._init_callbacks()

    def _init_callbacks(self) -> None:
        """Initialize connection callbacks."""
        @self.m_ipc_sub.on_connect
        async def _on_connect() -> None:
            self.m_ipc_sub.logger.silent("IPC Subscriber connected")

        @self.m_ipc_sub.on_disconnect
        async def _on_disconnect(_exc: Optional[Exception]) -> None:
            self.m_ipc_sub.logger.silent("IPC Subscriber disconnected")

    def _init_routes(self) -> None:
        """Initialize the IPC routes."""
        @self.m_ipc_sub.route("race-table-update")
        async def _handle_race_table_update(msg: Dict[str, Any]) -> None:
            """Handle race table update messages."""
            set_state_data("race-table-update", msg)
            self.m_wdt.kick()

        @self.m_ipc_sub.route("race-engineer-trace-update")
        async def _handle_race_engineer_trace_update(msg: Dict[str, Any]) -> None:
            """Handle high-frequency race engineer trace messages."""
            set_state_data("race-engineer-trace-update", msg)
            self._clear_stale_trace_advice_if_session_changed(msg)
            previous_completed = self.m_trace_recorder.last_completed_lap
            advice = self.m_trace_recorder.update_from_trace_update(msg)
            last_completed = self.m_trace_recorder.last_completed_lap
            if last_completed is not None and last_completed is not previous_completed:
                set_state_data("race-engineer-driving-advice-update", {
                    "source": "race-engineer-trace-update",
                    "session-uid": self.m_trace_session_uid,
                    "advice": advice,
                    "reference-lap-count": self.m_trace_recorder.reference_lap_count,
                    "last-completed-lap": last_completed.lap_number if last_completed else None,
                })
            self.m_wdt.kick()

    def _clear_stale_trace_advice_if_session_changed(self, msg: Dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            return
        session_uid = msg.get("session-uid")
        if not session_uid:
            return
        if self.m_trace_session_uid is None:
            self.m_trace_session_uid = session_uid
            return
        if session_uid != self.m_trace_session_uid:
            self.m_trace_session_uid = session_uid
            delete_state_data("race-engineer-driving-advice-update")

    async def run(self) -> None:
        """Starts the IPC server."""
        await self.m_ipc_sub.run()

    async def close(self) -> None:
        """Closes the IPC subscriber."""
        self.m_ipc_sub.close()

    def _wdt_callback(self, active: bool) -> None:
        """Watchdog timer callback to update IPC activity state.

        Args:
            active (bool): True if Subscriptions are active (i.e.) "connected" to producer
        """
        set_state_data("connected", active)
        if active:
            self.m_ipc_sub.logger.info("Connected to data stream")
        else:
            self.m_ipc_sub.logger.warning("Disconnected from data stream")

    def get_stats(self) -> dict:
        """Get stats for the subscriber.

        Returns:
            dict: Stats dictionary
        """
        return {
            **self.m_ipc_sub.get_stats(),
            "trace-reference-laps": self.m_trace_recorder.reference_lap_count,
        }

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------

def init_subscriber_task(port: int, logger: PngLogger, tasks: List[asyncio.Task]) -> McpSubscriber:
    """Initialize the IPC task.

    Args:
        port (int): IPC port
        logger (PngLogger): Logger
        tasks (List[asyncio.Task]): List of tasks

    Returns:
        McpSubscriber: The MCP Subscriber instance
    """
    ipc_sub = McpSubscriber(logger, port, timeout=10.0)
    tasks.append(asyncio.create_task(ipc_sub.run(), name="IPC Subscriber Task"))
    tasks.append(asyncio.create_task(ipc_sub.m_wdt.run(), name="IPC Watchdog Task"))
    return ipc_sub
