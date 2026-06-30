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
import time
import unittest

from apps.mcp_server import state
from apps.mcp_server.mcp_server.tools.get_race_engineer_brief import (
    get_race_engineer_brief,
)
from lib.race_engineer import build_race_engineer_brief


class TestRaceEngineerBrief(unittest.TestCase):
    def setUp(self):
        state.state_data.clear()
        state.set_state_data("connected", True)
        self.logger = logging.getLogger("tests_mcp_race_engineer_brief")

    def tearDown(self):
        state.state_data.clear()

    def test_unavailable_without_snapshot(self):
        rsp = get_race_engineer_brief(self.logger)

        self.assertFalse(rsp["available"])
        self.assertTrue(rsp["connected"])
        self.assertFalse(rsp["ok"])

    def test_unavailable_without_connected_state(self):
        state.delete_state_data("connected")

        rsp = get_race_engineer_brief(self.logger)

        self.assertFalse(rsp["available"])
        self.assertFalse(rsp["connected"])
        self.assertFalse(rsp["ok"])

    def test_tyre_warning_from_player_snapshot(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["rear-right-wear"] = 82.4
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="tyres")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"][0]["id"], "tyres-wear")
        self.assertEqual(rsp["advice"][0]["priority"], "critical")
        self.assertIn("Puncture risk", rsp["advice"][0]["message"])
        _assert_no_raw_ms(self, rsp["advice"])

    def test_fuel_deficit_from_player_snapshot(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="fuel")

        self.assertEqual(rsp["advice"][0]["id"], "fuel-critical-deficit")
        self.assertEqual(rsp["advice"][0]["priority"], "critical")
        self.assertIn("Lift and coast", rsp["advice"][0]["message"])
        _assert_no_raw_ms(self, rsp["advice"])

    def test_fuel_over_target_warns_before_deficit_is_critical(self):
        snapshot = _snapshot()
        fuel = snapshot["table-entries"][1]["fuel-info"]
        fuel["surplus-laps-png"] = 0.05
        fuel["target-fuel-rate-next-lap"] = 2.00
        fuel["last-lap-fuel-used"] = 2.22
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="fuel")

        self.assertEqual(rsp["advice"][0]["id"], "fuel-over-target")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("lift and coast", rsp["advice"][0]["message"].lower())
        self.assertAlmostEqual(rsp["advice"][0]["metrics"]["fuel_burn_delta_kg"], 0.22)
        self.assertIn("fuel-over-target", rsp["agent_context"]["categories"]["fuel"]["advice_ids"])
        self.assertIn(
            "Last lap fuel burn: 0.22kg over target",
            rsp["agent_context"]["categories"]["fuel"]["facts"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_ers_defence_when_car_behind_inside_drs(self):
        snapshot = _snapshot()
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 850
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="ers")

        self.assertEqual(rsp["advice"][0]["id"], "ers-defend-drs")
        self.assertIn("within DRS", rsp["advice"][0]["message"])
        self.assertEqual(rsp["nearby"]["car_behind"]["gap"], "0.8s")
        _assert_no_raw_ms(self, rsp["advice"])

    def test_ers_defence_warns_when_battery_is_low(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["ers-info"]["ers-percent-float"] = 12.0
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 850
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="ers")

        self.assertEqual(rsp["advice"][0]["id"], "ers-defend-low-battery")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("battery is low", rsp["advice"][0]["voice_callout"].lower())
        self.assertEqual(rsp["advice"][0]["metrics"]["ers_percent"], 12.0)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_ers_attack_window_harvests_when_battery_is_low(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["ers-info"]["ers-percent-float"] = 18.0
        snapshot["table-entries"][1]["delta-info"]["delta-to-car-in-front"] = 850
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="ers")

        self.assertEqual(rsp["advice"][0]["id"], "ers-attack-harvest")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("harvest", rsp["advice"][0]["voice_callout"].lower())
        self.assertEqual(rsp["advice"][0]["metrics"]["gap_ahead_ms"], 850)
        self.assertEqual(rsp["agent_context"]["categories"]["ers"]["metrics"]["ers_percent"], 18.0)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_damage_warning_from_player_snapshot(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["damage-info"]["floor-damage"] = 28
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="damage")

        self.assertEqual(rsp["advice"][0]["id"], "damage-aero")
        self.assertEqual(rsp["advice"][0]["priority"], "critical")
        self.assertIn("Floor damage", rsp["advice"][0]["message"])
        _assert_no_raw_ms(self, rsp["advice"])

    def test_damage_fault_takes_priority_over_aero_damage(self):
        snapshot = _snapshot()
        damage = snapshot["table-entries"][1]["damage-info"]
        damage["floor-damage"] = 28
        damage["drs-fault"] = True
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="damage")

        self.assertEqual(rsp["advice"][0]["id"], "damage-drs-fault")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("DRS", rsp["advice"][0]["message"])
        self.assertIn("damage-drs-fault", rsp["agent_context"]["categories"]["damage"]["advice_ids"])
        self.assertIn("Faults reported: DRS fault", rsp["agent_context"]["categories"]["damage"]["facts"])
        _assert_no_raw_ms(self, rsp["advice"])

    def test_powertrain_damage_warns_before_engine_failure(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["damage-info"]["engine-ice-wear"] = 72
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="damage")

        self.assertEqual(rsp["advice"][0]["id"], "damage-powertrain-engine-ice")
        self.assertEqual(rsp["advice"][0]["priority"], "critical")
        self.assertIn("Short-shift", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["worst_part"], "engine-ice")
        self.assertEqual(
            rsp["agent_context"]["categories"]["damage"]["metrics"]["worst_powertrain_part"],
            "engine-ice",
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_weather_rain_arriving_from_forecast(self):
        snapshot = _snapshot()
        snapshot["weather-forecast-samples"] = [
            _weather_sample(0, "Overcast", rain=20, track_temp=36, air_temp=25),
            _weather_sample(10, "Light Rain", rain=65, track_temp=33, air_temp=22),
        ]
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="weather")

        self.assertEqual(rsp["advice"][0]["id"], "weather-rain-arriving")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("Rain expected", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["time_offset_min"], 10.0)
        self.assertEqual(rsp["advice"][0]["metrics"]["rain_probability_pct"], 65.0)
        self.assertIn("weather", rsp["agent_prompt_specs"])
        self.assertIn(
            "Current weather: Overcast",
            rsp["agent_context"]["categories"]["weather"]["facts"],
        )
        self.assertEqual(
            rsp["agent_context"]["categories"]["weather"]["metrics"]["next_transition_to"],
            "Light Rain",
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_weather_drying_window_from_forecast(self):
        snapshot = _snapshot()
        snapshot["weather-forecast-samples"] = [
            _weather_sample(0, "Heavy Rain", rain=80, track_temp=24, air_temp=20),
            _weather_sample(15, "Overcast", rain=25, track_temp=27, air_temp=21),
        ]
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="weather")

        self.assertEqual(rsp["advice"][0]["id"], "weather-drying-window")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("Drying trend", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["agent_context"]["categories"]["weather"]["status"], "active_call")
        _assert_no_raw_ms(self, rsp["advice"])

    def test_weather_track_temperature_shift(self):
        snapshot = _snapshot()
        snapshot["weather-forecast-samples"] = [
            _weather_sample(0, "Clear", rain=4, track_temp=42, air_temp=28),
            _weather_sample(15, "Clear", rain=5, track_temp=36, air_temp=25),
        ]
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="weather")

        self.assertEqual(rsp["advice"][0]["id"], "weather-track-temp-shift")
        self.assertEqual(rsp["advice"][0]["priority"], "info")
        self.assertIn("Warm the tyres", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["track_temperature_delta_c"], -6.0)
        self.assertIn(
            "Track temperature trend: down 6C by +15 min",
            rsp["agent_context"]["categories"]["weather"]["facts"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_pace_compares_last_lap_to_car_ahead(self):
        snapshot = _snapshot()
        snapshot["table-entries"][0]["lap-info"]["last-lap"]["lap-time-ms"] = 91200
        snapshot["table-entries"][1]["lap-info"]["last-lap"]["lap-time-ms"] = 90500
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="pace")

        self.assertEqual(rsp["advice"][0]["id"], "pace-catching-ahead")
        self.assertIn("faster", rsp["advice"][0]["message"])
        self.assertEqual(rsp["nearby"]["car_ahead"]["last_lap"], "01:31.200")
        _assert_no_raw_ms(self, rsp["advice"])

    def test_pace_calls_attack_when_car_ahead_is_in_drs_and_slower(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["delta-info"]["delta-to-car-in-front"] = 850
        snapshot["table-entries"][0]["lap-info"]["last-lap"]["lap-time-ms"] = 91200
        snapshot["table-entries"][1]["lap-info"]["last-lap"]["lap-time-ms"] = 90400
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="pace")

        self.assertEqual(rsp["advice"][0]["id"], "pace-battle-attack-drs")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("Attack window", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["battle_target"], "ahead")
        self.assertEqual(rsp["advice"][0]["metrics"]["gap_ahead_ms"], 850)
        self.assertIn("pace-battle-attack-drs", rsp["agent_context"]["categories"]["pace"]["advice_ids"])
        _assert_no_raw_ms(self, rsp["advice"])

    def test_pace_calls_defence_when_car_behind_is_in_drs_and_faster(self):
        snapshot = _snapshot()
        snapshot["table-entries"][0]["lap-info"]["last-lap"]["lap-time-ms"] = 90450
        snapshot["table-entries"][1]["lap-info"]["last-lap"]["lap-time-ms"] = 90400
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 750
        snapshot["table-entries"][2]["lap-info"]["last-lap"]["lap-time-ms"] = 89700
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="pace")

        self.assertEqual(rsp["advice"][0]["id"], "pace-battle-defend-drs")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("Defend", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["battle_target"], "behind")
        self.assertEqual(rsp["advice"][0]["metrics"]["gap_behind_ms"], 750)
        self.assertEqual(rsp["advice"][0]["metrics"]["last_lap_delta_to_behind_ms"], 700)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_pace_reports_worst_sector_loss_against_best_lap(self):
        snapshot = _snapshot()
        snapshot["table-entries"][0]["lap-info"]["last-lap"]["lap-time-ms"] = 92000
        snapshot["table-entries"][1]["lap-info"]["last-lap"]["lap-time-ms"] = 92000
        snapshot["table-entries"][2]["lap-info"]["last-lap"]["lap-time-ms"] = 92000
        player_laps = snapshot["table-entries"][1]["lap-info"]
        player_laps["last-lap"]["s1-time-ms"] = 28800
        player_laps["last-lap"]["s2-time-ms"] = 30900
        player_laps["last-lap"]["s3-time-ms"] = 31700

        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="pace")

        self.assertEqual(rsp["advice"][0]["id"], "pace-sector-loss-sector_3")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("Sector 3", rsp["advice"][0]["message"])
        self.assertIn("braking", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["sector"], "sector_3")
        self.assertEqual(rsp["agent_context"]["categories"]["pace"]["metrics"]["worst_sector"], "sector_3")
        _assert_no_raw_ms(self, rsp["advice"])

    def test_tyre_wear_rate_warns_before_wear_threshold(self):
        snapshot = _snapshot()
        rates = snapshot["table-entries"][1]["tyre-info"]["wear-prediction"]["rate"]
        rates["front-left"] = 1.9
        rates["front-right"] = 2.0
        rates["rear-left"] = 2.1
        rates["rear-right"] = 3.7
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="tyres")

        self.assertEqual(rsp["advice"][0]["id"], "tyres-wear-rate-rear-right")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("wearing", rsp["advice"][0]["message"])
        self.assertIn("Smooth traction", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["fastest_wear_rate_tyre"], "rear-right")
        self.assertIn(
            "tyres-wear-rate-rear-right",
            rsp["agent_context"]["categories"]["tyres"]["advice_ids"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_tyre_stint_forecast_warns_before_wear_limit(self):
        snapshot = _snapshot()
        tyre = snapshot["table-entries"][1]["tyre-info"]
        tyre["current-wear"]["average"] = 51.0
        tyre["current-wear"]["rear-right-wear"] = 58.0
        for tyre_name in tyre["wear-prediction"]["rate"]:
            tyre["wear-prediction"]["rate"][tyre_name] = 2.5
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="tyres")

        self.assertEqual(rsp["advice"][0]["id"], "tyres-stint-window-rear-right")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("Start planning", rsp["advice"][0]["message"])
        self.assertAlmostEqual(rsp["advice"][0]["metrics"]["projected_laps_to_threshold"], 4.8)
        self.assertIn(
            "Projected stint limit: Rear Right to 70% in 4.8 laps",
            rsp["agent_context"]["categories"]["tyres"]["facts"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_tyre_focus_reports_fastest_live_compound(self):
        snapshot = _snapshot()
        snapshot["table-entries"][0]["tyre-info"]["visual-tyre-compound"] = "Soft"
        snapshot["table-entries"][0]["lap-info"]["last-lap"]["lap-time-ms"] = 90000
        snapshot["table-entries"][1]["tyre-info"]["visual-tyre-compound"] = "Medium"
        snapshot["table-entries"][1]["lap-info"]["last-lap"]["lap-time-ms"] = 90400
        snapshot["table-entries"][2]["tyre-info"]["visual-tyre-compound"] = "Hard"
        snapshot["table-entries"][2]["lap-info"]["last-lap"]["lap-time-ms"] = 91000
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="tyres")

        self.assertEqual(rsp["advice"][0]["id"], "tyres-fastest-compound-soft")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("Soft is the quickest", rsp["advice"][0]["message"])
        self.assertEqual(rsp["advice"][0]["metrics"]["fastest_live_compound"], "Soft")
        self.assertEqual(rsp["advice"][0]["metrics"]["gap_to_next_compound_ms"], 400.0)
        self.assertIn(
            "Fastest live compound: Soft via Driver Ahead at 01:30.000",
            rsp["agent_context"]["categories"]["tyres"]["facts"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_safety_car_box_near_pit_window(self):
        snapshot = _snapshot()
        snapshot["safety-car-status"] = "Safety Car"
        snapshot["current-lap"] = 12
        snapshot["player-pit-window"] = 13
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 41.0
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"][0]["id"], "strategy-safety-car-box")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("Safety Car", rsp["advice"][0]["message"])
        self.assertIn("Safety car window", rsp["advice"][0]["voice_callout"])
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_pit_window_reports_traffic_risk(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        snapshot["pit-time-loss"] = 23.0
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 55.0
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 8000
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"][0]["id"], "strategy-pit-traffic-risk")
        self.assertIn("traffic risk", rsp["advice"][0]["voice_callout"].lower())
        self.assertEqual(rsp["advice"][0]["metrics"]["pit_loss_ms"], 23000.0)
        self.assertTrue(rsp["advice"][0]["metrics"]["traffic_risk"])
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_pit_window_reports_clear_air(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        snapshot["pit-time-loss"] = 23.0
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 55.0
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 31000
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"][0]["id"], "strategy-pit-clear-air")
        self.assertIn("clear", rsp["advice"][0]["voice_callout"].lower())
        self.assertFalse(rsp["advice"][0]["metrics"]["traffic_risk"])
        self.assertEqual(rsp["advice"][0]["metrics"]["gap_behind_ms"], 31000)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_pit_window_recommends_available_tyre_set(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["total-laps"] = 27
        snapshot["player-pit-window"] = 13
        snapshot["pit-time-loss"] = 23.0
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 55.0
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 31000
        snapshot["player-tyre-sets"] = _player_tyre_sets()
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-pit-clear-air")
        self.assertIn("Tyre call: Medium", rsp["advice"][0]["message"])
        self.assertIn("Target Medium", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["recommended_next_compound"], "Medium")
        self.assertEqual(rsp["advice"][0]["metrics"]["recommended_next_tyre_source"], "tyre_sets")
        self.assertIn(
            "Recommended next tyre: Medium",
            " ".join(rsp["agent_context"]["categories"]["strategy"]["facts"]),
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_plans_stop_when_tyre_limit_reaches_pit_window(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 10
        snapshot["total-laps"] = 27
        snapshot["player-pit-window"] = 13
        player_tyre = snapshot["table-entries"][1]["tyre-info"]
        player_tyre["current-wear"]["average"] = 53.0
        player_tyre["current-wear"]["rear-right-wear"] = 58.0
        for tyre_name in player_tyre["wear-prediction"]["rate"]:
            player_tyre["wear-prediction"]["rate"][tyre_name] = 4.0
        snapshot["player-tyre-sets"] = _player_tyre_sets()
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-tyre-stint-70-rear-right")
        self.assertIn("Prepare the stop", rsp["advice"][0]["message"])
        self.assertIn("Tyre call: Medium", rsp["advice"][0]["message"])
        self.assertEqual(rsp["advice"][0]["metrics"]["recommended_next_compound"], "Medium")
        self.assertAlmostEqual(rsp["advice"][0]["metrics"]["projected_laps_to_threshold"], 3.0)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_holds_dry_stop_when_rain_is_close(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        snapshot["pit-time-loss"] = 23.0
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 52.0
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 31000
        snapshot["weather-forecast-samples"] = [
            _weather_sample(0, "Overcast", rain=20, track_temp=36, air_temp=25),
            _weather_sample(10, "Light Rain", rain=65, track_temp=32, air_temp=22),
        ]
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"][0]["id"], "strategy-hold-for-rain")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("rain is close", rsp["advice"][0]["voice_callout"].lower())
        self.assertEqual(rsp["advice"][0]["metrics"]["weather_transition_to"], "Light Rain")
        self.assertEqual(rsp["advice"][0]["metrics"]["rain_probability_pct"], 65.0)
        self.assertIn(
            "Weather transition for strategy: Overcast to Light Rain in 10 min",
            rsp["agent_context"]["categories"]["strategy"]["facts"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_holds_dry_stop_when_rain_risk_is_high(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 50.0
        snapshot["weather-forecast-samples"] = [
            _weather_sample(0, "Overcast", rain=25, track_temp=35, air_temp=24),
            _weather_sample(8, "Overcast", rain=75, track_temp=34, air_temp=23),
        ]
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-hold-for-rain-risk")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("Keep this dry stint flexible", rsp["advice"][0]["message"])
        self.assertEqual(rsp["advice"][0]["metrics"]["rain_risk_pct"], 75.0)
        self.assertIn(
            "Rain risk for strategy: 75% at +8 min",
            rsp["agent_context"]["categories"]["strategy"]["facts"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_delays_wet_stop_when_track_is_drying(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        snapshot["table-entries"][1]["tyre-info"]["visual-tyre-compound"] = "Intermediate"
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 48.0
        snapshot["weather-forecast-samples"] = [
            _weather_sample(0, "Light Rain", rain=70, track_temp=24, air_temp=20),
            _weather_sample(15, "Overcast", rain=30, track_temp=27, air_temp=21),
        ]
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-drying-crossover")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("Drying window", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["compound"], "Intermediate")
        self.assertEqual(rsp["advice"][0]["metrics"]["weather_transition_to"], "Overcast")
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_does_not_hold_for_rain_when_tyre_wear_is_critical(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        snapshot["pit-time-loss"] = 23.0
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 72.0
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 31000
        snapshot["weather-forecast-samples"] = [
            _weather_sample(0, "Overcast", rain=20, track_temp=36, air_temp=25),
            _weather_sample(10, "Light Rain", rain=65, track_temp=32, air_temp=22),
        ]
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-pit-clear-air")
        self.assertNotEqual(rsp["advice"][0]["id"], "strategy-hold-for-rain")
        self.assertEqual(rsp["advice"][0]["metrics"]["average_tyre_wear_pct"], 72.0)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_covers_undercut_threat_from_car_behind(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        player_tyre = snapshot["table-entries"][1]["tyre-info"]
        player_tyre["current-wear"]["average"] = 56.0
        player_tyre["tyre-age"] = 14
        behind = snapshot["table-entries"][2]
        behind["delta-info"]["delta-to-car-in-front"] = 2600
        behind["lap-info"]["last-lap"]["lap-time-ms"] = 89700
        behind["tyre-info"]["current-wear"]["average"] = 46.0
        behind["tyre-info"]["tyre-age"] = 10
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-cover-undercut")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("Undercut pressure", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["gap_behind_ms"], 2600)
        self.assertEqual(rsp["advice"][0]["metrics"]["behind_lap_delta_ms"], 700)
        self.assertEqual(rsp["advice"][0]["metrics"]["tyre_age_delta_laps"], 4)
        self.assertIn(
            "Car behind stint: Driver Behind, Medium, age 10 laps, wear 46.0%, stops 0",
            rsp["agent_context"]["categories"]["strategy"]["facts"],
        )
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_reports_undercut_threat_after_rival_has_stopped(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        player_tyre = snapshot["table-entries"][1]["tyre-info"]
        player_tyre["current-wear"]["average"] = 50.0
        player_tyre["tyre-age"] = 13
        behind = snapshot["table-entries"][2]
        behind["delta-info"]["delta-to-car-in-front"] = 6500
        behind["lap-info"]["last-lap"]["lap-time-ms"] = 89750
        behind["tyre-info"]["current-wear"]["average"] = 16.0
        behind["tyre-info"]["tyre-age"] = 2
        behind["tyre-info"]["num-pitstops"] = 1
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-undercut-threat")
        self.assertEqual(rsp["advice"][0]["priority"], "warning")
        self.assertIn("Undercut threat", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["opponent_pit_stops"], 1)
        self.assertEqual(rsp["advice"][0]["metrics"]["tyre_wear_delta_pct"], 34.0)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_strategy_spots_undercut_opportunity_on_car_ahead(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["player-pit-window"] = 13
        snapshot["table-entries"][1]["delta-info"]["delta-to-car-in-front"] = 2400
        player_tyre = snapshot["table-entries"][1]["tyre-info"]
        player_tyre["current-wear"]["average"] = 48.0
        player_tyre["tyre-age"] = 10
        ahead = snapshot["table-entries"][0]
        ahead["lap-info"]["last-lap"]["lap-time-ms"] = 91200
        ahead["tyre-info"]["current-wear"]["average"] = 60.0
        ahead["tyre-info"]["tyre-age"] = 15
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="strategy")

        self.assertEqual(rsp["advice"][0]["id"], "strategy-undercut-opportunity")
        self.assertEqual(rsp["advice"][0]["priority"], "advisory")
        self.assertIn("Undercut opportunity", rsp["advice"][0]["voice_callout"])
        self.assertEqual(rsp["advice"][0]["metrics"]["gap_ahead_ms"], 2400)
        self.assertEqual(rsp["advice"][0]["metrics"]["player_lap_delta_to_ahead_ms"], 800)
        self.assertEqual(rsp["advice"][0]["metrics"]["tyre_age_advantage_laps"], 5)
        _assert_no_raw_ms(self, rsp["advice"])

    def test_agent_context_prioritises_active_advisor_roles(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["rear-right-wear"] = 74.0
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="all")

        context = rsp["agent_context"]
        self.assertEqual(context["focus"], "all")
        self.assertEqual(context["agent_order"][0], "fuel")
        self.assertIn("fuel", context["active_categories"])
        self.assertIn("tyres", context["active_categories"])
        self.assertEqual(context["categories"]["fuel"]["status"], "active_call")
        self.assertEqual(context["categories"]["fuel"]["highest_priority"], "critical")
        self.assertIn("fuel-critical-deficit", context["categories"]["fuel"]["advice_ids"])
        self.assertIn("Fuel surplus: -0.65 laps", context["categories"]["fuel"]["facts"])
        self.assertEqual(context["categories"]["tyres"]["metrics"]["worst_tyre"], "rear-right")
        self.assertEqual(context["categories"]["pace"]["role"], "Pace Engineer")
        self.assertTrue(context["review"]["required"])

    def test_agent_context_only_marks_visible_advice_active(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["rear-right-wear"] = 74.0
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="all", max_items=1)

        self.assertEqual([item["id"] for item in rsp["advice"]], ["fuel-critical-deficit"])
        context = rsp["agent_context"]
        self.assertEqual(context["active_categories"], ["fuel"])
        self.assertEqual(context["categories"]["fuel"]["status"], "active_call")
        self.assertEqual(context["categories"]["tyres"]["status"], "monitoring")
        self.assertEqual(context["categories"]["tyres"]["advice_ids"], [])
        self.assertIn("Worst tyre: Rear Right at 74.0%", context["categories"]["tyres"]["facts"])

    def test_agent_context_respects_focused_category(self):
        snapshot = _snapshot()
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="tyres")

        context = rsp["agent_context"]
        self.assertEqual(context["focus"], "tyres")
        self.assertEqual(context["agent_order"], ["tyres"])
        self.assertEqual(list(context["categories"].keys()), ["tyres"])
        self.assertEqual(context["categories"]["tyres"]["status"], "monitoring")
        self.assertIn("Compound: Medium", context["categories"]["tyres"]["facts"])

    def test_agent_context_reports_trace_only_driving_workspace(self):
        state.set_state_data("race-engineer-driving-advice-update", {
            "source": "race-engineer-trace-update",
            "session-uid": "trace-only-session",
            "advice": [_driving_coach_advice()],
            "reference-lap-count": 1,
            "last-completed-lap": 4,
        })

        rsp = get_race_engineer_brief(self.logger, focus="driving_coach")

        context = rsp["agent_context"]
        self.assertEqual(context["agent_order"], ["driving_coach"])
        self.assertEqual(context["categories"]["driving_coach"]["status"], "active_call")
        self.assertIn(
            "driving-coach-test",
            context["categories"]["driving_coach"]["advice_ids"],
        )
        self.assertIn("Clean reference laps: 1", context["categories"]["driving_coach"]["facts"])

    def test_invalid_tool_inputs_are_normalised(self):
        snapshot = _snapshot()
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus=[], max_items="2")

        self.assertTrue(rsp["ok"])
        self.assertLessEqual(len(rsp["advice"]), 2)
        self.assertIn("review", rsp["agent_prompt_specs"])

    def test_brief_applies_agent_prompt_overrides_to_specs_and_context(self):
        snapshot = _snapshot()

        rsp = build_race_engineer_brief(
            snapshot,
            {"available": True, "connected": True, "ok": False},
            focus="fuel",
            agent_prompt_overrides={
                "fuel": {
                    "role": "Fuel Coach",
                    "system_prompt": "Turn fuel evidence into crisp lift-and-coast instructions.",
                }
            },
        )

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["agent_prompt_specs"]["fuel"]["role"], "Fuel Coach")
        self.assertEqual(
            rsp["agent_context"]["categories"]["fuel"]["role"],
            "Fuel Coach",
        )
        self.assertIn("Fuel Coach", rsp["agent_prompts"]["fuel"])

    def test_malformed_table_entries_return_error_instead_of_crashing(self):
        state.set_state_data("race-table-update", {"table-entries": "bad"})

        rsp = get_race_engineer_brief(self.logger)

        self.assertFalse(rsp["ok"])
        direct_rsp = build_race_engineer_brief(
            {"table-entries": "bad"},
            {"available": True, "connected": True, "ok": False},
        )
        self.assertFalse(direct_rsp["ok"])
        self.assertIn("No race table entries", direct_rsp["error"])

    def test_malformed_race_table_state_returns_error_instead_of_crashing(self):
        state.set_state_data("race-table-update", "bad")

        rsp = get_race_engineer_brief(self.logger)

        self.assertFalse(rsp["ok"])
        self.assertFalse(rsp["available"])
        self.assertEqual(rsp["status"], "error")
        self.assertEqual(rsp["error"], "Telemetry update is not an object.")

    def test_malformed_nested_driver_data_does_not_crash(self):
        snapshot = _snapshot()
        snapshot["table-entries"] = ["bad-row", None, snapshot["table-entries"][1]]
        snapshot["table-entries"][2]["tyre-info"] = None
        snapshot["table-entries"][2]["driver-info"]["is-player"] = True
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="tyres")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"], [])

    def test_fuel_zero_live_surplus_does_not_fall_back_to_game_deficit(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = 0.0
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-game"] = -0.65
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="fuel")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"], [])

    def test_nearby_context_uses_sorted_adjacency_when_positions_have_gaps(self):
        snapshot = _snapshot()
        snapshot["table-entries"][0]["driver-info"]["position"] = 1
        snapshot["table-entries"][1]["driver-info"]["position"] = 3
        snapshot["table-entries"][2]["driver-info"]["position"] = 4
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger, focus="pace")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["nearby"]["car_ahead"]["name"], "Driver Ahead")
        self.assertEqual(rsp["nearby"]["car_behind"]["name"], "Driver Behind")

    def test_boolean_ref_row_index_is_ignored(self):
        snapshot = _snapshot()
        snapshot["ref-row-index"] = True
        snapshot["table-entries"][0]["driver-info"]["is-player"] = True
        snapshot["table-entries"][1]["driver-info"]["is-player"] = False
        state.set_state_data("race-table-update", snapshot)

        rsp = get_race_engineer_brief(self.logger)

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["reference_driver"]["name"], "Driver Ahead")

    def test_driving_coach_focus_includes_latest_trace_advice(self):
        state.set_state_data("race-table-update", _snapshot())
        state.set_state_data("race-engineer-driving-advice-update", {
            "source": "race-engineer-trace-update",
            "session-uid": 12345,
            "advice": [_driving_coach_advice()],
            "reference-lap-count": 2,
            "last-completed-lap": 8,
        })

        rsp = get_race_engineer_brief(self.logger, focus="driving_coach")

        self.assertTrue(rsp["ok"])
        self.assertEqual(len(rsp["advice"]), 1)
        self.assertEqual(rsp["advice"][0]["id"], "driving-coach-test")
        self.assertEqual(rsp["advice"][0]["category"], "driving_coach")
        self.assertTrue(rsp["driving_trace"]["available"])
        self.assertFalse(rsp["driving_trace"]["session_mismatch"])
        self.assertEqual(rsp["driving_trace"]["session_uid"], 12345)
        self.assertEqual(rsp["driving_trace"]["reference_lap_count"], 2)
        self.assertEqual(rsp["driving_trace"]["last_completed_lap"], 8)

    def test_trace_advice_from_other_session_is_not_returned(self):
        state.set_state_data("race-table-update", _snapshot())
        state.set_state_data("race-engineer-driving-advice-update", {
            "source": "race-engineer-trace-update",
            "session-uid": "previous-session",
            "advice": [_driving_coach_advice()],
            "reference-lap-count": 2,
            "last-completed-lap": 8,
        })

        rsp = get_race_engineer_brief(self.logger, focus="driving_coach")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"], [])
        self.assertFalse(rsp["driving_trace"]["available"])
        self.assertTrue(rsp["driving_trace"]["session_mismatch"])
        self.assertEqual(rsp["driving_trace"]["session_uid"], "previous-session")
        context = rsp["agent_context"]["categories"]["driving_coach"]
        self.assertEqual(context["status"], "monitoring")
        self.assertEqual(context["advice_ids"], [])
        self.assertIn("Trace session does not match current race table.", context["facts"])
        self.assertTrue(context["metrics"]["session_mismatch"])

    def test_trace_advice_is_available_before_race_table_snapshot(self):
        state.set_state_data("race-engineer-driving-advice-update", {
            "source": "race-engineer-trace-update",
            "session-uid": "trace-only-session",
            "advice": [_driving_coach_advice()],
            "reference-lap-count": 1,
            "last-completed-lap": 4,
        })

        rsp = get_race_engineer_brief(self.logger, focus="driving_coach")

        self.assertTrue(rsp["available"])
        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"][0]["id"], "driving-coach-test")
        self.assertIsNone(rsp["reference_driver"]["name"])

    def test_malformed_trace_advice_is_ignored(self):
        state.set_state_data("race-table-update", _snapshot())
        state.set_state_data("race-engineer-driving-advice-update", {
            "source": "race-engineer-trace-update",
            "advice": "bad",
        })

        rsp = get_race_engineer_brief(self.logger, focus="driving_coach")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"], [])
        self.assertFalse(rsp["driving_trace"]["available"])
        self.assertTrue(rsp["driving_trace"]["invalid_payload"])
        context = rsp["agent_context"]["categories"]["driving_coach"]
        self.assertEqual(context["status"], "insufficient_data")
        self.assertIn("Trace payload is invalid.", context["facts"])

    def test_rejected_trace_advice_is_reported_in_agent_review(self):
        invalid_advice = _driving_coach_advice()
        invalid_advice["evidence"] = []
        state.set_state_data("race-table-update", _snapshot())
        state.set_state_data("race-engineer-driving-advice-update", {
            "source": "race-engineer-trace-update",
            "session-uid": 12345,
            "advice": [invalid_advice],
            "reference-lap-count": 2,
            "last-completed-lap": 8,
        })

        rsp = get_race_engineer_brief(self.logger, focus="driving_coach")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"], [])
        self.assertEqual(rsp["advice_review"]["rejected_advice_ids"], ["driving-coach-test"])
        self.assertEqual(rsp["agent_context"]["review"]["rejected_count"], 1)
        self.assertEqual(
            rsp["agent_context"]["review"]["rejected_advice_ids"],
            ["driving-coach-test"],
        )
        self.assertEqual(
            rsp["agent_context"]["categories"]["driving_coach"]["advice_ids"],
            [],
        )

    def test_stale_trace_advice_is_not_returned(self):
        state.set_state_data("race-table-update", _snapshot())
        state.set_state_data("race-engineer-driving-advice-update", {
            "source": "race-engineer-trace-update",
            "advice": [_driving_coach_advice()],
            "reference-lap-count": 2,
            "last-completed-lap": 8,
        })
        state.state_data["race-engineer-driving-advice-update"].ts = time.time() - 121.0

        rsp = get_race_engineer_brief(self.logger, focus="driving_coach")

        self.assertTrue(rsp["ok"])
        self.assertEqual(rsp["advice"], [])
        self.assertFalse(rsp["driving_trace"]["available"])
        self.assertTrue(rsp["driving_trace"]["stale"])
        self.assertGreaterEqual(rsp["driving_trace"]["age_seconds"], 120.0)
        context = rsp["agent_context"]["categories"]["driving_coach"]
        self.assertEqual(context["status"], "stale")
        self.assertEqual(context["advice_ids"], [])
        self.assertIn("Trace advice is stale.", context["facts"])
        self.assertTrue(context["metrics"]["stale"])


def _assert_no_raw_ms(test_case, advice):
    for item in advice:
        test_case.assertNotIn("ms", item["message"].lower())
        test_case.assertNotIn("ms", item["voice_callout"].lower())


def _snapshot():
    return {
        "session-uid": 12345,
        "event-type": "Race",
        "formula": "F1 Modern",
        "circuit": "Monza",
        "race-ended": False,
        "current-lap": 12,
        "total-laps": 27,
        "session-time-left": 1800,
        "safety-car-status": "None",
        "player-pit-window": 13,
        "is-spectating": False,
        "table-entries": [
            _row(
                name="Driver Ahead",
                index=3,
                position=4,
                is_player=False,
                delta_to_front=4200,
                last_lap_ms=90750,
            ),
            _row(
                name="Player",
                index=7,
                position=5,
                is_player=True,
                delta_to_front=1250,
                last_lap_ms=90400,
            ),
            _row(
                name="Driver Behind",
                index=11,
                position=6,
                is_player=False,
                delta_to_front=1800,
                last_lap_ms=90300,
            ),
        ],
    }


def _row(name, index, position, is_player, delta_to_front, last_lap_ms):
    return {
        "driver-info": {
            "position": position,
            "name": name,
            "team": "Test Team",
            "is-player": is_player,
            "index": index,
            "dnf-status": None,
            "drs": False,
            "drs-activated": False,
            "drs-allowed": False,
            "drs-distance": 0,
        },
        "delta-info": {
            "delta-to-car-in-front": delta_to_front,
            "delta-to-leader": 10000 + delta_to_front,
        },
        "lap-info": {
            "current-lap": 12,
            "last-lap": {
                "lap-time-ms": last_lap_ms,
                "s1-time-ms": 29000,
                "s2-time-ms": 31000,
                "s3-time-ms": 30400,
                "is-valid": True,
            },
            "best-lap": {
                "lap-time-ms": 89800,
                "s1-time-ms": 28800,
                "s2-time-ms": 30900,
                "s3-time-ms": 30100,
                "is-valid": True,
            },
            "curr-lap": {
                "lap-time-ms": 35000,
                "delta-ms": 120,
                "is-valid": True,
            },
        },
        "warns-pens-info": {
            "corner-cutting-warnings": 0,
            "time-penalties": 0,
        },
        "tyre-info": {
            "visual-tyre-compound": "Medium",
            "tyre-age": 9,
            "num-pitstops": 0,
            "current-wear": {
                "average": 42.0,
                "front-left-wear": 40.0,
                "front-right-wear": 41.0,
                "rear-left-wear": 43.0,
                "rear-right-wear": 44.0,
            },
            "wear-prediction": {
                "status": True,
                "rate": {
                    "front-left": 2.1,
                    "front-right": 2.0,
                    "rear-left": 2.4,
                    "rear-right": 2.5,
                },
            },
        },
        "fuel-info": {
            "surplus-laps-png": 0.25,
            "surplus-laps-game": 0.2,
            "target-fuel-rate-next-lap": 2.05,
            "last-lap-fuel-used": 2.1,
        },
        "ers-info": {
            "ers-percent-float": 32.5,
            "ers-mode": "Medium",
        },
        "damage-info": {
            "fl-wing-damage": 0,
            "fr-wing-damage": 0,
            "rear-wing-damage": 0,
            "floor-damage": 0,
            "diffuser-damage": 0,
            "sidepod-damage": 0,
            "drs-fault": False,
            "ers-fault": False,
            "gear-box-damage": 0,
            "engine-damage": 0,
            "engine-mguh-wear": 0,
            "engine-es-wear": 0,
            "engine-ce-wear": 0,
            "engine-ice-wear": 0,
            "engine-mguk-wear": 0,
            "engine-tc-wear": 0,
            "engine-blown": False,
            "engine-seized": False,
        },
        "2026-regs-info": {
            "2026-regs-enabled": False,
            "overtake-avlb": False,
            "overtake-active": False,
            "overtake-dist": 0,
        },
    }


def _player_tyre_sets():
    return {
        "car-index": 7,
        "fitted-index": 3,
        "tyre-set-data": [
            {
                "actual-tyre-compound": "C5",
                "visual-tyre-compound": "Soft",
                "wear": 0,
                "available": True,
                "recommended-session": "Race",
                "life-span": 8,
                "usable-life": 8,
                "lap-delta-time": -700,
                "fitted": False,
            },
            {
                "actual-tyre-compound": "C4",
                "visual-tyre-compound": "Medium",
                "wear": 0,
                "available": True,
                "recommended-session": "Race",
                "life-span": 17,
                "usable-life": 17,
                "lap-delta-time": -250,
                "fitted": False,
            },
            {
                "actual-tyre-compound": "C3",
                "visual-tyre-compound": "Hard",
                "wear": 0,
                "available": True,
                "recommended-session": "Race",
                "life-span": 25,
                "usable-life": 25,
                "lap-delta-time": 200,
                "fitted": False,
            },
            {
                "actual-tyre-compound": "C4",
                "visual-tyre-compound": "Medium",
                "wear": 44,
                "available": True,
                "recommended-session": "Race",
                "life-span": 17,
                "usable-life": 9,
                "lap-delta-time": 0,
                "fitted": True,
            },
        ],
    }


def _driving_coach_advice():
    return {
        "id": "driving-coach-test",
        "category": "driving_coach",
        "priority": "advisory",
        "title": "Brake and throttle overlap",
        "message": "Lap 8: brake and throttle overlap around sector 2, 300-320m.",
        "voice_callout": "Sector 2: separate brake and throttle.",
        "cooldown_key": "driving-coach:overlap:sector-2",
        "evidence": ["lap=8", "avg-overlap-pct=55.0"],
        "metrics": {"lap": 8, "avg_overlap_pct": 55.0},
    }


def _weather_sample(offset, weather, rain, track_temp, air_temp):
    return {
        "session-type": "Race",
        "time-offset": offset,
        "weather": weather,
        "track-temperature": track_temp,
        "track-temperature-change": "No Temperature Change",
        "air-temperature": air_temp,
        "air-temperature-change": "No Temperature Change",
        "rain-percentage": rain,
    }
