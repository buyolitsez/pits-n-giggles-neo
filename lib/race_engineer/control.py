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
from typing import Any, Dict, Optional, Protocol

from lib.inter_task_communicator import AsyncInterTaskCommunicator

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

RACE_ENGINEER_CONTROL_TOPIC = "race-engineer-control"
RACE_ENGINEER_PTT_CONTROL_TOPIC = "race-engineer-ptt-control"
RACE_ENGINEER_TOGGLE_ACTION_FIELD = "race_engineer_toggle_udp_action_code"
RACE_ENGINEER_PUSH_TO_TALK_ACTION_FIELD = "race_engineer_push_to_talk_udp_action_code"

# -------------------------------------- CLASSES -----------------------------------------------------------------------


class RaceEngineerControlPublisher(Protocol):
    """Protocol for pub/sub publishers used by the backend bridge."""

    async def publish(self, topic: str, data: Dict[str, Any]) -> None:
        """Publish one control message."""


class UdpHoldActionTracker:
    """Track press/release transitions for UDP actions used as hold controls."""

    def __init__(self) -> None:
        self._states: Dict[str, bool] = {}

    def update(self, key: str, is_pressed: bool) -> Optional[str]:
        """Return 'pressed' or 'released' only when the hold state changes."""

        was_pressed = self._states.get(key, False)
        if is_pressed == was_pressed:
            return None
        self._states[key] = is_pressed
        return "pressed" if is_pressed else "released"

    def clear(self, key: Optional[str] = None) -> None:
        """Clear one hold state or all hold states."""

        if key is None:
            self._states.clear()
        else:
            self._states.pop(key, None)


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def race_engineer_toggle_message(*, source: str = "udp_action") -> Dict[str, Any]:
    """Build the runtime message that toggles the race engineer."""

    return {
        "command": "toggle",
        "announce": True,
        "source": source,
    }


def race_engineer_push_to_talk_message(
        command: str,
        *,
        source: str = "udp_action") -> Dict[str, Any]:
    """Build a runtime push-to-talk lifecycle message."""

    return {
        "command": command,
        "source": source,
    }


async def forward_race_engineer_control_messages(
        publisher: RaceEngineerControlPublisher,
        shutdown_event: asyncio.Event,
        topic: str,
        *,
        communicator: Optional[AsyncInterTaskCommunicator] = None) -> None:
    """Forward local race engineer control queue messages to the pub/sub broker."""

    communicator = communicator or AsyncInterTaskCommunicator()
    while not shutdown_event.is_set():
        if message := await communicator.receive(topic):
            await publisher.publish(topic, message)
