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

import asyncio
import unittest

from lib.race_engineer import (
    RACE_ENGINEER_CONTROL_TOPIC,
    RACE_ENGINEER_PTT_CONTROL_TOPIC,
    RACE_ENGINEER_PUSH_TO_TALK_ACTION_FIELD,
    RACE_ENGINEER_TOGGLE_ACTION_FIELD,
    UdpHoldActionTracker,
    forward_race_engineer_control_messages,
    race_engineer_push_to_talk_message,
    race_engineer_toggle_message,
)


class TestRaceEngineerUdpActionBridge(unittest.IsolatedAsyncioTestCase):
    def test_udp_action_contract_names_are_stable(self):
        self.assertEqual(RACE_ENGINEER_TOGGLE_ACTION_FIELD, "race_engineer_toggle_udp_action_code")
        self.assertEqual(RACE_ENGINEER_PUSH_TO_TALK_ACTION_FIELD, "race_engineer_push_to_talk_udp_action_code")
        self.assertEqual(RACE_ENGINEER_CONTROL_TOPIC, "race-engineer-control")
        self.assertEqual(RACE_ENGINEER_PTT_CONTROL_TOPIC, "race-engineer-ptt-control")

    def test_control_message_builders_match_race_engineer_routes(self):
        self.assertEqual(race_engineer_toggle_message(source="udp_action"), {
            "command": "toggle",
            "announce": True,
            "source": "udp_action",
        })
        self.assertEqual(
            race_engineer_push_to_talk_message("start", source="udp_action"),
            {"command": "start", "source": "udp_action"},
        )
        self.assertEqual(
            race_engineer_push_to_talk_message("stop", source="udp_action"),
            {"command": "stop", "source": "udp_action"},
        )

    def test_udp_hold_action_tracker_emits_only_press_release_edges(self):
        tracker = UdpHoldActionTracker()

        self.assertEqual(tracker.update("ptt", True), "pressed")
        self.assertIsNone(tracker.update("ptt", True))
        self.assertEqual(tracker.update("ptt", False), "released")
        self.assertIsNone(tracker.update("ptt", False))

    async def test_control_bridge_publishes_internal_messages_to_broker_topic(self):
        communicator = _FakeCommunicator()
        publisher = _FakePublisher()
        shutdown_event = asyncio.Event()
        task = asyncio.create_task(
            forward_race_engineer_control_messages(
                publisher,
                shutdown_event,
                RACE_ENGINEER_CONTROL_TOPIC,
                communicator=communicator,
            )
        )

        await communicator.send(
            RACE_ENGINEER_CONTROL_TOPIC,
            {"command": "toggle", "source": "test"},
        )
        await _wait_for(lambda: bool(publisher.published))
        shutdown_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.assertEqual(publisher.published, [
            (RACE_ENGINEER_CONTROL_TOPIC, {"command": "toggle", "source": "test"}),
        ])

    async def test_control_bridge_publishes_every_queued_message(self):
        communicator = _FakeCommunicator()
        publisher = _FakePublisher()
        shutdown_event = asyncio.Event()
        task = asyncio.create_task(
            forward_race_engineer_control_messages(
                publisher,
                shutdown_event,
                RACE_ENGINEER_CONTROL_TOPIC,
                communicator=communicator,
            )
        )

        messages = [
            {"command": "toggle", "source": "test", "seq": 1},
            {"command": "toggle", "source": "test", "seq": 2},
            {"command": "toggle", "source": "test", "seq": 3},
        ]
        for message in messages:
            await communicator.send(RACE_ENGINEER_CONTROL_TOPIC, message)

        await _wait_for(lambda: len(publisher.published) == len(messages))
        shutdown_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.assertEqual(
            publisher.published,
            [(RACE_ENGINEER_CONTROL_TOPIC, message) for message in messages],
        )

    async def test_control_bridge_does_not_drop_empty_payloads(self):
        communicator = _FakeCommunicator()
        publisher = _FakePublisher()
        shutdown_event = asyncio.Event()
        task = asyncio.create_task(
            forward_race_engineer_control_messages(
                publisher,
                shutdown_event,
                RACE_ENGINEER_CONTROL_TOPIC,
                communicator=communicator,
            )
        )

        await communicator.send(RACE_ENGINEER_CONTROL_TOPIC, {})
        await _wait_for(lambda: bool(publisher.published))
        shutdown_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.assertEqual(publisher.published, [(RACE_ENGINEER_CONTROL_TOPIC, {})])


async def _wait_for(predicate, *, timeout: float = 0.5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("Timed out waiting for condition")
        await asyncio.sleep(0.01)


class _FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, data):
        self.published.append((topic, data))


class _FakeCommunicator:
    def __init__(self):
        self._queue = asyncio.Queue()

    async def send(self, _queue_name, message):
        await self._queue.put(message)

    async def receive(self, _queue_name, timeout=None):
        try:
            if timeout is None:
                return await self._queue.get()
            return await asyncio.wait_for(self._queue.get(), timeout)
        except asyncio.TimeoutError:
            return None


if __name__ == "__main__":
    unittest.main()
