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

# pylint: skip-file

import unittest
import sys
import types
from dataclasses import dataclass
from unittest.mock import patch

from apps.race_engineer.mgmt import RaceEngineerIpc


class TestRaceEngineerMgmtIpc(unittest.IsolatedAsyncioTestCase):
    async def test_set_enabled_accepts_false_string_and_suppresses_announcement(self):
        app = _FakeRaceEngineerApp(enabled=True)
        ipc = _build_ipc(app)

        rsp = await ipc.m_ipc_server._route_handlers["set-enabled"]({
            "enabled": "false",
            "announce": "false",
        })

        self.assertEqual(rsp, {
            "status": "success",
            "enabled": False,
            "changed": True,
        })
        self.assertEqual(app.set_enabled_calls, [{
            "enabled": False,
            "announce": False,
            "source": "launcher",
        }])

    async def test_toggle_enabled_flips_state_and_announces_by_default(self):
        app = _FakeRaceEngineerApp(enabled=False)
        ipc = _build_ipc(app)

        rsp = await ipc.m_ipc_server._route_handlers["toggle-enabled"]({})

        self.assertEqual(rsp["status"], "success")
        self.assertTrue(rsp["enabled"])
        self.assertTrue(rsp["changed"])
        self.assertEqual(app.set_enabled_calls, [{
            "enabled": True,
            "announce": True,
            "source": "launcher",
        }])

    async def test_speak_test_queues_radio_check(self):
        app = _FakeRaceEngineerApp(enabled=True)
        ipc = _build_ipc(app)

        rsp = await ipc.m_ipc_server._route_handlers["speak-test"]({"text": "  Radio check.  "})

        self.assertEqual(rsp, {
            "status": "success",
            "enabled": True,
            "voice-queue-size": 1,
        })
        self.assertEqual(app.system_announcements, [{
            "text": "Radio check.",
            "advice_id": "race-engineer-radio-check",
        }])

    async def test_speak_test_uses_default_message_when_blank(self):
        app = _FakeRaceEngineerApp(enabled=True)
        ipc = _build_ipc(app)

        rsp = await ipc.m_ipc_server._route_handlers["speak-test"]({"text": "   "})

        self.assertEqual(rsp["voice-queue-size"], 1)
        self.assertEqual(app.system_announcements[0]["text"], "Radio check.")

    async def test_ask_text_rejects_empty_question(self):
        app = _FakeRaceEngineerApp(enabled=True)
        ipc = _build_ipc(app)

        rsp = await ipc.m_ipc_server._route_handlers["ask-text"]({"question": "   "})

        self.assertEqual(rsp, {
            "status": "error",
            "message": "Question cannot be empty",
        })
        self.assertEqual(app.text_questions, [])

    async def test_ask_text_answers_and_returns_spoken_answer_contract(self):
        app = _FakeRaceEngineerApp(enabled=True)
        ipc = _build_ipc(app)

        rsp = await ipc.m_ipc_server._route_handlers["ask-text"]({"question": "  how is fuel?  "})

        self.assertEqual(rsp["status"], "success")
        self.assertTrue(rsp["enabled"])
        self.assertEqual(rsp["voice-queue-size"], 0)
        self.assertEqual(rsp["answer"], {
            "ok": True,
            "question": "how is fuel?",
            "text": "Fuel is safe.",
            "source": "launcher",
            "focus": "fuel",
            "error": None,
            "metrics": {"advice_count": 1},
        })
        self.assertEqual(app.text_questions, [{
            "question": "how is fuel?",
            "source": "launcher",
        }])

    async def test_shutdown_route_closes_app(self):
        app = _FakeRaceEngineerApp(enabled=True)
        ipc = _build_ipc(app)

        rsp = await ipc.m_ipc_server._shutdown_handler({"reason": "test"})

        self.assertEqual(rsp, {"status": "success"})
        self.assertTrue(app.closed)


def _build_ipc(app: "_FakeRaceEngineerApp") -> RaceEngineerIpc:
    fake_ipc_module = types.SimpleNamespace(IpcServerAsync=_FakeIpcServerAsync)
    with patch.dict(sys.modules, {"lib.ipc": fake_ipc_module}):
        with patch("apps.race_engineer.mgmt.report_ipc_port_from_child"):
            return RaceEngineerIpc(_SilentLogger(), app)


class _FakeIpcServerAsync:
    def __init__(self, *args, **kwargs):
        del args, kwargs
        self.port = 54545
        self._route_handlers = {}
        self._shutdown_handler = None
        self._get_stats_handler = None
        self._heartbeat_missed_handler = None

    def on(self, command):
        def _decorator(handler):
            self._route_handlers[command] = handler
            return handler
        return _decorator

    def on_shutdown(self, handler):
        self._shutdown_handler = handler
        return handler

    def on_get_stats(self, handler):
        self._get_stats_handler = handler
        return handler

    def on_heartbeat_missed(self, handler):
        self._heartbeat_missed_handler = handler
        return handler

    async def run(self):
        return None


class _FakeRaceEngineerApp:
    def __init__(self, *, enabled):
        self.enabled = enabled
        self.closed = False
        self.set_enabled_calls = []
        self.system_announcements = []
        self.text_questions = []

    def close(self):
        self.closed = True

    def get_stats(self):
        return {
            "enabled": self.enabled,
            "voice-queue-size": len(self.system_announcements),
        }

    def set_enabled(self, enabled, *, announce=True, source="control"):
        changed = bool(enabled) != self.enabled
        self.enabled = bool(enabled)
        self.set_enabled_calls.append({
            "enabled": self.enabled,
            "announce": announce,
            "source": source,
        })
        return changed

    def queue_system_announcement(self, text, advice_id="race-engineer-system"):
        self.system_announcements.append({
            "text": text,
            "advice_id": advice_id,
        })

    async def ask_text_question(self, question, *, source="question"):
        self.text_questions.append({
            "question": question,
            "source": source,
        })
        return _FakeAnswer(
            ok=True,
            question=question,
            answer="Fuel is safe.",
            source=source,
            focus="fuel",
            error=None,
            metrics={"advice_count": 1},
        )


@dataclass(frozen=True)
class _FakeAnswer:
    ok: bool
    question: str
    answer: str
    source: str
    focus: str
    error: str | None
    metrics: dict


class _SilentLogger:
    def info(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None
