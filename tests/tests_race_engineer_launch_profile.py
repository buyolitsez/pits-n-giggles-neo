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
    RaceEngineerLaunchProfile,
    load_race_engineer_launch_profile,
    race_engineer_launch_profile_from_dict,
    race_engineer_launch_profile_to_cli_args,
    race_engineer_live_question_timeout_ms,
    race_engineer_profile_udp_action_code,
    race_engineer_profile_udp_action_codes,
    save_race_engineer_launch_profile,
)


class TestRaceEngineerLaunchProfile(unittest.TestCase):
    def test_profile_from_dict_normalises_values_and_never_stores_secret_key(self):
        profile = race_engineer_launch_profile_from_dict({
            "initial_enabled": "off",
            "focus": "tyres",
            "min_priority": "warning",
            "cooldown_seconds": "35",
            "voice_provider": "azure",
            "azure_key_env_var": "not a valid env var",
            "conversation_provider": "codex",
            "memory_file": "C:\\temp\\race-engineer-memory.json",
            "race_engineer_toggle_udp_action_code": 4,
            "race_engineer_push_to_talk_udp_action_code": 4,
        })

        self.assertFalse(profile.initial_enabled)
        self.assertEqual(profile.focus, "tyres")
        self.assertEqual(profile.min_priority, "warning")
        self.assertEqual(profile.cooldown_seconds, 35)
        self.assertEqual(profile.voice_provider, "azure")
        self.assertEqual(profile.azure_key_env_var, "PNG_AZURE_SPEECH_KEY")
        self.assertEqual(profile.conversation_provider, "local_brief")
        self.assertEqual(profile.memory_file, "C:\\temp\\race-engineer-memory.json")
        self.assertEqual(profile.race_engineer_toggle_udp_action_code, 4)
        self.assertIsNone(profile.race_engineer_push_to_talk_udp_action_code)

    def test_profile_round_trips_to_json(self):
        profile = RaceEngineerLaunchProfile(
            initial_enabled=False,
            voice_provider="azure",
            azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
            race_engineer_toggle_udp_action_code=8,
            race_engineer_push_to_talk_udp_action_code=9,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "race_engineer_profile.json"
            save_race_engineer_launch_profile(profile, str(path))
            loaded = load_race_engineer_launch_profile(str(path))

        self.assertEqual(loaded, profile)

    def test_missing_profile_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            loaded = load_race_engineer_launch_profile(str(Path(tmp_dir) / "missing.json"))

        self.assertEqual(loaded, RaceEngineerLaunchProfile())

    def test_cli_args_include_voice_question_and_prompt_settings(self):
        profile = RaceEngineerLaunchProfile(
            initial_enabled=False,
            voice_provider="azure",
            speech_recognition_provider="azure",
            push_to_talk_audio_source="windows_microphone",
            conversation_provider="codex_cli",
            conversation_command="codex exec --json",
            conversation_key_env_var="PNG_CODEX_PROXY_KEY",
            agent_prompts_file="C:\\temp\\prompts.json",
            memory_file="C:\\temp\\memory.json",
            no_audio_playback=True,
        )

        args = race_engineer_launch_profile_to_cli_args(profile)

        self.assertIn("--initial-enabled", args)
        self.assertEqual(args[args.index("--initial-enabled") + 1], "false")
        self.assertEqual(args[args.index("--voice-provider") + 1], "azure")
        self.assertEqual(args[args.index("--speech-recognition-provider") + 1], "azure")
        self.assertEqual(args[args.index("--push-to-talk-audio-source") + 1], "windows_microphone")
        self.assertEqual(args[args.index("--conversation-provider") + 1], "codex_cli")
        self.assertEqual(args[args.index("--conversation-command") + 1], "codex exec --json")
        self.assertEqual(args[args.index("--conversation-key-env-var") + 1], "PNG_CODEX_PROXY_KEY")
        self.assertEqual(args[args.index("--agent-prompts-file") + 1], "C:\\temp\\prompts.json")
        self.assertEqual(args[args.index("--memory-file") + 1], "C:\\temp\\memory.json")
        self.assertIn("--no-audio-playback", args)

    def test_codex_cli_provider_survives_profile_normalisation(self):
        profile = race_engineer_launch_profile_from_dict({
            "conversation_provider": "codex-cli",
            "conversation_command": 'codex exec --profile race-engineer',
        })

        self.assertEqual(profile.conversation_provider, "codex_cli")
        self.assertEqual(profile.conversation_command, "codex exec --profile race-engineer")

    def test_udp_action_codes_are_exposed_for_backend_bridge(self):
        profile = RaceEngineerLaunchProfile(
            race_engineer_toggle_udp_action_code=7,
            race_engineer_push_to_talk_udp_action_code=8,
        )

        self.assertEqual(race_engineer_profile_udp_action_codes(profile), {
            "race_engineer_toggle": 7,
            "race_engineer_push_to_talk": 8,
        })

    def test_profile_udp_action_code_ignores_conflicts(self):
        profile = RaceEngineerLaunchProfile(race_engineer_toggle_udp_action_code=7)

        self.assertEqual(
            race_engineer_profile_udp_action_code(profile, "race_engineer_toggle_udp_action_code"),
            7,
        )
        self.assertIsNone(
            race_engineer_profile_udp_action_code(
                profile,
                "race_engineer_toggle_udp_action_code",
                existing_codes={7: "HUD.toggle_overlays_udp_action_code"},
            )
        )

    def test_live_question_timeout_follows_profile_conversation_timeout(self):
        self.assertEqual(
            race_engineer_live_question_timeout_ms(
                RaceEngineerLaunchProfile(conversation_timeout_seconds=0.1)
            ),
            3000,
        )
        self.assertEqual(
            race_engineer_live_question_timeout_ms(
                RaceEngineerLaunchProfile(conversation_timeout_seconds=12.5)
            ),
            14500,
        )

    def test_json_unknown_fields_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "race_engineer_profile.json"
            path.write_text(json.dumps({"unknown": "ignored", "voice_provider": "azure"}), encoding="utf-8")
            loaded = load_race_engineer_launch_profile(str(path))

        self.assertEqual(loaded.voice_provider, "azure")


if __name__ == "__main__":
    unittest.main()
