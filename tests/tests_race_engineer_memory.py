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

import tempfile
import unittest
from pathlib import Path

from lib.race_engineer import (
    RaceEngineerMemory,
    apply_race_engineer_memory_feedback,
    load_race_engineer_memory,
    race_engineer_memory_answer_limits,
    race_engineer_memory_from_dict,
    race_engineer_memory_to_prompt_context,
    save_race_engineer_memory,
    save_race_engineer_memory_template,
)


class TestRaceEngineerMemory(unittest.TestCase):
    def test_missing_memory_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            memory = load_race_engineer_memory(str(Path(tmp_dir) / "missing.json"))

        self.assertEqual(memory, RaceEngineerMemory())
        self.assertEqual(race_engineer_memory_answer_limits(memory), (2, 180))

    def test_feedback_can_make_future_answers_concise(self):
        update = apply_race_engineer_memory_feedback(
            RaceEngineerMemory(),
            "запомни, не говори так много информации и не повторяйся",
        )

        self.assertTrue(update.applied)
        self.assertEqual(update.acknowledgement, "Запомнил. Дальше короче.")
        self.assertEqual(update.memory.verbosity, "concise")
        self.assertEqual(update.memory.max_sentences, 1)
        self.assertEqual(update.memory.max_chars, 110)
        self.assertTrue(update.memory.avoid_repeating)
        self.assertIn("shorter_answers", update.rules)
        self.assertIn("avoid_repeating", update.rules)
        self.assertTrue(update.memory.feedback_log)

    def test_non_feedback_question_does_not_update_memory(self):
        update = apply_race_engineer_memory_feedback(
            RaceEngineerMemory(),
            "какие шины брать на пит?",
        )

        self.assertFalse(update.applied)
        self.assertEqual(update.memory, RaceEngineerMemory())

    def test_memory_round_trips_as_editable_json(self):
        memory = race_engineer_memory_from_dict({
            "language_preference": "ru",
            "verbosity": "concise",
            "max_sentences": 3,
            "max_chars": 200,
            "avoid_phrases": ["держи ритм"],
            "style_notes": ["No long strategy lectures while braking."],
        })

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "race_engineer_memory.json"
            save_race_engineer_memory(memory, str(path))
            loaded = load_race_engineer_memory(str(path))

        self.assertEqual(loaded.language_preference, "ru")
        self.assertEqual(loaded.verbosity, "concise")
        self.assertEqual(loaded.max_sentences, 1)
        self.assertEqual(loaded.max_chars, 110)
        self.assertEqual(loaded.avoid_phrases, ("держи ритм",))
        self.assertEqual(loaded.style_notes, ("No long strategy lectures while braking.",))

    def test_prompt_context_exposes_driver_preferences(self):
        memory = RaceEngineerMemory(
            language_preference="ru",
            verbosity="concise",
            max_sentences=1,
            max_chars=90,
            avoid_repeating=True,
            style_notes=("Keep calls short under braking.",),
        )

        context = race_engineer_memory_to_prompt_context(memory)

        self.assertEqual(context["language_preference"], "ru")
        self.assertEqual(context["verbosity"], "concise")
        self.assertEqual(context["max_sentences"], 1)
        self.assertEqual(context["max_chars"], 90)
        self.assertTrue(context["avoid_repeating"])
        self.assertEqual(context["style_notes"], ["Keep calls short under braking."])

    def test_memory_template_refuses_to_overwrite_by_default(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "race_engineer_memory.json"
            save_race_engineer_memory_template(str(path))

            with self.assertRaises(FileExistsError):
                save_race_engineer_memory_template(str(path))


if __name__ == "__main__":
    unittest.main()
