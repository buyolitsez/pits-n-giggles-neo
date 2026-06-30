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

from lib.race_engineer import BoundedLatestVoiceQueue


class TestRaceEngineerVoiceQueue(unittest.IsolatedAsyncioTestCase):
    async def test_push_get_roundtrip(self):
        queue = BoundedLatestVoiceQueue(max_size=2)

        result = queue.push("callout-a")

        self.assertTrue(result.enqueued)
        self.assertFalse(result.dropped_oldest)
        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(await queue.get(), "callout-a")
        queue.task_done()

    async def test_full_queue_drops_oldest_and_keeps_latest(self):
        queue = BoundedLatestVoiceQueue(max_size=2)

        queue.push("old")
        queue.push("middle")
        result = queue.push("latest")

        self.assertTrue(result.enqueued)
        self.assertTrue(result.dropped_oldest)
        self.assertEqual(queue.qsize(), 2)
        self.assertEqual(await queue.get(), "middle")
        queue.task_done()
        self.assertEqual(await queue.get(), "latest")
        queue.task_done()

    async def test_max_size_is_clamped_to_one(self):
        queue = BoundedLatestVoiceQueue(max_size=0)

        queue.push("old")
        result = queue.push("latest")

        self.assertTrue(result.dropped_oldest)
        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(await queue.get(), "latest")
        queue.task_done()

    async def test_clear_drops_pending_items(self):
        queue = BoundedLatestVoiceQueue(max_size=3)
        queue.push("old")
        queue.push("middle")

        dropped = queue.clear()

        self.assertEqual(dropped, 2)
        self.assertEqual(queue.qsize(), 0)

    async def test_drop_matching_keeps_retained_items_in_order(self):
        queue = BoundedLatestVoiceQueue(max_size=4)
        queue.push({"id": "keep-a", "priority": "critical"})
        queue.push({"id": "drop-a", "priority": "warning"})
        queue.push({"id": "keep-b", "priority": "critical"})
        queue.push({"id": "drop-b", "priority": "info"})

        dropped = queue.drop_matching(lambda item: item["priority"] != "critical")

        self.assertEqual(dropped, 2)
        self.assertEqual(queue.qsize(), 2)
        self.assertEqual((await queue.get())["id"], "keep-a")
        queue.task_done()
        self.assertEqual((await queue.get())["id"], "keep-b")
        queue.task_done()


if __name__ == "__main__":
    unittest.main()
