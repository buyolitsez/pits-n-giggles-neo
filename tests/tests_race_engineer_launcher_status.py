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

from lib.race_engineer import (
    race_engineer_launcher_status_from_stats,
    race_engineer_launcher_status_is_attention,
)


class TestRaceEngineerLauncherStatus(unittest.TestCase):
    def test_empty_stats_fall_back_to_running(self):
        self.assertEqual(race_engineer_launcher_status_from_stats({}), "Running")
        self.assertEqual(race_engineer_launcher_status_from_stats(None), "Running")

    def test_maps_assistant_runtime_statuses_to_short_launcher_labels(self):
        cases = {
            "online": "Online",
            "waiting-for-telemetry": "No Telemetry",
            "listening": "Listening",
            "speaking": "Speaking",
            "voice-queued": "Queued",
            "muted": "Muted",
            "voice-error": "Voice Error",
            "speech-error": "Speech Error",
            "question-error": "Question Error",
        }

        for assistant_status, expected in cases.items():
            with self.subTest(assistant_status=assistant_status):
                self.assertEqual(
                    race_engineer_launcher_status_from_stats({
                        "assistant-status": assistant_status,
                        "enabled": True,
                    }),
                    expected,
                )

    def test_muted_legacy_stats_still_show_muted(self):
        self.assertEqual(
            race_engineer_launcher_status_from_stats({"enabled": False}),
            "Muted",
        )

    def test_unknown_status_falls_back_to_running(self):
        self.assertEqual(
            race_engineer_launcher_status_from_stats({
                "assistant-status": "custom-state",
                "enabled": True,
            }),
            "Running",
        )

    def test_attention_helper_flags_only_error_statuses(self):
        self.assertTrue(race_engineer_launcher_status_is_attention({"assistant-status": "voice-error"}))
        self.assertTrue(race_engineer_launcher_status_is_attention({"assistant-status": "speech-error"}))
        self.assertTrue(race_engineer_launcher_status_is_attention({"assistant-status": "question-error"}))
        self.assertFalse(race_engineer_launcher_status_is_attention({"assistant-status": "listening"}))
