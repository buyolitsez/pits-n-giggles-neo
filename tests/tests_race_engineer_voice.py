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

from lib.race_engineer import DryRunVoiceEngine, NullVoiceEngine


class TestRaceEngineerVoice(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_records_message_and_metadata(self):
        engine = DryRunVoiceEngine()

        result = await engine.speak(
            "Fuel minus three tenths.",
            metadata={"priority": "warning", "category": "fuel"},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "dry_run")
        self.assertEqual(len(engine.messages), 1)
        self.assertEqual(engine.messages[0]["text"], "Fuel minus three tenths.")
        self.assertEqual(engine.messages[0]["metadata"]["category"], "fuel")

    async def test_null_voice_drops_message_successfully(self):
        engine = NullVoiceEngine()

        result = await engine.speak("Do not speak this.")

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "disabled")
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
