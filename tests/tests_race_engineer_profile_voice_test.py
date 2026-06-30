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

import os
import json
import tempfile
import unittest

from apps.race_engineer.profile_voice_test import (
    build_profile_audio_question_test_command,
    build_profile_mic_question_test_command,
    build_profile_preflight_command,
    build_profile_question_test_command,
    build_profile_voice_test_command,
    format_profile_audio_question_test_output,
    format_profile_mic_question_test_output,
    format_profile_preflight_output,
    cleanup_temp_profile_for_smoke_test,
    format_profile_question_test_output,
    format_profile_voice_test_output,
    write_temp_profile_for_smoke_test,
)
from lib.race_engineer import RaceEngineerLaunchProfile, load_race_engineer_launch_profile


class TestRaceEngineerProfileVoiceTest(unittest.TestCase):
    def test_build_profile_voice_test_command_uses_python_module_in_dev(self):
        command = build_profile_voice_test_command(
            "C:\\temp\\profile.json",
            message="Radio check.",
            executable="python.exe",
            frozen=False,
        )

        self.assertEqual(command, [
            "python.exe",
            "-m",
            "apps.race_engineer",
            "--profile-file",
            "C:\\temp\\profile.json",
            "--profile-voice-test",
            "Radio check.",
        ])

    def test_build_profile_voice_test_command_uses_module_dispatcher_when_frozen(self):
        command = build_profile_voice_test_command(
            "C:\\temp\\profile.json",
            executable="pits_n_giggles.exe",
            frozen=True,
        )

        self.assertEqual(command[:3], ["pits_n_giggles.exe", "--module", "apps.race_engineer"])
        self.assertIn("--profile-voice-test", command)

    def test_build_profile_question_test_command_uses_python_module_in_dev(self):
        command = build_profile_question_test_command(
            "C:\\temp\\profile.json",
            question="как топливо?",
            executable="python.exe",
            frozen=False,
        )

        self.assertEqual(command, [
            "python.exe",
            "-m",
            "apps.race_engineer",
            "--profile-file",
            "C:\\temp\\profile.json",
            "--profile-question-test",
            "как топливо?",
        ])

    def test_build_profile_preflight_command_uses_python_module_in_dev(self):
        command = build_profile_preflight_command(
            "C:\\temp\\profile.json",
            question="как топливо?",
            executable="python.exe",
            frozen=False,
        )

        self.assertEqual(command, [
            "python.exe",
            "-m",
            "apps.race_engineer",
            "--profile-file",
            "C:\\temp\\profile.json",
            "--profile-preflight",
            "--profile-preflight-question",
            "как топливо?",
        ])

    def test_build_profile_preflight_command_defaults_to_pit_tyre_strategy_question(self):
        command = build_profile_preflight_command(
            "C:\\temp\\profile.json",
            executable="python.exe",
            frozen=False,
        )

        self.assertEqual(command, [
            "python.exe",
            "-m",
            "apps.race_engineer",
            "--profile-file",
            "C:\\temp\\profile.json",
            "--profile-preflight",
            "--profile-preflight-question",
            "какие шины брать на пит?",
        ])

    def test_build_profile_audio_question_test_command_uses_python_module_in_dev(self):
        command = build_profile_audio_question_test_command(
            "C:\\temp\\profile.json",
            "C:\\temp\\question.wav",
            executable="python.exe",
            frozen=False,
        )

        self.assertEqual(command, [
            "python.exe",
            "-m",
            "apps.race_engineer",
            "--profile-file",
            "C:\\temp\\profile.json",
            "--profile-audio-question-test",
            "C:\\temp\\question.wav",
        ])

    def test_build_profile_mic_question_test_command_uses_python_module_in_dev(self):
        command = build_profile_mic_question_test_command(
            "C:\\temp\\profile.json",
            seconds=2.5,
            executable="python.exe",
            frozen=False,
        )

        self.assertEqual(command, [
            "python.exe",
            "-m",
            "apps.race_engineer",
            "--profile-file",
            "C:\\temp\\profile.json",
            "--profile-mic-question-test-seconds",
            "2.5",
        ])

    def test_write_temp_profile_for_smoke_test_round_trips_and_cleans_up(self):
        profile = RaceEngineerLaunchProfile(
            voice_provider="azure",
            azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
            azure_key_env_var="PNG_AZURE_SPEECH_KEY",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_temp_profile_for_smoke_test(profile, directory=temp_dir)
            loaded = load_race_engineer_launch_profile(path)

            cleanup_temp_profile_for_smoke_test(path)

            self.assertEqual(loaded.voice_provider, "azure")
            self.assertEqual(loaded.azure_speech_endpoint, "https://francecentral.api.cognitive.microsoft.com/")
            self.assertFalse(os.path.exists(path))

    def test_cleanup_temp_profile_for_smoke_test_ignores_missing_file(self):
        cleanup_temp_profile_for_smoke_test("C:\\temp\\missing-race-engineer-profile.json")

    def test_format_profile_question_test_output_extracts_answer_json(self):
        output = """
noise before
{
  "ok": true,
  "answer": "Fuel is tight.",
  "source": "local_brief",
  "focus": "fuel"
}
"""

        formatted = format_profile_question_test_output(output)

        self.assertIn("Fuel is tight.", formatted)
        self.assertIn("local_brief", formatted)
        self.assertIn("fuel", formatted)

    def test_format_profile_question_test_output_reports_error_json(self):
        output = '{"ok": false, "error": "provider timed out"}'

        self.assertEqual(format_profile_question_test_output(output), "provider timed out")

    def test_format_profile_voice_test_output_extracts_runtime_error(self):
        output = """
Traceback (most recent call last):
  File "race_engineer.py", line 1, in <module>
RuntimeError: Azure Speech request failed with HTTP 400
"""

        self.assertEqual(
            format_profile_voice_test_output(output),
            "Azure Speech request failed with HTTP 400",
        )

    def test_format_profile_audio_question_test_output_summarises_full_pipeline(self):
        output = json.dumps({
            "ok": True,
            "speech": {"ok": True, "provider": "azure", "text": "как топливо?"},
            "question": {
                "ok": True,
                "answer": "Fuel is tight.",
                "source": "local_brief",
                "focus": "fuel",
            },
            "voice": {"ok": True, "provider": "dry_run"},
        })

        formatted = format_profile_audio_question_test_output(output)

        self.assertIn("Audio question test completed.", formatted)
        self.assertIn("Transcript: как топливо?", formatted)
        self.assertIn("Answer: Fuel is tight.", formatted)
        self.assertIn("Speech: OK (azure)", formatted)
        self.assertIn("Question: OK (local_brief)", formatted)
        self.assertIn("Voice: OK (dry_run)", formatted)

    def test_format_profile_mic_question_test_output_summarises_full_pipeline(self):
        output = json.dumps({
            "ok": True,
            "audio": {"source": "microphone", "provider": "windows_microphone"},
            "speech": {"ok": True, "provider": "azure", "text": "как топливо?"},
            "question": {
                "ok": True,
                "answer": "Fuel is tight.",
                "source": "local_brief",
                "focus": "fuel",
            },
            "voice": {"ok": True, "provider": "dry_run"},
        })

        formatted = format_profile_mic_question_test_output(output)

        self.assertIn("Mic PTT test completed.", formatted)
        self.assertIn("Transcript: как топливо?", formatted)
        self.assertIn("Answer: Fuel is tight.", formatted)

    def test_format_profile_audio_question_test_output_reports_error_json(self):
        output = '{"ok": false, "error": "speech recognition is not configured"}'

        self.assertEqual(
            format_profile_audio_question_test_output(output),
            "speech recognition is not configured",
        )

    def test_format_profile_preflight_output_summarises_sections(self):
        output = json.dumps({
            "ok": True,
            "diagnostics": [],
            "voice": {"ok": True, "provider": "dry_run"},
            "question": {
                "ok": True,
                "answer": "Fuel is tight.",
                "source": "local_brief",
                "focus": "fuel",
            },
            "push_to_talk": {
                "ok": True,
                "speech_provider": "azure",
                "audio_source": "windows_microphone",
                "message": "Windows microphone push-to-talk is configured. Run Mic PTT Test.",
            },
            "next_steps": [
                "Run Mic PTT Test before driving to verify the real microphone path.",
                "Save Race Engineer settings to apply UDP action bindings to a running backend.",
            ],
        })

        formatted = format_profile_preflight_output(output)

        self.assertIn("Preflight completed.", formatted)
        self.assertIn("Voice: OK (dry_run)", formatted)
        self.assertIn("Question: OK (local_brief)", formatted)
        self.assertIn("Push-to-talk: OK", formatted)
        self.assertIn("Run Mic PTT Test", formatted)
        self.assertIn("Fuel is tight.", formatted)
        self.assertIn("Next steps:", formatted)
        self.assertIn("- Run Mic PTT Test before driving to verify the real microphone path.", formatted)
        self.assertIn(
            "- Save Race Engineer settings to apply UDP action bindings to a running backend.",
            formatted,
        )

    def test_format_profile_preflight_output_reports_diagnostics_and_skips(self):
        output = json.dumps({
            "ok": False,
            "diagnostics": [{
                "severity": "error",
                "code": "conversation-http-endpoint-missing",
                "message": "HTTP endpoint missing.",
            }],
            "voice": {"ok": True, "provider": "dry_run"},
            "question": {"ok": False, "skipped": True, "error": "HTTP endpoint missing."},
            "next_steps": ["Fix the conversation provider settings, then run Question Test."],
        })

        formatted = format_profile_preflight_output(output)

        self.assertIn("Preflight found issues.", formatted)
        self.assertIn("Error: HTTP endpoint missing.", formatted)
        self.assertIn("Question: skipped", formatted)
        self.assertIn("- Fix the conversation provider settings, then run Question Test.", formatted)
