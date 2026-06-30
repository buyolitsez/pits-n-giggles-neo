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

from lib.race_engineer import RaceEngineerAnnouncer, RaceEngineerHistory
from tests.tests_mcp_race_engineer_brief import _snapshot


class TestRaceEngineerAnnouncer(unittest.TestCase):
    def test_filters_below_min_priority(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = 0.8
        announcer = RaceEngineerAnnouncer(min_priority="warning")

        announcements = announcer.process_snapshot(snapshot, now=100.0, focus="fuel")

        self.assertEqual(announcements, [])

    def test_emits_warning_or_higher(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.3
        announcer = RaceEngineerAnnouncer(min_priority="warning")

        announcements = announcer.process_snapshot(snapshot, now=100.0, focus="fuel")

        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0].advice_id, "fuel-small-deficit")
        self.assertEqual(announcements[0].priority, "warning")
        self.assertIn("Fuel minus", announcements[0].text)

    def test_suppresses_repeated_cooldown_key(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["rear-right-wear"] = 82.0
        announcer = RaceEngineerAnnouncer(min_priority="critical", cooldown_seconds=20)

        first = announcer.process_snapshot(snapshot, now=100.0, focus="tyres")
        second = announcer.process_snapshot(snapshot, now=110.0, focus="tyres")
        third = announcer.process_snapshot(snapshot, now=121.0, focus="tyres")

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(third), 1)

    def test_invalid_priority_defaults_to_warning(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = 0.8
        announcer = RaceEngineerAnnouncer(min_priority="banana")

        announcements = announcer.process_snapshot(snapshot, now=100.0, focus="fuel")

        self.assertEqual(announcements, [])

    def test_driving_coach_focus_filters_other_advice_categories(self):
        announcer = RaceEngineerAnnouncer(min_priority="advisory")

        announcements = announcer.process_advice_items([
            _advice("fuel-small-deficit", "fuel"),
            _advice("driving-coach-overlap", "driving_coach"),
        ], now=100.0, focus="driving_coach")

        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0].category, "driving_coach")

    def test_history_mode_keeps_live_battle_callout_when_no_lap_trend(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["delta-info"]["delta-to-car-in-front"] = 850
        snapshot["table-entries"][0]["lap-info"]["last-lap"]["lap-time-ms"] = 91200
        snapshot["table-entries"][1]["lap-info"]["last-lap"]["lap-time-ms"] = 90400
        announcer = RaceEngineerAnnouncer(
            min_priority="advisory",
            history=RaceEngineerHistory(),
        )

        announcements = announcer.process_snapshot(snapshot, now=100.0, focus="pace")

        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0].advice_id, "pace-battle-attack-drs")


def _advice(advice_id, category):
    return {
        "id": advice_id,
        "category": category,
        "priority": "advisory",
        "title": "Advice",
        "message": "Use this advice.",
        "voice_callout": "Use this advice.",
        "cooldown_key": advice_id,
        "evidence": ["test"],
        "metrics": {},
    }


if __name__ == "__main__":
    unittest.main()
