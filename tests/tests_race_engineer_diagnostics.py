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
    RaceEngineerLaunchProfile,
    diagnose_race_engineer_launch_profile,
    format_race_engineer_profile_diagnostics,
    race_engineer_profile_has_errors,
)


class TestRaceEngineerProfileDiagnostics(unittest.TestCase):
    def test_default_profile_has_no_offline_diagnostics(self):
        diagnostics = diagnose_race_engineer_launch_profile(RaceEngineerLaunchProfile())

        self.assertEqual(diagnostics, [])
        self.assertEqual(format_race_engineer_profile_diagnostics(diagnostics), "Race Engineer profile looks ready.")
        self.assertFalse(race_engineer_profile_has_errors(diagnostics))

    def test_azure_voice_requires_location_and_key_env_var(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                voice_provider="azure",
                azure_region="",
                azure_speech_endpoint="",
                azure_key_env_var="PNG_AZURE_SPEECH_KEY",
            ),
            environ={},
        )

        self.assertEqual(_codes(diagnostics), ["azure-tts-location", "azure-tts-key-missing"])
        self.assertTrue(race_engineer_profile_has_errors(diagnostics))
        self.assertNotIn("secret", format_race_engineer_profile_diagnostics(diagnostics).lower())

    def test_azure_voice_accepts_https_endpoint_and_present_key(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                voice_provider="azure",
                azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
                azure_key_env_var="PNG_AZURE_SPEECH_KEY",
            ),
            environ={"PNG_AZURE_SPEECH_KEY": "secret"},
        )

        self.assertEqual(diagnostics, [])

    def test_azure_stt_warns_when_ptt_audio_is_external(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                speech_recognition_provider="azure",
                azure_region="francecentral",
                azure_key_env_var="PNG_AZURE_SPEECH_KEY",
                push_to_talk_audio_source="external",
            ),
            environ={"PNG_AZURE_SPEECH_KEY": "secret"},
        )

        self.assertEqual(_codes(diagnostics), ["ptt-external-audio"])
        self.assertFalse(race_engineer_profile_has_errors(diagnostics))

    def test_windows_microphone_is_error_off_windows(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                speech_recognition_provider="azure",
                azure_region="francecentral",
                azure_key_env_var="PNG_AZURE_SPEECH_KEY",
                push_to_talk_audio_source="windows_microphone",
            ),
            environ={"PNG_AZURE_SPEECH_KEY": "secret"},
            platform="linux",
        )

        self.assertEqual(_codes(diagnostics), ["ptt-windows-microphone-platform"])
        self.assertTrue(race_engineer_profile_has_errors(diagnostics))

    def test_http_conversation_requires_valid_endpoint(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                conversation_provider="http",
                conversation_endpoint="localhost:8765",
            )
        )

        self.assertEqual(_codes(diagnostics), ["conversation-http-endpoint-invalid"])

    def test_codex_cli_requires_command_and_warns_when_executable_is_missing(self):
        missing = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(conversation_provider="codex_cli")
        )
        not_found = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                conversation_provider="codex_cli",
                conversation_command="codex-wrapper --answer-race-engineer",
            ),
            command_exists=lambda _exe: False,
        )

        self.assertEqual(_codes(missing), ["conversation-command-missing"])
        self.assertEqual(_codes(not_found), ["conversation-command-not-found"])
        self.assertFalse(race_engineer_profile_has_errors(not_found))

    def test_prompt_file_must_exist_when_configured(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(agent_prompts_file="C:\\missing\\prompts.json"),
            path_exists=lambda _path: False,
        )

        self.assertEqual(_codes(diagnostics), ["agent-prompts-file-missing"])

    def test_udp_action_conflict_is_reported(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                speech_recognition_provider="azure",
                azure_region="francecentral",
                azure_key_env_var="PNG_AZURE_SPEECH_KEY",
                push_to_talk_audio_source="windows_microphone",
                race_engineer_toggle_udp_action_code=5,
                race_engineer_push_to_talk_udp_action_code=5,
            ),
            environ={"PNG_AZURE_SPEECH_KEY": "secret"},
            platform="win32",
        )

        self.assertEqual(_codes(diagnostics), ["udp-action-conflict"])

    def test_push_to_talk_binding_requires_speech_recognition(self):
        diagnostics = diagnose_race_engineer_launch_profile(
            RaceEngineerLaunchProfile(
                speech_recognition_provider="disabled",
                race_engineer_push_to_talk_udp_action_code=6,
            )
        )

        self.assertEqual(_codes(diagnostics), ["ptt-speech-recognition-disabled"])
        self.assertTrue(race_engineer_profile_has_errors(diagnostics))


def _codes(diagnostics):
    return [item.code for item in diagnostics]


if __name__ == "__main__":
    unittest.main()
