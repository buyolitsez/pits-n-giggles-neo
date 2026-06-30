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

from copy import deepcopy
import unittest

from lib.race_engineer import RaceEngineerAnnouncer, RaceEngineerHistory
from tests.tests_mcp_race_engineer_brief import _snapshot


class TestRaceEngineerHistory(unittest.TestCase):
    def test_first_update_seeds_without_advice_by_default(self):
        history = RaceEngineerHistory()

        advice = history.update(_snapshot())

        self.assertEqual(advice, [])
        self.assertEqual(len(history.latest_laps(7)), 1)

    def test_new_player_lap_reports_catching_car_ahead(self):
        history = RaceEngineerHistory()
        history.update(_snapshot())

        advice = history.update(_next_lap_snapshot(
            player_lap_ms=90000,
            ahead_lap_ms=90500,
            behind_lap_ms=90200,
            gap_ahead_ms=800,
            gap_behind_ms=1600,
        ))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "pace-trend-catching-ahead")
        self.assertEqual(advice[0]["priority"], "advisory")
        self.assertIn("Lap 12", advice[0]["voice_callout"])
        self.assertIn("Faster by 0.5s", advice[0]["voice_callout"])
        self.assertIn("you 01:30.000", advice[0]["voice_callout"])
        self.assertIn("ahead 01:30.500", advice[0]["voice_callout"])
        self.assertEqual(advice[0]["metrics"]["last_lap_delta_to_ahead_ms"], -500)
        self.assertTrue(advice[0]["metrics"]["battle_window"])

    def test_new_player_lap_reports_threat_behind(self):
        history = RaceEngineerHistory()
        history.update(_snapshot())

        advice = history.update(_next_lap_snapshot(
            player_lap_ms=91000,
            ahead_lap_ms=90900,
            behind_lap_ms=90200,
            gap_ahead_ms=1300,
            gap_behind_ms=700,
        ))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "pace-trend-threat-behind")
        self.assertEqual(advice[0]["priority"], "warning")
        self.assertIn("gap 0.7s", advice[0]["voice_callout"])
        self.assertIn("behind 01:30.200", advice[0]["voice_callout"])

    def test_battle_ahead_reports_lap_times_when_pace_is_close(self):
        history = RaceEngineerHistory()
        history.update(_snapshot())

        advice = history.update(_next_lap_snapshot(
            player_lap_ms=90400,
            ahead_lap_ms=90500,
            behind_lap_ms=90900,
            gap_ahead_ms=900,
            gap_behind_ms=6200,
        ))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "pace-trend-battle-ahead")
        self.assertEqual(advice[0]["priority"], "advisory")
        self.assertIn("battle ahead", advice[0]["voice_callout"])
        self.assertIn("You 01:30.400", advice[0]["voice_callout"])
        self.assertIn("ahead 01:30.500", advice[0]["voice_callout"])
        self.assertEqual(advice[0]["metrics"]["gap_trend_ahead_ms"], -350)

    def test_losing_to_car_ahead_inside_battle_window_is_advisory(self):
        history = RaceEngineerHistory()
        history.update(_snapshot())

        advice = history.update(_next_lap_snapshot(
            player_lap_ms=91000,
            ahead_lap_ms=90500,
            behind_lap_ms=91400,
            gap_ahead_ms=4300,
            gap_behind_ms=6200,
        ))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "pace-trend-losing-ahead")
        self.assertEqual(advice[0]["priority"], "advisory")
        self.assertIn("Ahead quicker by 0.5s", advice[0]["voice_callout"])
        self.assertTrue(advice[0]["metrics"]["battle_window"])

    def test_battle_behind_reports_holding_when_no_ahead_callout(self):
        history = RaceEngineerHistory()
        history.update(_snapshot())

        advice = history.update(_next_lap_snapshot(
            player_lap_ms=90000,
            ahead_lap_ms=90100,
            behind_lap_ms=90500,
            gap_ahead_ms=6200,
            gap_behind_ms=900,
        ))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "pace-trend-holding-behind")
        self.assertEqual(advice[0]["priority"], "advisory")
        self.assertIn("car behind 01:30.500", advice[0]["voice_callout"])
        self.assertIn("Your lap 01:30.000", advice[0]["voice_callout"])
        self.assertEqual(advice[0]["metrics"]["gap_trend_behind_ms"], -900)

    def test_pace_to_car_ahead_includes_three_lap_rolling_average(self):
        history = RaceEngineerHistory()
        history.update(_snapshot())
        history.update(_next_lap_snapshot(
            current_lap=13,
            timestamp=456.0,
            player_lap_ms=90500,
            ahead_lap_ms=90700,
            behind_lap_ms=92000,
            gap_ahead_ms=1300,
            gap_behind_ms=7000,
        ))
        history.update(_next_lap_snapshot(
            current_lap=14,
            timestamp=466.0,
            player_lap_ms=90200,
            ahead_lap_ms=90600,
            behind_lap_ms=92100,
            gap_ahead_ms=1000,
            gap_behind_ms=7200,
        ))

        advice = history.update(_next_lap_snapshot(
            current_lap=15,
            timestamp=476.0,
            player_lap_ms=90000,
            ahead_lap_ms=90500,
            behind_lap_ms=92200,
            gap_ahead_ms=700,
            gap_behind_ms=7400,
        ))

        self.assertEqual(advice[0]["id"], "pace-trend-catching-ahead")
        self.assertIn("3-lap avg: you 01:30.233, ahead 01:30.600", advice[0]["voice_callout"])
        self.assertEqual(advice[0]["metrics"]["recent_lap_count_to_ahead"], 3)
        self.assertAlmostEqual(advice[0]["metrics"]["recent_avg_delta_to_ahead_ms"], -366.666, places=2)

    def test_announcer_uses_history_once_per_completed_lap(self):
        history = RaceEngineerHistory()
        announcer = RaceEngineerAnnouncer(
            min_priority="advisory",
            cooldown_seconds=20,
            history=history,
        )
        startup = announcer.process_snapshot(_snapshot(), now=100.0, focus="pace")
        self.assertEqual(startup, [])

        snapshot = _next_lap_snapshot(
            player_lap_ms=90000,
            ahead_lap_ms=90500,
            behind_lap_ms=90200,
            gap_ahead_ms=800,
            gap_behind_ms=1600,
        )
        first = announcer.process_snapshot(snapshot, now=110.0, focus="pace")
        second = announcer.process_snapshot(snapshot, now=111.0, focus="pace")

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].advice_id, "pace-trend-catching-ahead")
        self.assertEqual(second, [])

    def test_session_change_clears_seen_laps_and_reseeds(self):
        history = RaceEngineerHistory()
        history.update(_snapshot())

        new_session = _snapshot()
        new_session["session-uid"] = 999
        new_session["timestamp"] = 999.0
        new_session["table-entries"][1]["lap-info"]["last-lap"]["lap-time-ms"] = 88000

        advice = history.update(new_session)

        self.assertEqual(advice, [])
        self.assertEqual(len(history.latest_laps(7)), 1)
        self.assertEqual(history.latest_laps(7)[0].lap_time_ms, 88000)

    def test_malformed_history_update_is_ignored(self):
        history = RaceEngineerHistory()

        self.assertEqual(history.update({"table-entries": "bad"}), [])
        self.assertEqual(history.update(None), [])


def _next_lap_snapshot(
    *,
    current_lap=13,
    timestamp=456.0,
    player_lap_ms,
    ahead_lap_ms,
    behind_lap_ms,
    gap_ahead_ms,
    gap_behind_ms,
):
    snapshot = deepcopy(_snapshot())
    snapshot["current-lap"] = current_lap
    snapshot["timestamp"] = timestamp
    _set_row_lap(snapshot["table-entries"][0], current_lap=current_lap, lap_time_ms=ahead_lap_ms)
    _set_row_lap(snapshot["table-entries"][1], current_lap=current_lap, lap_time_ms=player_lap_ms)
    _set_row_lap(snapshot["table-entries"][2], current_lap=current_lap, lap_time_ms=behind_lap_ms)
    snapshot["table-entries"][1]["delta-info"]["delta-to-car-in-front"] = gap_ahead_ms
    snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = gap_behind_ms
    return snapshot


def _set_row_lap(row, *, current_lap, lap_time_ms):
    row["lap-info"]["current-lap"] = current_lap
    row["lap-info"]["last-lap"]["lap-time-ms"] = lap_time_ms
    row["lap-info"]["last-lap"]["is-valid"] = True
