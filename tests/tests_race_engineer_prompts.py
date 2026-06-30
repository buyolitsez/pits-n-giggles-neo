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

import json
import tempfile
import unittest
from pathlib import Path

from lib.race_engineer import (
    build_agent_prompt_override_template,
    get_agent_prompt_specs,
    get_agent_prompt_texts,
    load_agent_prompt_overrides,
    normalise_agent_prompt_overrides,
    save_agent_prompt_override_template,
)


class TestRaceEngineerPrompts(unittest.TestCase):
    def test_all_prompt_specs_include_advisor_roles_and_review_agent(self):
        specs = get_agent_prompt_specs()

        self.assertIn("pace", specs)
        self.assertIn("tyres", specs)
        self.assertIn("fuel", specs)
        self.assertIn("ers", specs)
        self.assertIn("damage", specs)
        self.assertIn("weather", specs)
        self.assertIn("strategy", specs)
        self.assertIn("race_control", specs)
        self.assertIn("driving_coach", specs)
        self.assertIn("review", specs)
        self.assertEqual(specs["tyres"]["role"], "Tyre Engineer")
        self.assertEqual(specs["weather"]["role"], "Weather Engineer")
        self.assertIn("Use only", specs["review"]["base_rules"])

    def test_focus_returns_requested_agent_and_review_agent(self):
        prompts = get_agent_prompt_texts("fuel")

        self.assertEqual(set(prompts), {"fuel", "review"})
        self.assertIn("Fuel Engineer", prompts["fuel"])
        self.assertIn("fuel surplus", prompts["fuel"])
        self.assertIn("Review Agent", prompts["review"])

    def test_unknown_focus_falls_back_to_all_prompts(self):
        specs = get_agent_prompt_specs("unknown")

        self.assertIn("pace", specs)
        self.assertIn("review", specs)
        self.assertGreater(len(specs), 3)

    def test_prompt_overrides_change_only_selected_agent_fields(self):
        overrides = {
            "tyres": {
                "role": "Tyre Whisperer",
                "system_prompt": "Speak about tyre life like a calm race engineer.",
            }
        }

        specs = get_agent_prompt_specs("tyres", prompt_overrides=overrides)
        texts = get_agent_prompt_texts("tyres", prompt_overrides=overrides)

        self.assertEqual(specs["tyres"]["role"], "Tyre Whisperer")
        self.assertEqual(specs["tyres"]["system_prompt"], "Speak about tyre life like a calm race engineer.")
        self.assertIn("Use only", specs["tyres"]["base_rules"])
        self.assertIn("Tyre Whisperer", texts["tyres"])
        self.assertIn("Review Agent", texts["review"])

    def test_prompt_overrides_reject_unknown_categories_and_fields(self):
        with self.assertRaisesRegex(ValueError, "Unknown race engineer prompt category"):
            normalise_agent_prompt_overrides({"banana": {"role": "Nope"}})

        with self.assertRaisesRegex(ValueError, "Unknown prompt override field"):
            normalise_agent_prompt_overrides({"fuel": {"temperature": "warmer"}})

    def test_prompt_overrides_can_load_from_json_file(self):
        payload = {
            "prompts": {
                "fuel": {
                    "role": "Fuel Coach",
                    "call_policy": "Call fuel only when the next lap needs action.",
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "race-engineer-prompts.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            overrides = load_agent_prompt_overrides(str(path))

        self.assertEqual(overrides, {
            "fuel": {
                "role": "Fuel Coach",
                "call_policy": "Call fuel only when the next lap needs action.",
            }
        })

    def test_prompt_template_contains_every_category_and_loads_as_overrides(self):
        template = build_agent_prompt_override_template()

        self.assertEqual(template["schema"], "pits-n-giggles.race-engineer.agent-prompts.v1")
        prompts = template["prompts"]
        for category in (
                "pace", "tyres", "fuel", "ers", "damage", "weather",
                "strategy", "race_control", "driving_coach", "review"):
            with self.subTest(category=category):
                self.assertIn(category, prompts)
                self.assertIn("role", prompts[category])
                self.assertIn("system_prompt", prompts[category])
                self.assertIn("call_policy", prompts[category])

        overrides = normalise_agent_prompt_overrides(template)

        self.assertEqual(overrides["fuel"]["role"], "Fuel Engineer")
        self.assertEqual(overrides["review"]["role"], "Review Agent")

    def test_save_prompt_template_writes_json_and_protects_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "race-engineer-prompts.json"
            saved = save_agent_prompt_override_template(str(path))
            with self.assertRaises(FileExistsError):
                save_agent_prompt_override_template(str(path))
            save_agent_prompt_override_template(str(path), overwrite=True)
            overrides = load_agent_prompt_overrides(saved)

        self.assertIn("tyres", overrides)
        self.assertEqual(overrides["tyres"]["role"], "Tyre Engineer")


if __name__ == "__main__":
    unittest.main()
