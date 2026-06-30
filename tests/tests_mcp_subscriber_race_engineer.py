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

import logging
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from apps.mcp_server import state
from apps.mcp_server.subscriber import McpSubscriber


class TestMcpSubscriberRaceEngineer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        state.state_data.clear()

    def tearDown(self):
        state.state_data.clear()

    async def test_trace_update_route_stores_driving_coach_advice_for_mcp_tools(self):
        with _fake_ipc_module():
            subscriber = McpSubscriber(
                logging.getLogger("tests_mcp_subscriber_race_engineer"),
                port=4242,
                timeout=10.0,
            )

        route = subscriber.m_ipc_sub.routes["race-engineer-trace-update"]
        for sample in _trace_lap_samples(lap=1, speed=220, throttle=80, brake=0):
            await route(sample)
        await route(_trace_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _trace_lap_samples(lap=2, speed=219, throttle=75, brake=0, timestamp_offset=20.0):
            if sample["lap-distance-m"] in {300, 310}:
                sample["throttle-pct"] = 55
                sample["brake-pct"] = 55
                sample["speed-kmph"] = 190
            await route(sample)
        await route(_trace_sample(lap=3, distance=0, timestamp=40.0))

        advice_entry = state.get_state_data("race-engineer-driving-advice-update")
        self.assertIsNotNone(advice_entry)
        self.assertEqual(advice_entry.data["source"], "race-engineer-trace-update")
        self.assertEqual(advice_entry.data["session-uid"], "abc")
        self.assertEqual(advice_entry.data["last-completed-lap"], 2)
        self.assertGreaterEqual(advice_entry.data["reference-lap-count"], 1)
        self.assertEqual(advice_entry.data["advice"][0]["category"], "driving_coach")
        self.assertTrue(subscriber.get_stats()["trace-reference-laps"] >= 1)

    async def test_trace_session_change_clears_stale_driving_coach_advice(self):
        with _fake_ipc_module():
            subscriber = McpSubscriber(
                logging.getLogger("tests_mcp_subscriber_race_engineer"),
                port=4242,
                timeout=10.0,
            )

        route = subscriber.m_ipc_sub.routes["race-engineer-trace-update"]
        for sample in _trace_lap_samples(lap=1, speed=220, throttle=80, brake=0):
            await route(sample)
        await route(_trace_sample(lap=2, distance=0, timestamp=20.0))
        for sample in _trace_lap_samples(lap=2, speed=190, throttle=55, brake=55, timestamp_offset=20.0):
            await route(sample)
        await route(_trace_sample(lap=3, distance=0, timestamp=40.0))
        self.assertIsNotNone(state.get_state_data("race-engineer-driving-advice-update"))

        await route(_trace_sample(lap=1, distance=0, timestamp=100.0, session_uid="new-session"))

        self.assertIsNone(state.get_state_data("race-engineer-driving-advice-update"))
        self.assertEqual(subscriber.m_trace_session_uid, "new-session")

    async def test_clean_completed_lap_clears_previous_driving_coach_advice(self):
        with _fake_ipc_module():
            subscriber = McpSubscriber(
                logging.getLogger("tests_mcp_subscriber_race_engineer"),
                port=4242,
                timeout=10.0,
            )

        route = subscriber.m_ipc_sub.routes["race-engineer-trace-update"]
        for sample in _trace_lap_samples(lap=1, speed=220, throttle=80, brake=0):
            await route(sample)
        await route(_trace_sample(lap=2, distance=0, timestamp=20.0))
        for sample in _trace_lap_samples(lap=2, speed=219, throttle=75, brake=0, timestamp_offset=20.0):
            if sample["lap-distance-m"] in {300, 310}:
                sample["throttle-pct"] = 55
                sample["brake-pct"] = 55
                sample["speed-kmph"] = 190
            await route(sample)
        await route(_trace_sample(lap=3, distance=0, timestamp=40.0))
        self.assertTrue(state.get_state_data("race-engineer-driving-advice-update").data["advice"])

        for sample in _trace_lap_samples(lap=3, speed=220, throttle=80, brake=0, timestamp_offset=40.0):
            await route(sample)
        await route(_trace_sample(lap=4, distance=0, timestamp=60.0))

        advice_entry = state.get_state_data("race-engineer-driving-advice-update")
        self.assertIsNotNone(advice_entry)
        self.assertEqual(advice_entry.data["last-completed-lap"], 3)
        self.assertEqual(advice_entry.data["advice"], [])


class _FakeSubscriber:
    def __init__(self, *, port, logger):
        self.port = port
        self.logger = logger
        self.routes = {}
        self.closed = False

    def route(self, topic):
        def _decorator(handler):
            self.routes[topic] = handler
            return handler
        return _decorator

    def on_connect(self, handler):
        return handler

    def on_disconnect(self, handler):
        return handler

    async def run(self):
        return None

    def close(self):
        self.closed = True

    def get_stats(self):
        return {"port": self.port, "routes": sorted(self.routes)}


class _FakeIpcModule(types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.IpcSubscriberAsync = _FakeSubscriber


@contextmanager
def _fake_ipc_module():
    with patch.dict(sys.modules, {"lib.ipc": _FakeIpcModule()}):
        yield


def _trace_lap_samples(*, lap, speed, throttle, brake, timestamp_offset=0.0):
    return [
        _trace_sample(
            lap=lap,
            distance=distance,
            timestamp=timestamp_offset + index,
            speed=speed,
            throttle=throttle,
            brake=brake,
        )
        for index, distance in enumerate(range(0, 321, 10))
    ]


def _trace_sample(*, lap, distance, timestamp, speed=210, throttle=80, brake=0, session_uid="abc"):
    return {
        "ok": True,
        "session-uid": session_uid,
        "current-lap": lap,
        "timestamp": timestamp,
        "circuit-enum-name": "Spa",
        "current-lap-invalid": False,
        "lap-distance-m": distance,
        "circuit-length-m": 320,
        "sector": "3" if distance >= 300 else "2",
        "speed-kmph": speed,
        "throttle-pct": throttle,
        "brake-pct": brake,
        "steering-pct": -12,
        "gear": 6,
        "drs": 0,
        "segment-label": None,
        "segment-voice-label": None,
    }


if __name__ == "__main__":
    unittest.main()
