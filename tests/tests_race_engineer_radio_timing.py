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
    RadioTimingConfig,
    RaceEngineerAnnouncement,
    decide_radio_timing,
    normalise_radio_timing_config,
    sample_from_trace_update,
)


class TestRaceEngineerRadioTiming(unittest.TestCase):
    def test_braking_sample_delays_noncritical_callout(self):
        sample = sample_from_trace_update(_trace_sample(brake=55, throttle=0, steering=4, timestamp=100.0))
        callout = _announcement(priority="warning")

        decision = decide_radio_timing(
            callout,
            sample=sample,
            now=100.4,
            queued_at=100.0,
            config=RadioTimingConfig(max_delay_seconds=8.0),
        )

        self.assertTrue(decision.should_delay)
        self.assertEqual(decision.reason, "braking")

    def test_safe_straight_speaks_now(self):
        sample = sample_from_trace_update(_trace_sample(brake=0, throttle=85, steering=3, timestamp=100.0))
        callout = _announcement(priority="advisory")

        decision = decide_radio_timing(
            callout,
            sample=sample,
            now=100.2,
            queued_at=100.0,
            config=RadioTimingConfig(),
        )

        self.assertFalse(decision.should_delay)
        self.assertEqual(decision.reason, "safe-window")

    def test_critical_and_system_callouts_bypass_timing(self):
        sample = sample_from_trace_update(_trace_sample(brake=70, throttle=0, steering=40, timestamp=100.0))

        critical = decide_radio_timing(
            _announcement(priority="critical"),
            sample=sample,
            now=100.1,
            queued_at=100.0,
            config=RadioTimingConfig(),
        )
        system = decide_radio_timing(
            _announcement(priority="info", category="system"),
            sample=sample,
            now=100.1,
            queued_at=100.0,
            config=RadioTimingConfig(),
        )

        self.assertFalse(critical.should_delay)
        self.assertEqual(critical.reason, "critical")
        self.assertFalse(system.should_delay)
        self.assertEqual(system.reason, "bypass-category")

    def test_max_delay_forces_speech(self):
        sample = sample_from_trace_update(_trace_sample(brake=55, throttle=0, steering=4, timestamp=107.9))

        decision = decide_radio_timing(
            _announcement(priority="warning"),
            sample=sample,
            now=108.0,
            queued_at=100.0,
            config=RadioTimingConfig(max_delay_seconds=8.0),
        )

        self.assertFalse(decision.should_delay)
        self.assertTrue(decision.forced)
        self.assertEqual(decision.reason, "max-delay")

    def test_stale_sample_fails_open(self):
        sample = sample_from_trace_update(_trace_sample(brake=55, throttle=0, steering=4, timestamp=90.0))

        decision = decide_radio_timing(
            _announcement(priority="warning"),
            sample=sample,
            now=100.0,
            queued_at=99.0,
            config=RadioTimingConfig(),
        )

        self.assertFalse(decision.should_delay)
        self.assertEqual(decision.reason, "stale-sample")

    def test_config_normalises_bounds(self):
        config = normalise_radio_timing_config(
            enabled="off",
            max_delay_seconds="99",
            check_interval_seconds="0",
        )

        self.assertFalse(config.enabled)
        self.assertEqual(config.max_delay_seconds, 30.0)
        self.assertEqual(config.check_interval_seconds, 0.05)


def _announcement(priority="warning", category="fuel"):
    return RaceEngineerAnnouncement(
        text="Callout",
        priority=priority,
        category=category,
        cooldown_key="test:callout",
        advice_id="test-callout",
        evidence=[],
        metrics={},
    )


def _trace_sample(*, brake, throttle, steering, timestamp):
    return {
        "ok": True,
        "session-uid": "abc",
        "current-lap": 3,
        "timestamp": timestamp,
        "circuit-enum-name": "Spa",
        "current-lap-invalid": False,
        "lap-distance-m": 1000,
        "circuit-length-m": 7000,
        "sector": "2",
        "speed-kmph": 220,
        "throttle-pct": throttle,
        "brake-pct": brake,
        "steering-pct": steering,
        "gear": 7,
        "pit-status": "None",
    }


if __name__ == "__main__":
    unittest.main()
