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

from lib.race_engineer import build_race_engineer_brief, review_race_engineer_advice
from tests.tests_mcp_race_engineer_brief import _snapshot


class TestRaceEngineerReview(unittest.TestCase):
    def test_valid_advice_is_accepted(self):
        result = review_race_engineer_advice([_advice()])

        self.assertTrue(result.ok)
        self.assertEqual(len(result.accepted_advice), 1)
        self.assertEqual(result.rejected_advice_ids, [])

    def test_missing_evidence_is_rejected(self):
        advice = _advice()
        advice["evidence"] = []

        result = review_race_engineer_advice([advice])

        self.assertFalse(result.ok)
        self.assertEqual(result.rejected_advice_ids, ["fuel-test"])
        self.assertEqual(result.issues[0].code, "missing-evidence")

    def test_raw_milliseconds_in_voice_are_rejected(self):
        advice = _advice()
        advice["voice_callout"] = "You are 500 ms faster."

        result = review_race_engineer_advice([advice])

        self.assertFalse(result.ok)
        self.assertEqual(result.issues[0].code, "raw-milliseconds")

    def test_invalid_id_and_cooldown_key_are_rejected(self):
        advice = _advice()
        advice["id"] = "Fuel Test!"
        advice["cooldown_key"] = "fuel test with spaces"

        result = review_race_engineer_advice([advice])

        self.assertFalse(result.ok)
        self.assertIn("invalid-id", [issue.code for issue in result.issues])
        self.assertIn("invalid-cooldown-key", [issue.code for issue in result.issues])

    def test_oversized_evidence_is_rejected(self):
        advice = _advice()
        advice["evidence"] = ["x" * 200]

        result = review_race_engineer_advice([advice])

        self.assertFalse(result.ok)
        self.assertEqual(result.issues[0].code, "evidence-too-long")

    def test_brief_contains_prompt_specs_and_review_summary(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65

        brief = build_race_engineer_brief(
            snapshot,
            {"available": True, "connected": True, "ok": False},
            focus="fuel",
        )

        self.assertTrue(brief["ok"])
        self.assertEqual(brief["advice_review"]["rejected_count"], 0)
        self.assertIn("fuel", brief["agent_prompt_specs"])
        self.assertIn("review", brief["agent_prompt_specs"])
        self.assertEqual(brief["advice"][0]["id"], "fuel-critical-deficit")

    def test_driving_coach_focus_returns_prompt_without_advice_until_trace_exists(self):
        brief = build_race_engineer_brief(
            _snapshot(),
            {"available": True, "connected": True, "ok": False},
            focus="driving_coach",
        )

        self.assertTrue(brief["ok"])
        self.assertEqual(brief["advice"], [])
        self.assertIn("driving_coach", brief["agent_prompt_specs"])
        self.assertIn("review", brief["agent_prompt_specs"])


def _advice():
    return {
        "id": "fuel-test",
        "category": "fuel",
        "priority": "warning",
        "title": "Fuel saving needed",
        "message": "Fuel is short. Lift and coast before the biggest braking zone.",
        "voice_callout": "Fuel minus three tenths. Start saving.",
        "cooldown_key": "fuel:test",
        "evidence": ["surplus-laps=-0.30"],
        "metrics": {"surplus_laps": -0.3},
    }


if __name__ == "__main__":
    unittest.main()
