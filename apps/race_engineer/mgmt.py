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

import asyncio
import logging
import os
from typing import Any, Dict, List

from lib.child_proc_mgmt import report_ipc_port_from_child
from lib.error_status import PNG_LOST_CONN_TO_PARENT

from .race_engineer import RaceEngineerApp

# -------------------------------------- CLASSES -----------------------------------------------------------------------

class RaceEngineerIpc:
    """Launcher management IPC for the race engineer process."""

    def __init__(self, logger: logging.Logger, app: RaceEngineerApp) -> None:
        from lib.ipc import IpcServerAsync

        self.m_logger = logger
        self.m_app = app
        self.m_ipc_server = IpcServerAsync(name="Race Engineer")
        self._register_routes()
        report_ipc_port_from_child(self.m_ipc_server.port)

    async def run(self) -> None:
        """Run the management IPC server."""

        await self.m_ipc_server.run()

    def _register_routes(self) -> None:
        @self.m_ipc_server.on_heartbeat_missed
        async def _heartbeat_missed_handler(count: int) -> None:
            self.m_logger.error(
                "Missed heartbeat %d times. This process has probably been orphaned. Terminating...",
                count,
            )
            os._exit(PNG_LOST_CONN_TO_PARENT)

        @self.m_ipc_server.on_shutdown
        async def _shutdown_handler(args: dict) -> Dict[str, Any]:
            reason = args.get("reason", "N/A")
            self.m_logger.info("Shutting down. Reason: %s", reason)
            self.m_app.close()
            return {"status": "success"}

        @self.m_ipc_server.on_get_stats
        async def _handle_get_stats(_args: dict) -> Dict[str, Any]:
            return {
                "status": "success",
                "stats": self.m_app.get_stats(),
            }

        @self.m_ipc_server.on("set-enabled")
        async def _handle_set_enabled(args: dict) -> Dict[str, Any]:
            enabled = _bool_arg(args.get("enabled"), True)
            announce = _bool_arg(args.get("announce"), True)
            changed = self.m_app.set_enabled(enabled, announce=announce, source="launcher")
            return {
                "status": "success",
                "enabled": self.m_app.enabled,
                "changed": changed,
            }

        @self.m_ipc_server.on("toggle-enabled")
        async def _handle_toggle_enabled(args: dict) -> Dict[str, Any]:
            announce = _bool_arg(args.get("announce"), True)
            changed = self.m_app.set_enabled(
                not self.m_app.enabled,
                announce=announce,
                source="launcher",
            )
            return {
                "status": "success",
                "enabled": self.m_app.enabled,
                "changed": changed,
            }

        @self.m_ipc_server.on("speak-test")
        async def _handle_speak_test(args: dict) -> Dict[str, Any]:
            text = str(args.get("text") or "Radio check.").strip() or "Radio check."
            self.m_app.queue_system_announcement(text, "race-engineer-radio-check")
            return {
                "status": "success",
                "enabled": self.m_app.enabled,
                "voice-queue-size": self.m_app.get_stats().get("voice-queue-size", 0),
            }

        @self.m_ipc_server.on("ask-text")
        async def _handle_ask_text(args: dict) -> Dict[str, Any]:
            question = str(args.get("question") or "").strip()
            if not question:
                return {
                    "status": "error",
                    "message": "Question cannot be empty",
                }
            answer = await self.m_app.ask_text_question(question, source="launcher")
            return {
                "status": "success",
                "answer": {
                    "ok": answer.ok,
                    "question": answer.question,
                    "text": answer.answer,
                    "source": answer.source,
                    "focus": answer.focus,
                    "error": answer.error,
                    "metrics": answer.metrics or {},
                },
                "enabled": self.m_app.enabled,
                "voice-queue-size": self.m_app.get_stats().get("voice-queue-size", 0),
            }

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------

def init_ipc_task(logger: logging.Logger, app: RaceEngineerApp, tasks: List[asyncio.Task]) -> None:
    """Initialize launcher management IPC for the race engineer process."""

    ipc_server = RaceEngineerIpc(logger, app)
    tasks.append(asyncio.create_task(ipc_server.run(), name="Race Engineer IPC Server"))


def _bool_arg(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
