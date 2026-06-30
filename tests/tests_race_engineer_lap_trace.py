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
    DrivingTraceRecorder,
    RaceEngineerAnnouncer,
    sample_from_stream_overlay,
    sample_from_trace_update,
)


class TestRaceEngineerLapTrace(unittest.TestCase):
    def test_sample_from_stream_overlay_extracts_hud_and_steering(self):
        sample = sample_from_stream_overlay(_stream_sample(lap=3, distance=100, timestamp=1.0))

        self.assertEqual(sample.session_uid, "abc")
        self.assertEqual(sample.current_lap, 3)
        self.assertEqual(sample.lap_distance_m, 100)
        self.assertEqual(sample.throttle_pct, 80)
        self.assertEqual(sample.brake_pct, 0)
        self.assertEqual(sample.steering_pct, -12)

    def test_sample_from_trace_update_extracts_backend_payload(self):
        sample = sample_from_trace_update(_trace_sample(lap=3, distance=100, timestamp=1.0))

        self.assertEqual(sample.session_uid, "abc")
        self.assertEqual(sample.current_lap, 3)
        self.assertEqual(sample.lap_distance_m, 100)
        self.assertEqual(sample.throttle_pct, 80)
        self.assertEqual(sample.brake_pct, 0)
        self.assertEqual(sample.steering_pct, -12)
        self.assertEqual(sample.location_label, "La Source")
        self.assertEqual(sample.location_voice_label, "La Source")

    def test_invalid_trace_sample_is_ignored(self):
        self.assertIsNone(sample_from_trace_update({"ok": False, "reason": "missing telemetry"}))
        invalid = _trace_sample(lap=3, distance=100, timestamp=1.0)
        invalid["current-lap-invalid"] = True
        self.assertIsNone(sample_from_trace_update(invalid))

    def test_pit_trace_sample_is_ignored(self):
        pitting = _trace_sample(lap=3, distance=100, timestamp=1.0)
        pitting["pit-status"] = "PitStatus.PITTING"
        self.assertIsNone(sample_from_trace_update(pitting))

        in_lane = _trace_sample(lap=3, distance=100, timestamp=1.0)
        in_lane["pit-lane-timer-active"] = True
        self.assertIsNone(sample_from_trace_update(in_lane))

    def test_first_completed_lap_becomes_reference_without_advice(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)

        for sample in _lap_samples(lap=1, speed=210, throttle=0.8, brake=0.0):
            self.assertEqual(recorder.update_from_stream_overlay(sample), [])
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        self.assertEqual(advice, [])
        self.assertEqual(recorder.reference_lap_count, 1)
        self.assertEqual(recorder.last_completed_lap.lap_number, 1)

    def test_low_coverage_completed_lap_is_not_used_as_reference(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)

        for sample in _lap_samples(lap=1, speed=210, throttle=0.8, brake=0.0, circuit_length=5800):
            self.assertEqual(recorder.update_from_stream_overlay(sample), [])
        advice = recorder.update_from_stream_overlay(
            _stream_sample(lap=2, distance=0, timestamp=20.0, circuit_length=5800),
        )

        self.assertEqual(advice, [])
        self.assertEqual(recorder.reference_lap_count, 0)
        self.assertEqual(recorder.last_completed_lap.lap_number, 1)
        self.assertLess(recorder.last_completed_lap.coverage_ratio(recorder.bin_size_m), 0.55)

    def test_completed_lap_reports_early_braking_against_reference(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=219, throttle=0.75, brake=0.0, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400, 500}:
                sample["hud"]["brake"] = 0.75
                sample["hud"]["throttle"] = 0.0
                sample["hud"]["speed-kmph"] = 190
                sample["car-telemetry"]["throttle"] = 0
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["category"], "driving_coach")
        self.assertEqual(advice[0]["id"], "driving-coach-early-brake")
        self.assertIn("braked earlier", advice[0]["message"])
        self.assertIn("around sector 3, 300-600m", advice[0]["message"])
        self.assertIn("Carry a little more speed", advice[0]["voice_callout"])
        self.assertIn("lap-coverage=0.86", advice[0]["evidence"])
        self.assertIn("reference-coverage=0.86", advice[0]["evidence"])
        self.assertGreater(advice[0]["metrics"]["lap_coverage_ratio"], 0.55)

    def test_completed_lap_reports_brake_throttle_overlap_against_reference(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=219, throttle=0.75, brake=0.0, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400}:
                sample["hud"]["throttle"] = 0.4
                sample["hud"]["brake"] = 0.4
                sample["hud"]["speed-kmph"] = 190
                sample["car-telemetry"]["throttle"] = 40
                sample["car-telemetry"]["brake"] = 40
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "driving-coach-brake-throttle-overlap")
        self.assertIn("brake and throttle together", advice[0]["message"])
        self.assertIn("Separate the inputs", advice[0]["voice_callout"])
        announcements = RaceEngineerAnnouncer(min_priority="advisory").process_advice_items(
            advice,
            focus="driving_coach",
            now=100.0,
        )
        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0].advice_id, "driving-coach-brake-throttle-overlap")

    def test_brake_throttle_overlap_wins_over_early_braking(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=219, throttle=0.75, brake=0.0, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400}:
                sample["hud"]["throttle"] = 0.5
                sample["hud"]["brake"] = 0.5
                sample["hud"]["speed-kmph"] = 190
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "driving-coach-brake-throttle-overlap")

    def test_single_brake_throttle_overlap_bin_is_ignored(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=220, throttle=0.8, brake=0.0, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] == 300:
                sample["hud"]["throttle"] = 0.65
                sample["hud"]["brake"] = 0.4
                sample["hud"]["speed-kmph"] = 216
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(advice, [])

    def test_brake_throttle_overlap_ignored_when_reference_also_overlaps(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.1):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=220, throttle=0.8, brake=0.1, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400}:
                sample["hud"]["throttle"] = 0.65
                sample["hud"]["brake"] = 0.4
                sample["hud"]["speed-kmph"] = 216
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(advice, [])

    def test_brake_throttle_overlap_ignored_at_low_speed(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=80, throttle=0.8, brake=0.1):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=80, throttle=0.8, brake=0.1, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400}:
                sample["hud"]["throttle"] = 0.65
                sample["hud"]["brake"] = 0.4
                sample["hud"]["speed-kmph"] = 70
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(advice, [])

    def test_completed_lap_reports_long_coasting_against_reference(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=219, throttle=0.75, brake=0.0, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400, 500}:
                sample["hud"]["throttle"] = 0.0
                sample["hud"]["brake"] = 0.0
                sample["hud"]["speed-kmph"] = 198
                sample["car-telemetry"]["throttle"] = 0
                sample["car-telemetry"]["brake"] = 0
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "driving-coach-long-coast")
        self.assertIn("coasted longer", advice[0]["message"])
        self.assertIn("Commit to brake or throttle", advice[0]["voice_callout"])

    def test_completed_lap_reports_weak_throttle_against_reference(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=219, throttle=0.75, brake=0.0, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400, 500}:
                sample["hud"]["throttle"] = 0.4
                sample["hud"]["speed-kmph"] = 214
                sample["car-telemetry"]["throttle"] = 40
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "driving-coach-weak-throttle")
        self.assertIn("throttle pickup", advice[0]["message"])
        self.assertIn("Open the car earlier", advice[0]["voice_callout"])

    def test_completed_lap_reports_pure_speed_loss_against_reference(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _lap_samples(lap=2, speed=219, throttle=0.8, brake=0.0, timestamp_offset=20.0):
            if sample["hud"]["circuit-position"] in {300, 400, 500}:
                sample["hud"]["speed-kmph"] = 200
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "driving-coach-speed-loss")
        self.assertIn("speed was about", advice[0]["message"])
        self.assertIn("losing speed", advice[0]["voice_callout"])

    def test_announcer_accepts_driving_coach_advice_items(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))
        advice = []
        for sample in _lap_samples(lap=2, speed=185, throttle=0.4, brake=0.0, timestamp_offset=20.0):
            advice = recorder.update_from_stream_overlay(sample)
        advice = recorder.update_from_stream_overlay(_stream_sample(lap=3, distance=0, timestamp=40.0))

        announcer = RaceEngineerAnnouncer(min_priority="advisory")
        announcements = announcer.process_advice_items(advice, focus="driving_coach", now=100.0)

        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0].category, "driving_coach")

    def test_backend_segment_label_is_used_in_driving_coach_callout(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _trace_lap_samples(lap=1, speed=220, throttle=80, brake=0,
                                         segment_label="La Source", segment_voice_label="La Source"):
            recorder.update_from_trace_update(sample)
        recorder.update_from_trace_update(_trace_sample(lap=2, distance=0, timestamp=20.0))

        advice = []
        for sample in _trace_lap_samples(lap=2, speed=219, throttle=75, brake=0, timestamp_offset=20.0,
                                         segment_label="La Source", segment_voice_label="La Source"):
            if sample["lap-distance-m"] in {300, 400}:
                sample["throttle-pct"] = 40
                sample["brake-pct"] = 40
                sample["speed-kmph"] = 190
            advice = recorder.update_from_trace_update(sample)
        advice = recorder.update_from_trace_update(_trace_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertIn("around La Source", advice[0]["message"])
        self.assertTrue(advice[0]["voice_callout"].startswith("La Source:"))
        self.assertIn("location=La Source", advice[0]["evidence"])

    def test_session_change_resets_trace_references(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _lap_samples(lap=1, speed=220, throttle=0.8, brake=0.0):
            recorder.update_from_stream_overlay(sample)
        recorder.update_from_stream_overlay(_stream_sample(lap=2, distance=0, timestamp=20.0))
        self.assertEqual(recorder.reference_lap_count, 1)

        recorder.update_from_stream_overlay(_stream_sample(lap=1, distance=0, timestamp=1.0, session_uid="new"))

        self.assertEqual(recorder.reference_lap_count, 0)

    def test_recorder_accepts_backend_trace_updates(self):
        recorder = DrivingTraceRecorder(bin_size_m=100, min_samples=4)
        for sample in _trace_lap_samples(lap=1, speed=220, throttle=80, brake=0):
            recorder.update_from_trace_update(sample)
        recorder.update_from_trace_update(_trace_sample(lap=2, distance=0, timestamp=20.0))

        advice = []
        for sample in _trace_lap_samples(lap=2, speed=190, throttle=80, brake=0, timestamp_offset=20.0):
            if sample["lap-distance-m"] in {300, 400, 500}:
                sample["brake-pct"] = 75
                sample["throttle-pct"] = 0
            advice = recorder.update_from_trace_update(sample)
        advice = recorder.update_from_trace_update(_trace_sample(lap=3, distance=0, timestamp=40.0))

        self.assertEqual(len(advice), 1)
        self.assertEqual(advice[0]["id"], "driving-coach-early-brake")


def _lap_samples(*, lap, speed, throttle, brake, timestamp_offset=0.0, circuit_length=600):
    return [
        _stream_sample(lap=lap, distance=distance, timestamp=timestamp_offset + index, speed=speed,
                       throttle=throttle, brake=brake, circuit_length=circuit_length)
        for index, distance in enumerate([0, 100, 200, 300, 400, 500])
    ]


def _trace_lap_samples(
    *,
    lap,
    speed,
    throttle,
    brake,
    timestamp_offset=0.0,
    segment_label=None,
    segment_voice_label=None,
    circuit_length=600,
):
    return [
        _trace_sample(lap=lap, distance=distance, timestamp=timestamp_offset + index, speed=speed,
                      throttle=throttle, brake=brake, segment_label=segment_label,
                      segment_voice_label=segment_voice_label, circuit_length=circuit_length)
        for index, distance in enumerate([0, 100, 200, 300, 400, 500])
    ]


def _stream_sample(
    *,
    lap,
    distance,
    timestamp,
    speed=210,
    throttle=0.8,
    brake=0.0,
    session_uid="abc",
    circuit_length=600,
):
    return {
        "session-uid": session_uid,
        "current-lap": lap,
        "timestamp": timestamp,
        "circuit-enum-name": "Monza",
        "hud": {
            "throttle": throttle,
            "brake": brake,
            "rpm": 11500,
            "gear": 6,
            "speed-kmph": speed,
            "circuit-position": distance,
            "circuit-length": circuit_length,
            "sector": "3" if distance >= 300 else "2",
        },
        "car-telemetry": {
            "steering": -12,
            "throttle": throttle * 100,
            "brake": brake * 100,
        },
    }


def _trace_sample(
    *,
    lap,
    distance,
    timestamp,
    speed=210,
    throttle=80,
    brake=0,
    session_uid="abc",
    segment_label="La Source",
    segment_voice_label="La Source",
    circuit_length=600,
):
    return {
        "ok": True,
        "source": "backend-session-state",
        "session-uid": session_uid,
        "current-lap": lap,
        "current-lap-time-ms": 12345,
        "current-lap-invalid": False,
        "timestamp": timestamp,
        "circuit-enum-name": "Monza",
        "lap-distance-m": distance,
        "circuit-length-m": circuit_length,
        "sector": "3" if distance >= 300 else "2",
        "segment-label": segment_label,
        "segment-voice-label": segment_voice_label,
        "speed-kmph": speed,
        "throttle-pct": throttle,
        "brake-pct": brake,
        "steering-pct": -12,
        "gear": 6,
        "drs-enabled": False,
    }


if __name__ == "__main__":
    unittest.main()
