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
from dataclasses import dataclass
from typing import Any, Callable

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VoiceQueuePushResult:
    """Result of pushing one callout into the bounded voice queue."""

    enqueued: bool
    dropped_oldest: bool = False


class BoundedLatestVoiceQueue:
    """Small async queue that keeps the latest callouts when voice output is slow."""

    def __init__(self, *, max_size: int = 3) -> None:
        self.max_size = max(1, max_size)
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=self.max_size)

    def push(self, item: Any) -> VoiceQueuePushResult:
        """Push an item, dropping the oldest queued item if the queue is full."""

        dropped_oldest = False
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                dropped_oldest = True
            except asyncio.QueueEmpty:
                dropped_oldest = False

        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            return VoiceQueuePushResult(enqueued=False, dropped_oldest=dropped_oldest)

        return VoiceQueuePushResult(enqueued=True, dropped_oldest=dropped_oldest)

    async def get(self) -> Any:
        """Wait for and return the next queued item."""

        return await self._queue.get()

    def task_done(self) -> None:
        """Mark the most recently returned item as handled."""

        self._queue.task_done()

    def clear(self) -> int:
        """Drop all pending queued items and return the number dropped."""

        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                dropped += 1
            except asyncio.QueueEmpty:
                return dropped

    def drop_matching(self, predicate: Callable[[Any], bool]) -> int:
        """Drop queued items matching predicate and keep the rest in order."""

        dropped = 0
        retained = []
        while True:
            try:
                item = self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
            if predicate(item):
                dropped += 1
            else:
                retained.append(item)

        for item in retained:
            self._queue.put_nowait(item)
        return dropped

    def qsize(self) -> int:
        """Return the number of queued items."""

        return self._queue.qsize()
