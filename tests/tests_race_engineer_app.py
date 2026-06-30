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

import asyncio
import json
import os
import logging
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from apps.race_engineer.race_engineer import (
    RaceEngineerApp,
    build_agent_prompt_overrides,
    build_conversation_agent,
    build_microphone_capture,
    build_speech_recognizer,
    build_voice_engine,
    load_question_test_snapshot,
    main,
    parse_args,
    run_profile_check,
    run_profile_audio_question_test,
    run_profile_mic_question_test,
    run_profile_preflight,
    run_profile_question_test,
    run_profile_voice_test,
    run_question_test,
    run_write_agent_prompts_template,
)
from lib.race_engineer import (
    AzureSpeechRecognizer,
    AzureSpeechVoiceEngine,
    CodexCliConversationAgent,
    FallbackConversationAgent,
    LocalBriefConversationAgent,
    MicrophoneCaptureConfig,
    NullVoiceEngine,
    RaceEngineerLaunchProfile,
    RaceEngineerAnnouncement,
    RaceEngineerAnswer,
    SpeechRecognitionResult,
    VoiceResult,
    save_race_engineer_launch_profile,
)


class TestRaceEngineerAppArgs(unittest.TestCase):
    def test_env_defaults_configure_launcher_managed_voice(self):
        with patch.object(sys, "argv", ["apps.race_engineer", "--managed"]):
            with patch.dict(os.environ, {
                "PNG_RACE_ENGINEER_FOCUS": "tyres",
                "PNG_RACE_ENGINEER_MIN_PRIORITY": "advisory",
                "PNG_RACE_ENGINEER_COOLDOWN_SECONDS": "12",
                "PNG_RACE_ENGINEER_MAX_ITEMS": "2",
                "PNG_RACE_ENGINEER_MAX_QUEUE_SIZE": "1",
                "PNG_RACE_ENGINEER_MIN_VOICE_INTERVAL_SECONDS": "6.5",
                "PNG_RACE_ENGINEER_INITIAL_ENABLED": "false",
                "PNG_RACE_ENGINEER_VOICE_PROVIDER": "azure",
                "PNG_RACE_ENGINEER_SPEECH_RECOGNITION_PROVIDER": "azure",
                "PNG_RACE_ENGINEER_PUSH_TO_TALK_AUDIO_SOURCE": "windows_microphone",
                "PNG_RACE_ENGINEER_AGENT_PROMPTS_FILE": "C:\\temp\\race-engineer-prompts.json",
                "PNG_RACE_ENGINEER_CONVERSATION_PROVIDER": "http",
                "PNG_RACE_ENGINEER_CONVERSATION_ENDPOINT": "http://127.0.0.1:8765/race-engineer/answer",
                "PNG_RACE_ENGINEER_CONVERSATION_KEY_ENV_VAR": "PNG_CODEX_PROXY_KEY",
                "PNG_RACE_ENGINEER_CONVERSATION_COMMAND": "codex exec",
                "PNG_RACE_ENGINEER_CONVERSATION_TIMEOUT_SECONDS": "3.5",
                "PNG_AZURE_SPEECH_REGION": "westeurope",
                "PNG_AZURE_SPEECH_ENDPOINT": "https://francecentral.api.cognitive.microsoft.com/",
                "PNG_AZURE_SPEECH_VOICE": "en-US-GuyNeural",
                "PNG_AZURE_SPEECH_KEY_ENV_VAR": "MY_TEST_KEY",
                "PNG_AZURE_SPEECH_OUTPUT_FORMAT": "riff-24khz-16bit-mono-pcm",
                "PNG_AZURE_STT_LANGUAGE": "ru-RU",
                "PNG_AZURE_STT_FORMAT": "detailed",
                "PNG_AZURE_STT_CONTENT_TYPE": "audio/wav; codecs=audio/pcm; samplerate=16000",
            }):
                args = parse_args()

        self.assertTrue(args.managed)
        self.assertEqual(args.focus, "tyres")
        self.assertEqual(args.min_priority, "advisory")
        self.assertEqual(args.cooldown_seconds, 12)
        self.assertEqual(args.max_items, 2)
        self.assertEqual(args.max_queue_size, 1)
        self.assertEqual(args.min_voice_interval_seconds, 6.5)
        self.assertFalse(args.initial_enabled)
        self.assertEqual(args.voice_provider, "azure")
        self.assertEqual(args.speech_recognition_provider, "azure")
        self.assertEqual(args.push_to_talk_audio_source, "windows_microphone")
        self.assertEqual(args.agent_prompts_file, "C:\\temp\\race-engineer-prompts.json")
        self.assertEqual(args.conversation_provider, "http")
        self.assertEqual(args.conversation_endpoint, "http://127.0.0.1:8765/race-engineer/answer")
        self.assertEqual(args.conversation_key_env_var, "PNG_CODEX_PROXY_KEY")
        self.assertEqual(args.conversation_command, "codex exec")
        self.assertEqual(args.conversation_timeout_seconds, 3.5)
        self.assertEqual(args.azure_region, "westeurope")
        self.assertEqual(args.azure_speech_endpoint, "https://francecentral.api.cognitive.microsoft.com/")
        self.assertEqual(args.azure_voice, "en-US-GuyNeural")
        self.assertEqual(args.azure_key_env_var, "MY_TEST_KEY")
        self.assertEqual(args.azure_output_format, "riff-24khz-16bit-mono-pcm")
        self.assertEqual(args.azure_stt_language, "ru-RU")
        self.assertEqual(args.azure_stt_format, "detailed")
        self.assertEqual(args.azure_stt_content_type, "audio/wav; codecs=audio/pcm; samplerate=16000")

    def test_invalid_integer_env_defaults_are_ignored(self):
        with patch.object(sys, "argv", ["apps.race_engineer"]):
            with patch.dict(os.environ, {
                "PNG_RACE_ENGINEER_COOLDOWN_SECONDS": "soon",
                "PNG_RACE_ENGINEER_MAX_ITEMS": "many",
                "PNG_RACE_ENGINEER_MAX_QUEUE_SIZE": "full",
                "PNG_RACE_ENGINEER_MIN_VOICE_INTERVAL_SECONDS": "often",
            }):
                args = parse_args()

        self.assertEqual(args.cooldown_seconds, 20)
        self.assertEqual(args.max_items, 5)
        self.assertEqual(args.max_queue_size, 3)
        self.assertEqual(args.min_voice_interval_seconds, 4.0)

    def test_voice_test_arg_uses_default_message(self):
        with patch.object(sys, "argv", ["apps.race_engineer", "--voice-test"]):
            args = parse_args()

        self.assertEqual(args.voice_test, "Race engineer online.")

    def test_profile_voice_test_arg_uses_default_message(self):
        with patch.object(sys, "argv", ["apps.race_engineer", "--profile-voice-test"]):
            args = parse_args()

        self.assertEqual(args.profile_voice_test, "Race engineer online.")

    def test_profile_voice_test_arg_accepts_custom_message_and_profile_file(self):
        args = parse_args([
            "--profile-voice-test",
            "Radio check.",
            "--profile-file",
            "C:\\temp\\race_engineer_profile.json",
        ])

        self.assertEqual(args.profile_voice_test, "Radio check.")
        self.assertEqual(args.profile_file, "C:\\temp\\race_engineer_profile.json")

    def test_profile_question_test_arg_accepts_custom_question_and_profile_file(self):
        args = parse_args([
            "--profile-question-test",
            "как топливо?",
            "--profile-file",
            "C:\\temp\\race_engineer_profile.json",
        ])

        self.assertEqual(args.profile_question_test, "как топливо?")
        self.assertEqual(args.profile_file, "C:\\temp\\race_engineer_profile.json")

    def test_profile_audio_question_test_arg_accepts_audio_file_and_profile_file(self):
        args = parse_args([
            "--profile-audio-question-test",
            "C:\\temp\\question.wav",
            "--profile-file",
            "C:\\temp\\race_engineer_profile.json",
        ])

        self.assertEqual(args.profile_audio_question_test, "C:\\temp\\question.wav")
        self.assertEqual(args.profile_file, "C:\\temp\\race_engineer_profile.json")

    def test_profile_mic_question_test_arg_accepts_seconds_and_profile_file(self):
        args = parse_args([
            "--profile-mic-question-test-seconds",
            "2.5",
            "--profile-file",
            "C:\\temp\\race_engineer_profile.json",
        ])

        self.assertEqual(args.profile_mic_question_test_seconds, 2.5)
        self.assertEqual(args.profile_file, "C:\\temp\\race_engineer_profile.json")

    def test_profile_preflight_arg_accepts_question_and_profile_file(self):
        args = parse_args([
            "--profile-preflight",
            "--profile-preflight-question",
            "как топливо?",
            "--profile-file",
            "C:\\temp\\race_engineer_profile.json",
        ])

        self.assertTrue(args.profile_preflight)
        self.assertEqual(args.profile_preflight_question, "как топливо?")
        self.assertEqual(args.profile_file, "C:\\temp\\race_engineer_profile.json")

    def test_profile_preflight_arg_defaults_to_pit_tyre_strategy_question(self):
        args = parse_args(["--profile-preflight"])

        self.assertTrue(args.profile_preflight)
        self.assertEqual(args.profile_preflight_question, "какие шины брать на пит?")

    def test_profile_check_arg_accepts_optional_profile_file(self):
        with patch.object(sys, "argv", [
            "apps.race_engineer",
            "--profile-check",
            "--profile-file",
            "C:\\temp\\race_engineer_profile.json",
        ]):
            args = parse_args()

        self.assertTrue(args.profile_check)
        self.assertEqual(args.profile_file, "C:\\temp\\race_engineer_profile.json")

    def test_question_test_arg_accepts_optional_snapshot_file(self):
        with patch.object(sys, "argv", [
            "apps.race_engineer",
            "--question-test",
            "как топливо?",
            "--question-snapshot",
            "C:\\temp\\race-table-update.json",
        ]):
            args = parse_args()

        self.assertEqual(args.question_test, "как топливо?")
        self.assertEqual(args.question_snapshot, "C:\\temp\\race-table-update.json")

    def test_write_agent_prompts_template_arg_accepts_overwrite(self):
        with patch.object(sys, "argv", [
            "apps.race_engineer",
            "--write-agent-prompts-template",
            "C:\\temp\\race-engineer-prompts.json",
            "--overwrite-agent-prompts-template",
        ]):
            args = parse_args()

        self.assertEqual(args.write_agent_prompts_template, "C:\\temp\\race-engineer-prompts.json")
        self.assertTrue(args.overwrite_agent_prompts_template)

    def test_initial_enabled_cli_accepts_boolean_text(self):
        with patch.object(sys, "argv", ["apps.race_engineer", "--initial-enabled", "false"]):
            args = parse_args()

        self.assertFalse(args.initial_enabled)

    def test_build_speech_recognizer_builds_azure_provider(self):
        args = types.SimpleNamespace(
            speech_recognition_provider="azure",
            azure_region="francecentral",
            azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
            azure_key_env_var="PNG_TEST_AZURE_KEY",
            azure_stt_language="ru-RU",
            azure_stt_format="simple",
            azure_stt_content_type="audio/wav",
        )

        recognizer = build_speech_recognizer(args)

        self.assertIsInstance(recognizer, AzureSpeechRecognizer)

    def test_build_voice_engine_passes_azure_endpoint_to_tts(self):
        args = types.SimpleNamespace(
            voice_provider="azure",
            azure_region="",
            azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
            azure_voice="en-US-GuyNeural",
            azure_key_env_var="PNG_TEST_AZURE_KEY",
            azure_output_format="riff-24khz-16bit-mono-pcm",
            no_audio_playback=True,
        )

        engine = build_voice_engine(args, _SilentLogger())

        self.assertIsInstance(engine, AzureSpeechVoiceEngine)
        self.assertEqual(
            engine._config.endpoint_url(),
            "https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1",
        )

    def test_build_microphone_capture_ignores_windows_source_off_windows(self):
        args = types.SimpleNamespace(push_to_talk_audio_source="windows_microphone")

        with patch.object(sys, "platform", "linux"):
            capture = build_microphone_capture(args, _SilentLogger())

        self.assertIsNone(capture)

    def test_build_agent_prompt_overrides_returns_empty_when_file_missing(self):
        args = types.SimpleNamespace(agent_prompts_file="C:\\missing\\race-engineer-prompts.json")

        overrides = build_agent_prompt_overrides(args, _SilentLogger())

        self.assertEqual(overrides, {})

    def test_build_conversation_agent_uses_local_provider_by_default(self):
        args = types.SimpleNamespace(conversation_provider="local_brief")

        agent = build_conversation_agent(args, _SilentLogger(), {})

        self.assertIsInstance(agent, LocalBriefConversationAgent)

    def test_build_conversation_agent_http_wraps_with_local_fallback(self):
        args = types.SimpleNamespace(
            conversation_provider="http",
            conversation_endpoint="http://127.0.0.1:8765/race-engineer/answer",
            conversation_key_env_var="PNG_CODEX_PROXY_KEY",
            conversation_timeout_seconds=2.0,
        )

        agent = build_conversation_agent(args, _SilentLogger(), {})

        self.assertIsInstance(agent, FallbackConversationAgent)

    def test_build_conversation_agent_http_without_endpoint_uses_local(self):
        args = types.SimpleNamespace(
            conversation_provider="http",
            conversation_endpoint="",
            conversation_key_env_var="",
            conversation_timeout_seconds=2.0,
        )

        agent = build_conversation_agent(args, _SilentLogger(), {})

        self.assertIsInstance(agent, LocalBriefConversationAgent)

    def test_build_conversation_agent_codex_cli_wraps_with_local_fallback(self):
        args = types.SimpleNamespace(
            conversation_provider="codex_cli",
            conversation_command="codex exec --json",
            conversation_timeout_seconds=2.0,
        )

        agent = build_conversation_agent(args, _SilentLogger(), {})

        self.assertIsInstance(agent, FallbackConversationAgent)
        self.assertIsInstance(agent.primary, CodexCliConversationAgent)
        self.assertEqual(agent.primary.config.command, "codex exec --json")

    def test_build_conversation_agent_codex_cli_without_command_uses_local(self):
        args = types.SimpleNamespace(
            conversation_provider="codex_cli",
            conversation_command="",
            conversation_timeout_seconds=2.0,
        )

        agent = build_conversation_agent(args, _SilentLogger(), {})

        self.assertIsInstance(agent, LocalBriefConversationAgent)

    def test_build_speech_recognizer_disables_unknown_provider(self):
        args = types.SimpleNamespace(speech_recognition_provider="mystery")

        self.assertIsNone(build_speech_recognizer(args))

    def test_run_profile_check_reports_invalid_profile_without_loading_secrets(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    conversation_provider="http",
                    conversation_endpoint="localhost:8765",
                ),
                path,
            )

            with patch("builtins.print") as print_mock:
                ok = run_profile_check(types.SimpleNamespace(profile_file=path))

        self.assertFalse(ok)
        printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("HTTP conversation endpoint", printed)
        self.assertNotIn("secret", printed.lower())

    def test_run_profile_voice_test_uses_saved_profile_voice_settings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    voice_provider="azure",
                    azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
                    azure_voice="en-US-GuyNeural",
                    azure_key_env_var="PNG_TEST_AZURE_KEY",
                    no_audio_playback=True,
                ),
                path,
            )
            voice_engine = _RecordingVoiceEngine()
            captured = {}

            def _build_voice_engine(args, _logger):
                captured["args"] = args
                return voice_engine

            args = types.SimpleNamespace(
                profile_file=path,
                profile_voice_test="Radio check.",
                debug=True,
                managed=False,
                log_file="unused.log",
            )

            with patch("apps.race_engineer.race_engineer.build_voice_engine", side_effect=_build_voice_engine):
                result = asyncio.run(run_profile_voice_test(args, _SilentLogger()))

        self.assertTrue(result.ok)
        self.assertEqual(voice_engine.calls[0]["text"], "Radio check.")
        self.assertEqual(captured["args"].voice_provider, "azure")
        self.assertEqual(
            captured["args"].azure_speech_endpoint,
            "https://francecentral.api.cognitive.microsoft.com/",
        )
        self.assertEqual(captured["args"].azure_key_env_var, "PNG_TEST_AZURE_KEY")
        self.assertTrue(captured["args"].no_audio_playback)

    def test_run_profile_question_test_uses_saved_conversation_settings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            prompts_path = os.path.join(tmp_dir, "prompts.json")
            with open(prompts_path, "w", encoding="utf-8") as file_obj:
                json.dump({"prompts": {"fuel": {"role": "Fuel Coach"}}}, file_obj)
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    conversation_provider="http",
                    conversation_endpoint="http://127.0.0.1:8765/race-engineer/answer",
                    conversation_key_env_var="PNG_CODEX_PROXY_KEY",
                    conversation_timeout_seconds=3.5,
                    agent_prompts_file=prompts_path,
                ),
                path,
            )
            fake_agent = _FakeConversationAgent(
                RaceEngineerAnswer(
                    ok=True,
                    question="",
                    answer="Fuel is tight.",
                    source="fake",
                    focus="fuel",
                )
            )
            captured = {}

            def _build_conversation_agent(args, _logger, prompt_overrides):
                captured["args"] = args
                captured["prompt_overrides"] = prompt_overrides
                return fake_agent

            args = types.SimpleNamespace(
                profile_file=path,
                profile_question_test="как топливо?",
                question_snapshot="",
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch("apps.race_engineer.race_engineer.build_conversation_agent",
                       side_effect=_build_conversation_agent):
                with patch("builtins.print"):
                    answer = asyncio.run(run_profile_question_test(args, _SilentLogger()))

        self.assertTrue(answer.ok)
        self.assertEqual(fake_agent.calls[0]["question"], "как топливо?")
        self.assertEqual(captured["args"].conversation_provider, "http")
        self.assertEqual(captured["args"].conversation_endpoint, "http://127.0.0.1:8765/race-engineer/answer")
        self.assertEqual(captured["args"].conversation_key_env_var, "PNG_CODEX_PROXY_KEY")
        self.assertEqual(captured["args"].conversation_timeout_seconds, 3.5)
        self.assertIn("fuel", captured["prompt_overrides"])

    def test_run_profile_audio_question_test_transcribes_answers_and_speaks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile_path = os.path.join(tmp_dir, "race_engineer_profile.json")
            audio_path = os.path.join(tmp_dir, "question.wav")
            with open(audio_path, "wb") as file_obj:
                file_obj.write(b"RIFFaudio")
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    voice_provider="dry_run",
                    speech_recognition_provider="azure",
                    azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
                    azure_key_env_var="PNG_TEST_AZURE_KEY",
                    azure_stt_content_type="audio/wav",
                    conversation_provider="local_brief",
                ),
                profile_path,
            )
            speech_recognizer = _FakeSpeechRecognizer(
                SpeechRecognitionResult(ok=True, provider="fake_stt", text="как топливо?")
            )
            voice_engine = _RecordingVoiceEngine()
            captured = {}

            def _build_speech_recognizer(args):
                captured["speech_args"] = args
                return speech_recognizer

            def _build_voice_engine(args, _logger):
                captured["voice_args"] = args
                return voice_engine

            args = types.SimpleNamespace(
                profile_file=profile_path,
                profile_audio_question_test=audio_path,
                question_snapshot="",
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch("apps.race_engineer.race_engineer.build_speech_recognizer",
                       side_effect=_build_speech_recognizer):
                with patch("apps.race_engineer.race_engineer.build_voice_engine",
                           side_effect=_build_voice_engine):
                    with patch("builtins.print") as print_mock:
                        summary = asyncio.run(run_profile_audio_question_test(args, _SilentLogger()))

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["speech"]["text"], "как топливо?")
        self.assertTrue(summary["question"]["ok"])
        self.assertTrue(summary["voice"]["ok"])
        self.assertEqual(speech_recognizer.calls[0]["audio"], b"RIFFaudio")
        self.assertEqual(speech_recognizer.calls[0]["content_type"], "audio/wav")
        self.assertIn("топливо", voice_engine.calls[0]["text"].lower())
        self.assertEqual(captured["speech_args"].speech_recognition_provider, "azure")
        self.assertEqual(captured["voice_args"].voice_provider, "dry_run")
        payload = json.loads(print_mock.call_args_list[0].args[0])
        self.assertTrue(payload["ok"])

    def test_run_profile_mic_question_test_records_transcribes_answers_and_speaks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile_path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    voice_provider="dry_run",
                    speech_recognition_provider="azure",
                    azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
                    azure_key_env_var="PNG_TEST_AZURE_KEY",
                    conversation_provider="local_brief",
                    push_to_talk_audio_source="windows_microphone",
                ),
                profile_path,
            )
            speech_recognizer = _FakeSpeechRecognizer(
                SpeechRecognitionResult(ok=True, provider="fake_stt", text="как топливо?")
            )
            voice_engine = _RecordingVoiceEngine()
            microphone_capture = _FakeMicrophoneCapture(chunks=[b"\x00\x00" * 20, b"\x01\x00" * 20])

            async def _no_sleep(_seconds):
                return None

            args = types.SimpleNamespace(
                profile_file=profile_path,
                profile_mic_question_test_seconds=1.5,
                question_snapshot="",
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch("apps.race_engineer.race_engineer.build_speech_recognizer",
                       return_value=speech_recognizer):
                with patch("apps.race_engineer.race_engineer.build_voice_engine",
                           return_value=voice_engine):
                    with patch("apps.race_engineer.race_engineer.build_microphone_capture",
                               return_value=microphone_capture):
                        with patch("apps.race_engineer.race_engineer.asyncio.sleep",
                                   side_effect=_no_sleep):
                            with patch("builtins.print") as print_mock:
                                summary = asyncio.run(run_profile_mic_question_test(args, _SilentLogger()))

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["audio"]["source"], "microphone")
        self.assertEqual(summary["audio"]["raw_bytes"], 80)
        self.assertEqual(summary["audio"]["chunks"], 2)
        self.assertEqual(microphone_capture.starts, 1)
        self.assertEqual(microphone_capture.stops, 1)
        self.assertTrue(speech_recognizer.calls[0]["audio"].startswith(b"RIFF"))
        self.assertTrue(speech_recognizer.calls[0]["content_type"].startswith("audio/wav"))
        self.assertIn("топливо", voice_engine.calls[0]["text"].lower())
        payload = json.loads(print_mock.call_args_list[0].args[0])
        self.assertTrue(payload["ok"])

    def test_run_profile_preflight_reports_voice_and_question_ok(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    voice_provider="dry_run",
                    conversation_provider="local_brief",
                ),
                path,
            )
            args = types.SimpleNamespace(
                profile_file=path,
                profile_voice_test="Radio check.",
                profile_preflight_question="как топливо?",
                question_snapshot="",
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch("builtins.print") as print_mock:
                summary = asyncio.run(run_profile_preflight(args, _SilentLogger()))

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["voice"]["ok"])
        self.assertEqual(summary["voice"]["provider"], "dry_run")
        self.assertTrue(summary["question"]["ok"])
        self.assertEqual(summary["question"]["question"], "как топливо?")
        self.assertTrue(summary["push_to_talk"]["ok"])
        self.assertTrue(summary["push_to_talk"]["skipped"])
        self.assertFalse(summary["push_to_talk"]["configured"])
        payload = json.loads(print_mock.call_args_list[0].args[0])
        self.assertTrue(payload["ok"])

    def test_run_profile_preflight_reports_windows_microphone_ptt_readiness(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    voice_provider="dry_run",
                    conversation_provider="local_brief",
                    speech_recognition_provider="azure",
                    azure_speech_endpoint="https://francecentral.api.cognitive.microsoft.com/",
                    azure_key_env_var="PNG_TEST_AZURE_KEY",
                    push_to_talk_audio_source="windows_microphone",
                    race_engineer_push_to_talk_udp_action_code=12,
                ),
                path,
            )
            args = types.SimpleNamespace(
                profile_file=path,
                profile_voice_test="Radio check.",
                profile_preflight_question="как топливо?",
                question_snapshot="",
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch.dict(os.environ, {"PNG_TEST_AZURE_KEY": "secret"}):
                with patch("builtins.print") as print_mock:
                    summary = asyncio.run(run_profile_preflight(args, _SilentLogger()))

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["push_to_talk"]["ok"])
        self.assertTrue(summary["push_to_talk"]["configured"])
        self.assertTrue(summary["push_to_talk"]["udp_action_bound"])
        self.assertEqual(summary["push_to_talk"]["audio_source"], "windows_microphone")
        self.assertTrue(summary["push_to_talk"]["live_test_recommended"])
        self.assertFalse(summary["push_to_talk"]["live_tested"])
        payload = json.loads(print_mock.call_args_list[0].args[0])
        self.assertEqual(payload["push_to_talk"]["speech_provider"], "azure")

    def test_run_profile_preflight_skips_question_with_blocking_conversation_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(
                RaceEngineerLaunchProfile(
                    voice_provider="dry_run",
                    conversation_provider="http",
                    conversation_endpoint="",
                ),
                path,
            )
            args = types.SimpleNamespace(
                profile_file=path,
                profile_voice_test="Radio check.",
                profile_preflight_question="как топливо?",
                question_snapshot="",
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch("builtins.print"):
                summary = asyncio.run(run_profile_preflight(args, _SilentLogger()))

        self.assertFalse(summary["ok"])
        self.assertTrue(summary["voice"]["ok"])
        self.assertTrue(summary["question"]["skipped"])
        codes = {item["code"] for item in summary["diagnostics"]}
        self.assertIn("conversation-http-endpoint-missing", codes)

    def test_main_profile_check_returns_before_voice_and_config_setup(self):
        args = types.SimpleNamespace(profile_check=True, profile_file="", wd=None)

        with patch(
                "apps.race_engineer.race_engineer.load_race_engineer_launch_profile",
                return_value=RaceEngineerLaunchProfile()):
            with patch("apps.race_engineer.race_engineer.build_voice_engine") as build_voice:
                with patch("builtins.print"):
                    asyncio.run(main(args))

        build_voice.assert_not_called()

    def test_main_profile_voice_test_returns_before_conversation_and_config_setup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(RaceEngineerLaunchProfile(voice_provider="dry_run"), path)
            voice_engine = _RecordingVoiceEngine()
            args = types.SimpleNamespace(
                profile_check=False,
                write_agent_prompts_template="",
                profile_voice_test="Radio check.",
                profile_file=path,
                wd=None,
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch("apps.race_engineer.race_engineer.build_voice_engine", return_value=voice_engine):
                with patch("apps.race_engineer.race_engineer.get_logger", return_value=_SilentLogger()):
                    with patch("apps.race_engineer.race_engineer.build_agent_prompt_overrides") as build_prompts:
                        with patch("apps.race_engineer.race_engineer.build_conversation_agent") as build_agent:
                            asyncio.run(main(args))

        self.assertEqual(voice_engine.calls[0]["text"], "Radio check.")
        build_prompts.assert_not_called()
        build_agent.assert_not_called()

    def test_main_profile_preflight_returns_before_config_setup(self):
        args = types.SimpleNamespace(
            profile_check=False,
            write_agent_prompts_template="",
            profile_preflight=True,
            wd=None,
            debug=False,
            managed=False,
            log_file="unused.log",
        )

        with patch("apps.race_engineer.race_engineer.run_profile_preflight",
                   return_value={"ok": True}) as preflight:
            with patch("apps.race_engineer.race_engineer.build_voice_engine") as build_voice:
                with patch("apps.race_engineer.race_engineer.get_logger", return_value=_SilentLogger()):
                    asyncio.run(main(args))

        preflight.assert_called_once()
        build_voice.assert_not_called()

    def test_main_profile_audio_question_test_returns_before_config_setup(self):
        args = types.SimpleNamespace(
            profile_check=False,
            write_agent_prompts_template="",
            profile_preflight=False,
            profile_audio_question_test="C:\\temp\\question.wav",
            wd=None,
            debug=False,
            managed=False,
            log_file="unused.log",
        )

        with patch("apps.race_engineer.race_engineer.run_profile_audio_question_test",
                   return_value={"ok": True}) as audio_test:
            with patch("apps.race_engineer.race_engineer.build_voice_engine") as build_voice:
                with patch("apps.race_engineer.race_engineer.get_logger", return_value=_SilentLogger()):
                    asyncio.run(main(args))

        audio_test.assert_called_once()
        build_voice.assert_not_called()

    def test_main_profile_mic_question_test_returns_before_config_setup(self):
        args = types.SimpleNamespace(
            profile_check=False,
            write_agent_prompts_template="",
            profile_preflight=False,
            profile_audio_question_test="",
            profile_mic_question_test_seconds=2.0,
            wd=None,
            debug=False,
            managed=False,
            log_file="unused.log",
        )

        with patch("apps.race_engineer.race_engineer.run_profile_mic_question_test",
                   return_value={"ok": True}) as mic_test:
            with patch("apps.race_engineer.race_engineer.build_voice_engine") as build_voice:
                with patch("apps.race_engineer.race_engineer.get_logger", return_value=_SilentLogger()):
                    asyncio.run(main(args))

        mic_test.assert_called_once()
        build_voice.assert_not_called()

    def test_main_profile_question_test_returns_before_voice_and_config_setup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race_engineer_profile.json")
            save_race_engineer_launch_profile(RaceEngineerLaunchProfile(conversation_provider="local_brief"), path)
            args = types.SimpleNamespace(
                profile_check=False,
                write_agent_prompts_template="",
                profile_voice_test=None,
                profile_question_test="как топливо?",
                profile_file=path,
                question_snapshot="",
                wd=None,
                debug=False,
                managed=False,
                log_file="unused.log",
            )

            with patch("apps.race_engineer.race_engineer.build_voice_engine") as build_voice:
                with patch("apps.race_engineer.race_engineer.get_logger", return_value=_SilentLogger()):
                    with patch("builtins.print"):
                        asyncio.run(main(args))

        build_voice.assert_not_called()

    def test_load_question_test_snapshot_uses_sample_when_path_is_empty(self):
        snapshot = load_question_test_snapshot("")

        self.assertEqual(snapshot["session-uid"], 9001)
        self.assertTrue(snapshot["table-entries"][1]["driver-info"]["is-player"])
        self.assertLess(snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"], 0)

    def test_load_question_test_snapshot_extracts_wrapped_race_table_update(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "snapshot.json")
            expected = {"session-uid": 42, "table-entries": []}
            with open(path, "w", encoding="utf-8") as file_obj:
                json.dump({"race-table-update": expected}, file_obj)

            snapshot = load_question_test_snapshot(path)

        self.assertEqual(snapshot, expected)

    def test_run_question_test_prints_answer_json(self):
        agent = _FakeConversationAgent(
            RaceEngineerAnswer(
                ok=True,
                question="",
                answer="Fuel is critical.",
                source="fake",
                focus="fuel",
                metrics={"advice_count": 1},
            )
        )

        with patch("builtins.print") as print_mock:
            answer = asyncio.run(run_question_test(agent, _SilentLogger(), "как топливо?"))

        self.assertTrue(answer.ok)
        printed = print_mock.call_args_list[0].args[0]
        payload = json.loads(printed)
        self.assertEqual(payload["answer"], "Fuel is critical.")
        self.assertEqual(payload["focus"], "fuel")
        self.assertEqual(agent.calls[0]["question"], "как топливо?")
        self.assertEqual(agent.calls[0]["telemetry_update"]["session-uid"], 9001)

    def test_main_question_test_returns_before_voice_and_config_setup(self):
        args = types.SimpleNamespace(
            profile_check=False,
            question_test="как топливо?",
            question_snapshot="",
            wd=None,
            debug=False,
            managed=False,
            log_file="unused.log",
            agent_prompts_file="",
            conversation_provider="local_brief",
            conversation_endpoint="",
            conversation_key_env_var="",
            conversation_command="",
            conversation_timeout_seconds=2.0,
        )

        with patch("apps.race_engineer.race_engineer.build_voice_engine") as build_voice:
            with patch("builtins.print"):
                asyncio.run(main(args))

        build_voice.assert_not_called()

    def test_run_write_agent_prompts_template_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race-engineer-prompts.json")
            with patch("builtins.print") as print_mock:
                saved = run_write_agent_prompts_template(types.SimpleNamespace(
                    write_agent_prompts_template=path,
                    overwrite_agent_prompts_template=False,
                ))
            with open(saved, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)

        self.assertIn("prompts", payload)
        self.assertIn("fuel", payload["prompts"])
        self.assertIn(path, print_mock.call_args_list[0].args[0])

    def test_main_write_prompt_template_returns_before_voice_and_config_setup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "race-engineer-prompts.json")
            args = types.SimpleNamespace(
                profile_check=False,
                write_agent_prompts_template=path,
                overwrite_agent_prompts_template=False,
                wd=None,
            )

            with patch("apps.race_engineer.race_engineer.build_voice_engine") as build_voice:
                with patch("builtins.print"):
                    asyncio.run(main(args))

        build_voice.assert_not_called()


class TestRaceEngineerAppRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_stats_report_runtime_status_for_common_states(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        self.assertEqual(app.get_stats()["assistant-status"], "waiting-for-telemetry")
        self.assertIn("Waiting", app.get_stats()["assistant-status-detail"])

        app.queue_system_announcement("Radio check.", "race-engineer-radio-check")
        self.assertEqual(app.get_stats()["assistant-status"], "voice-queued")

        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.text, "Radio check.")

        await app.handle_push_to_talk_control({"command": "start"})
        self.assertEqual(app.get_stats()["assistant-status"], "listening")
        await app.handle_push_to_talk_control({"command": "cancel"})

        ok = await app.handle_audio_question(b"RIFFaudio")
        self.assertFalse(ok)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-speech-not-configured")
        self.assertEqual(app.get_stats()["assistant-status"], "speech-error")

        app.set_enabled(False, announce=False)
        self.assertEqual(app.get_stats()["assistant-status"], "muted")

    async def test_race_table_update_queues_focused_voice_announcement(self):
        with _fake_ipc_module() as fake_ipc:
            app = RaceEngineerApp(
                logger=logging.getLogger("tests_race_engineer_app"),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="tyres",
            )

        self.assertEqual(fake_ipc.created_subscribers[0].port, 4242)
        snapshot = _snapshot()
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["rear-right-wear"] = 82.4

        await app.subscriber.routes["race-table-update"](snapshot)

        stats = app.get_stats()
        self.assertTrue(stats["has-snapshot"])
        self.assertEqual(stats["voice-queue-size"], 1)
        announcement = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(announcement.category, "tyres")
        self.assertIn("Tyre", announcement.text)

    async def test_control_route_mutes_engineer_and_suppresses_auto_callouts(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        app._queue_announcement(_announcement("pending", "warning"))
        self.assertEqual(app.voice_queue.qsize(), 1)

        await app.subscriber.routes["race-engineer-control"]({"command": "disable", "source": "udp-action"})

        stats = app.get_stats()
        self.assertFalse(stats["enabled"])
        self.assertEqual(stats["control-events-count"], 1)
        self.assertEqual(stats["dropped-announcements-count"], 1)
        self.assertEqual(stats["voice-queue-size"], 1)
        muted = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(muted.advice_id, "race-engineer-muted")
        self.assertEqual(muted.text, "Race engineer muted.")

        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        await app.subscriber.routes["race-table-update"](snapshot)

        stats = app.get_stats()
        self.assertTrue(stats["has-snapshot"])
        self.assertEqual(stats["voice-queue-size"], 0)

    async def test_control_route_enables_engineer_from_boolean_payload(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="fuel",
                initial_enabled=False,
            )

        await app.subscriber.routes["race-engineer-control"]({"enabled": True, "source": "settings"})

        stats = app.get_stats()
        self.assertTrue(stats["enabled"])
        self.assertEqual(stats["control-events-count"], 1)
        online = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(online.advice_id, "race-engineer-online")
        self.assertEqual(online.text, "Race engineer online.")

        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        await app.subscriber.routes["race-table-update"](snapshot)

        self.assertEqual(app.get_stats()["voice-queue-size"], 1)

    async def test_question_route_answers_from_latest_snapshot_and_queues_voice(self):
        conversation_agent = _FakeConversationAgent(
            RaceEngineerAnswer(
                ok=True,
                question="",
                answer="Gap ahead is 1.2s.",
                source="fake",
                focus="pace",
                metrics={"advice_count": 1},
            )
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                conversation_agent=conversation_agent,
            )

        snapshot = _snapshot()
        await app.subscriber.routes["race-table-update"](snapshot)
        await app.subscriber.routes["race-engineer-question"]({"question": "what is my gap?", "source": "test"})

        self.assertEqual(conversation_agent.calls[0]["question"], "what is my gap?")
        self.assertIs(conversation_agent.calls[0]["telemetry_update"], snapshot)
        stats = app.get_stats()
        self.assertEqual(stats["questions-answered-count"], 1)
        self.assertEqual(stats["question-failures-count"], 0)
        self.assertEqual(stats["last-question-result"]["answer"], "Gap ahead is 1.2s.")
        self.assertEqual(stats["last-question-result"]["focus"], "pace")
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-question-answer")
        self.assertEqual(queued.text, "Gap ahead is 1.2s.")
        self.assertEqual(queued.metrics["advice_count"], 1)

    async def test_question_route_reports_muted_state_without_calling_agent(self):
        conversation_agent = _FakeConversationAgent(
            RaceEngineerAnswer(ok=True, question="", answer="should not be used", source="fake"),
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                initial_enabled=False,
                conversation_agent=conversation_agent,
            )

        result = await app.ask_text_question("what is my gap?", source="test")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "race engineer muted")
        self.assertEqual(conversation_agent.calls, [])
        stats = app.get_stats()
        self.assertEqual(stats["questions-answered-count"], 0)
        self.assertEqual(stats["question-failures-count"], 1)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-muted-question")
        self.assertEqual(queued.text, "Race engineer muted.")

    async def test_audio_question_route_transcribes_then_answers(self):
        speech_recognizer = _FakeSpeechRecognizer(
            SpeechRecognitionResult(ok=True, provider="fake", text="what is my fuel?")
        )
        conversation_agent = _FakeConversationAgent(
            RaceEngineerAnswer(
                ok=True,
                question="",
                answer="Fuel is safe.",
                source="fake",
                focus="fuel",
            )
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                speech_recognizer=speech_recognizer,
                conversation_agent=conversation_agent,
            )

        await app.subscriber.raw_routes["race-engineer-audio-question"](b"RIFFaudio")

        self.assertEqual(speech_recognizer.calls[0]["audio"], b"RIFFaudio")
        self.assertEqual(conversation_agent.calls[0]["question"], "what is my fuel?")
        stats = app.get_stats()
        self.assertEqual(stats["speech-questions-count"], 1)
        self.assertEqual(stats["speech-recognition-failures-count"], 0)
        self.assertEqual(stats["questions-answered-count"], 1)
        self.assertEqual(stats["last-speech-recognition-result"]["text"], "what is my fuel?")
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-question-answer")
        self.assertEqual(queued.text, "Fuel is safe.")

    async def test_audio_question_without_recognizer_reports_not_configured(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        ok = await app.handle_audio_question(b"RIFFaudio")

        self.assertFalse(ok)
        stats = app.get_stats()
        self.assertEqual(stats["speech-questions-count"], 1)
        self.assertEqual(stats["speech-recognition-failures-count"], 1)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-speech-not-configured")
        self.assertEqual(queued.text, "Speech recognition is not configured.")

    async def test_audio_question_while_muted_skips_speech_recognition(self):
        speech_recognizer = _FakeSpeechRecognizer(
            SpeechRecognitionResult(ok=True, provider="fake", text="what is fuel?")
        )
        conversation_agent = _FakeConversationAgent(
            RaceEngineerAnswer(ok=True, question="", answer="should not be used", source="fake"),
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                initial_enabled=False,
                speech_recognizer=speech_recognizer,
                conversation_agent=conversation_agent,
            )

        ok = await app.handle_audio_question(b"RIFFaudio")

        self.assertFalse(ok)
        self.assertEqual(speech_recognizer.calls, [])
        self.assertEqual(conversation_agent.calls, [])
        stats = app.get_stats()
        self.assertEqual(stats["speech-questions-count"], 1)
        self.assertEqual(stats["speech-recognition-failures-count"], 0)
        self.assertEqual(stats["question-failures-count"], 1)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-muted-question")
        self.assertEqual(queued.text, "Race engineer muted.")

    async def test_audio_question_recognition_failure_speaks_short_failure(self):
        speech_recognizer = _FakeSpeechRecognizer(
            SpeechRecognitionResult(ok=False, provider="fake", error="no match", status="NoMatch")
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                speech_recognizer=speech_recognizer,
            )

        ok = await app.handle_audio_question(b"RIFFaudio")

        self.assertFalse(ok)
        stats = app.get_stats()
        self.assertEqual(stats["speech-recognition-failures-count"], 1)
        self.assertEqual(stats["last-speech-recognition-result"]["error"], "no match")
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-speech-not-recognized")
        self.assertEqual(queued.text, "I did not catch that.")

    async def test_push_to_talk_routes_buffer_audio_until_stop(self):
        speech_recognizer = _FakeSpeechRecognizer(
            SpeechRecognitionResult(ok=True, provider="fake", text="what is my fuel?")
        )
        conversation_agent = _FakeConversationAgent(
            RaceEngineerAnswer(
                ok=True,
                question="",
                answer="Fuel is plus four tenths.",
                source="fake",
                focus="fuel",
            )
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                speech_recognizer=speech_recognizer,
                conversation_agent=conversation_agent,
            )

        await app.subscriber.routes["race-engineer-ptt-control"]({
            "command": "start",
            "audio_format": "pcm16",
            "sample_rate_hz": 16000,
        })
        await app.subscriber.raw_routes["race-engineer-ptt-audio"](b"\x00\x00" * 20)
        await app.subscriber.raw_routes["race-engineer-ptt-audio"](b"\x01\x00" * 20)
        await app.subscriber.routes["race-engineer-ptt-control"]({"command": "stop"})

        stats = app.get_stats()
        self.assertEqual(stats["push-to-talk-sessions-count"], 1)
        self.assertEqual(stats["push-to-talk-failures-count"], 0)
        self.assertFalse(stats["push-to-talk-active"])
        self.assertEqual(stats["push-to-talk-buffer-bytes"], 0)
        self.assertEqual(stats["speech-questions-count"], 1)
        self.assertTrue(speech_recognizer.calls[0]["audio"].startswith(b"RIFF"))
        self.assertEqual(
            speech_recognizer.calls[0]["content_type"],
            "audio/wav; codecs=audio/pcm; samplerate=16000",
        )
        self.assertEqual(conversation_agent.calls[0]["question"], "what is my fuel?")
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-question-answer")
        self.assertEqual(queued.text, "Fuel is plus four tenths.")

    async def test_push_to_talk_with_microphone_capture_records_until_stop(self):
        speech_recognizer = _FakeSpeechRecognizer(
            SpeechRecognitionResult(ok=True, provider="fake", text="how is pace?")
        )
        conversation_agent = _FakeConversationAgent(
            RaceEngineerAnswer(
                ok=True,
                question="",
                answer="Pace is stable.",
                source="fake",
                focus="pace",
            )
        )
        microphone_capture = _FakeMicrophoneCapture(chunks=[b"\x00\x00" * 20, b"\x01\x00" * 20])
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                speech_recognizer=speech_recognizer,
                conversation_agent=conversation_agent,
                microphone_capture=microphone_capture,
            )

        await app.subscriber.routes["race-engineer-ptt-control"]({
            "command": "start",
            "sample_rate_hz": 16000,
            "chunk_ms": 20,
        })
        self.assertTrue(app.get_stats()["push-to-talk-microphone-active"])
        await app.subscriber.routes["race-engineer-ptt-control"]({"command": "stop"})

        stats = app.get_stats()
        self.assertEqual(stats["push-to-talk-audio-source"], "fake_microphone")
        self.assertFalse(stats["push-to-talk-microphone-active"])
        self.assertEqual(stats["push-to-talk-sessions-count"], 1)
        self.assertEqual(stats["push-to-talk-failures-count"], 0)
        self.assertEqual(microphone_capture.starts, 1)
        self.assertEqual(microphone_capture.stops, 1)
        self.assertIsInstance(microphone_capture.config, MicrophoneCaptureConfig)
        self.assertEqual(microphone_capture.config.chunk_ms, 20)
        self.assertTrue(speech_recognizer.calls[0]["audio"].startswith(b"RIFF"))
        self.assertEqual(conversation_agent.calls[0]["question"], "how is pace?")
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-question-answer")
        self.assertEqual(queued.text, "Pace is stable.")

    async def test_push_to_talk_microphone_start_failure_speaks_status(self):
        microphone_capture = _FakeMicrophoneCapture(start_error=RuntimeError("device busy"))
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                microphone_capture=microphone_capture,
            )

        ok = await app.handle_push_to_talk_control({"command": "start"})

        self.assertFalse(ok)
        stats = app.get_stats()
        self.assertEqual(stats["push-to-talk-sessions-count"], 0)
        self.assertEqual(stats["push-to-talk-failures-count"], 1)
        self.assertFalse(stats["push-to-talk-active"])
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-microphone-unavailable")
        self.assertEqual(queued.text, "Microphone unavailable.")

    async def test_push_to_talk_start_while_muted_does_not_start_recording(self):
        microphone_capture = _FakeMicrophoneCapture(chunks=[b"\x00\x00" * 20])
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                initial_enabled=False,
                microphone_capture=microphone_capture,
            )

        ok = await app.handle_push_to_talk_control({"command": "start"})

        self.assertFalse(ok)
        stats = app.get_stats()
        self.assertFalse(stats["push-to-talk-active"])
        self.assertEqual(stats["push-to-talk-buffer-bytes"], 0)
        self.assertEqual(stats["question-failures-count"], 1)
        self.assertEqual(microphone_capture.starts, 0)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-muted-question")
        self.assertEqual(queued.text, "Race engineer muted.")

    async def test_push_to_talk_stop_without_audio_speaks_empty_recording_status(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        await app.subscriber.routes["race-engineer-ptt-control"]({"command": "start"})
        ok = await app.subscriber.routes["race-engineer-ptt-control"]({"command": "stop"})

        self.assertIsNone(ok)
        stats = app.get_stats()
        self.assertEqual(stats["push-to-talk-failures-count"], 1)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "race-engineer-ptt-empty")
        self.assertEqual(queued.text, "I did not hear anything.")

    async def test_push_to_talk_cancel_drops_buffer_without_answering(self):
        speech_recognizer = _FakeSpeechRecognizer(
            SpeechRecognitionResult(ok=True, provider="fake", text="unused")
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                speech_recognizer=speech_recognizer,
            )

        await app.subscriber.routes["race-engineer-ptt-control"]({"command": "start"})
        await app.subscriber.raw_routes["race-engineer-ptt-audio"](b"\x00\x00" * 20)
        await app.subscriber.routes["race-engineer-ptt-control"]({"command": "cancel"})

        self.assertFalse(app.get_stats()["push-to-talk-active"])
        self.assertEqual(app.get_stats()["push-to-talk-buffer-bytes"], 0)
        self.assertEqual(speech_recognizer.calls, [])
        self.assertEqual(app.voice_queue.qsize(), 0)

    async def test_backend_trace_update_queues_driving_coach_and_disables_stream_fallback(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=logging.getLogger("tests_race_engineer_app"),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="advisory",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="driving_coach",
            )

        for sample in _trace_lap_samples(lap=1, speed=220, throttle=80, brake=0):
            await app.subscriber.routes["race-engineer-trace-update"](sample)
        await app.subscriber.routes["race-engineer-trace-update"](_trace_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _trace_lap_samples(lap=2, speed=219, throttle=75, brake=0, timestamp_offset=20.0):
            if sample["lap-distance-m"] in {300, 310}:
                sample["throttle-pct"] = 55
                sample["brake-pct"] = 55
                sample["speed-kmph"] = 190
            await app.subscriber.routes["race-engineer-trace-update"](sample)
        await app.subscriber.routes["race-engineer-trace-update"](_trace_sample(lap=3, distance=0, timestamp=40.0))

        self.assertTrue(app._using_backend_trace)
        app.trace_recorder.update_from_stream_overlay = lambda _msg: self.fail("stream fallback should be disabled")
        await app.subscriber.routes["stream-overlay-update"]({})
        self.assertIsInstance(app.get_stats()["trace-reference-laps"], int)
        self.assertGreaterEqual(app.get_stats()["trace-reference-laps"], 1)
        self.assertGreater(app.get_stats()["voice-queue-size"], 0)
        announcements = []
        for _index in range(app.get_stats()["voice-queue-size"]):
            announcements.append(await app.voice_queue.get())
            app.voice_queue.task_done()
        self.assertTrue(all(item.category == "driving_coach" for item in announcements))
        advice_ids = {item.advice_id for item in announcements}
        self.assertIn("driving-coach-brake-throttle-overlap", advice_ids)

    async def test_speak_announcement_passes_engineer_metadata_to_voice_engine(self):
        voice_engine = _RecordingVoiceEngine()
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=logging.getLogger("tests_race_engineer_app"),
                broker_xpub_port=4242,
                voice_engine=voice_engine,
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        await app.subscriber.routes["race-table-update"](snapshot)
        announcement = await app.voice_queue.get()
        app.voice_queue.task_done()

        await app._speak_announcement(announcement)

        self.assertEqual(app.get_stats()["announcements-count"], 1)
        self.assertEqual(app.get_stats()["voice-failures-count"], 0)
        self.assertEqual(app.get_stats()["last-voice-result"]["advice-id"], "fuel-critical-deficit")
        self.assertEqual(app.get_stats()["last-voice-result"]["duration-ms"], 12.5)
        self.assertEqual(app.get_stats()["last-voice-result"]["audio-bytes"], 42)
        self.assertEqual(voice_engine.calls[0]["metadata"]["category"], "fuel")
        self.assertEqual(voice_engine.calls[0]["metadata"]["advice_id"], "fuel-critical-deficit")

    async def test_session_change_clears_pending_voice_and_cooldown_state(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=120,
                max_items=5,
                max_queue_size=3,
                focus="fuel",
            )

        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        await app.subscriber.routes["race-table-update"](snapshot)
        self.assertEqual(app.voice_queue.qsize(), 1)

        next_snapshot = _snapshot()
        next_snapshot["session-uid"] = 67890
        next_snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        await app.subscriber.routes["race-table-update"](next_snapshot)

        stats = app.get_stats()
        self.assertEqual(stats["session-uid"], "67890")
        self.assertEqual(stats["voice-queue-size"], 1)
        self.assertEqual(stats["dropped-announcements-count"], 1)
        announcement = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(announcement.advice_id, "fuel-critical-deficit")

    async def test_session_change_cancels_active_voice_callout(self):
        voice_engine = _BlockingVoiceEngine()
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=voice_engine,
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        app._reset_for_new_session_if_needed("old-session")
        app._queue_announcement(_announcement("old", "warning"))
        app._voice_task = asyncio.create_task(app._voice_worker())
        await asyncio.wait_for(voice_engine.started.wait(), timeout=1.0)

        app._reset_for_new_session_if_needed("new-session")
        await asyncio.wait_for(voice_engine.cancelled.wait(), timeout=1.0)
        await _wait_until(lambda: app.get_stats()["aborted-announcements-count"] == 1)

        stats = app.get_stats()
        self.assertEqual(stats["announcements-count"], 0)
        self.assertEqual(stats["aborted-announcements-count"], 1)
        self.assertEqual(stats["last-voice-result"]["advice-id"], "old")
        self.assertEqual(stats["last-voice-result"]["error"], "session changed during playback")

        app.close()
        await app._stop_voice_worker()

    async def test_session_change_reenables_stream_overlay_fallback(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="advisory",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="driving_coach",
            )

        await app.subscriber.routes["race-engineer-trace-update"](_trace_sample(lap=1, distance=0, timestamp=1.0))
        self.assertTrue(app._using_backend_trace)

        stream_sample = _stream_sample(lap=1, distance=0, timestamp=1.0, session_uid="new-session")
        await app.subscriber.routes["stream-overlay-update"](stream_sample)

        self.assertFalse(app._using_backend_trace)
        self.assertEqual(app.get_stats()["session-uid"], "new-session")

    async def test_invalid_backend_trace_does_not_disable_stream_overlay_fallback(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="advisory",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="driving_coach",
            )

        calls = []
        app.trace_recorder.update_from_stream_overlay = lambda msg: calls.append(msg) or []

        await app.subscriber.routes["race-engineer-trace-update"]({
            "ok": False,
            "session-uid": "abc",
        })
        await app.subscriber.routes["stream-overlay-update"](
            _stream_sample(lap=1, distance=0, timestamp=1.0, session_uid="abc"),
        )

        self.assertFalse(app._using_backend_trace)
        self.assertEqual(len(calls), 1)

    async def test_critical_callout_preempts_lower_priority_pending_voice_items(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="advisory",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        app._queue_announcement(_announcement("warn", "warning"))
        app._queue_announcement(_announcement("advice", "advisory"))
        self.assertEqual(app.voice_queue.qsize(), 2)

        app._queue_announcement(_announcement("critical", "critical"))

        self.assertEqual(app.get_stats()["dropped-announcements-count"], 2)
        self.assertEqual(app.voice_queue.qsize(), 1)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "critical")
        self.assertEqual(queued.priority, "critical")

    async def test_global_voice_interval_drops_non_critical_chatter(self):
        clock = _FakeClock(100.0)
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="advisory",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                min_voice_interval_seconds=5.0,
                monotonic_clock=clock.now,
            )

        app._queue_announcement(_announcement("first", "warning"))
        clock.value = 101.0
        app._queue_announcement(_announcement("second", "warning"))
        clock.value = 106.0
        app._queue_announcement(_announcement("third", "warning"))

        stats = app.get_stats()
        self.assertEqual(stats["voice-queue-size"], 2)
        self.assertEqual(stats["dropped-announcements-count"], 1)
        self.assertEqual(stats["rate-limited-announcements-count"], 1)
        self.assertEqual(stats["min-voice-interval-seconds"], 5.0)

        first = await app.voice_queue.get()
        app.voice_queue.task_done()
        third = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual([first.advice_id, third.advice_id], ["first", "third"])

    async def test_critical_callout_bypasses_global_voice_interval(self):
        clock = _FakeClock(100.0)
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=NullVoiceEngine(),
                min_priority="advisory",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
                min_voice_interval_seconds=30.0,
                monotonic_clock=clock.now,
            )

        app._queue_announcement(_announcement("first", "warning"))
        clock.value = 101.0
        app._queue_announcement(_announcement("urgent", "critical"))

        stats = app.get_stats()
        self.assertEqual(stats["voice-queue-size"], 1)
        self.assertEqual(stats["rate-limited-announcements-count"], 0)
        self.assertEqual(stats["dropped-announcements-count"], 1)
        queued = await app.voice_queue.get()
        app.voice_queue.task_done()
        self.assertEqual(queued.advice_id, "urgent")
        self.assertEqual(queued.priority, "critical")

    async def test_failed_voice_result_is_reported_in_stats(self):
        voice_engine = _RecordingVoiceEngine(
            VoiceResult(
                ok=False,
                provider="recording",
                text="",
                error="speaker failed",
                duration_ms=7.0,
            ),
        )
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=voice_engine,
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        await app.subscriber.routes["race-table-update"](snapshot)
        announcement = await app.voice_queue.get()
        app.voice_queue.task_done()

        await app._speak_announcement(announcement)

        stats = app.get_stats()
        self.assertEqual(stats["announcements-count"], 0)
        self.assertEqual(stats["voice-failures-count"], 1)
        self.assertFalse(stats["last-voice-result"]["ok"])
        self.assertEqual(stats["last-voice-result"]["error"], "speaker failed")
        self.assertEqual(stats["last-voice-result"]["duration-ms"], 7.0)

    async def test_voice_engine_exception_is_reported_in_stats(self):
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=_SilentLogger(),
                broker_xpub_port=4242,
                voice_engine=_ExplodingVoiceEngine(),
                min_priority="warning",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="all",
            )

        await app._speak_announcement(_announcement("boom", "warning"))

        stats = app.get_stats()
        self.assertEqual(stats["announcements-count"], 0)
        self.assertEqual(stats["voice-failures-count"], 1)
        self.assertFalse(stats["last-voice-result"]["ok"])
        self.assertEqual(stats["last-voice-result"]["provider"], "exploding")
        self.assertEqual(stats["last-voice-result"]["error"], "voice exploded")

    async def test_voice_test_mode_speaks_without_loading_config(self):
        voice_engine = _RecordingVoiceEngine()
        args = types.SimpleNamespace(
            wd=None,
            managed=True,
            debug=False,
            log_file="unused.log",
            voice_test="Engineer online.",
        )

        with patch("apps.race_engineer.race_engineer.build_voice_engine", return_value=voice_engine):
            with patch("apps.race_engineer.race_engineer.get_logger", return_value=logging.getLogger("test_voice")):
                await main(args)

        self.assertEqual(len(voice_engine.calls), 1)
        self.assertEqual(voice_engine.calls[0]["text"], "Engineer online.")
        self.assertEqual(voice_engine.calls[0]["metadata"]["advice_id"], "voice-test")

    async def test_backend_trace_driving_coach_callout_reaches_voice_engine(self):
        voice_engine = _RecordingVoiceEngine()
        with _fake_ipc_module():
            app = RaceEngineerApp(
                logger=logging.getLogger("tests_race_engineer_app"),
                broker_xpub_port=4242,
                voice_engine=voice_engine,
                min_priority="advisory",
                cooldown_seconds=20,
                max_items=5,
                max_queue_size=3,
                focus="driving_coach",
            )

        for sample in _trace_lap_samples(lap=1, speed=220, throttle=80, brake=0):
            await app.subscriber.routes["race-engineer-trace-update"](sample)
        await app.subscriber.routes["race-engineer-trace-update"](_trace_sample(lap=2, distance=0, timestamp=20.0))

        for sample in _trace_lap_samples(lap=2, speed=219, throttle=75, brake=0, timestamp_offset=20.0):
            if sample["lap-distance-m"] in {300, 310}:
                sample["throttle-pct"] = 55
                sample["brake-pct"] = 55
                sample["speed-kmph"] = 190
            await app.subscriber.routes["race-engineer-trace-update"](sample)
        await app.subscriber.routes["race-engineer-trace-update"](_trace_sample(lap=3, distance=0, timestamp=40.0))

        self.assertGreater(app.voice_queue.qsize(), 0)
        announcement = await app.voice_queue.get()
        app.voice_queue.task_done()
        await app._speak_announcement(announcement)

        self.assertEqual(app.get_stats()["announcements-count"], 1)
        self.assertEqual(voice_engine.calls[0]["metadata"]["category"], "driving_coach")
        self.assertTrue(voice_engine.calls[0]["metadata"]["advice_id"].startswith("driving-coach-"))
        self.assertIn("sector", voice_engine.calls[0]["text"].lower())


class _FakeSubscriber:
    def __init__(self, *, port, logger):
        self.port = port
        self.logger = logger
        self.routes = {}
        self.raw_routes = {}
        self.closed = False

    def route(self, topic):
        def _decorator(handler):
            self.routes[topic] = handler
            return handler
        return _decorator

    def route_raw(self, topic, content_type=None):
        del content_type
        def _decorator(handler):
            self.raw_routes[topic] = handler
            return handler
        return _decorator

    async def run(self):
        return None

    def close(self):
        self.closed = True

    def get_stats(self):
        return {"port": self.port, "routes": sorted(self.routes), "raw_routes": sorted(self.raw_routes)}


class _SilentLogger:
    def debug(self, *_args, **_kwargs):
        return None

    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


class _FakeClock:
    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value


class _FakeIpcModule(types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.created_subscribers = []

        def _build_subscriber(*, port, logger):
            subscriber = _FakeSubscriber(port=port, logger=logger)
            self.created_subscribers.append(subscriber)
            return subscriber

        self.IpcSubscriberAsync = _build_subscriber


class _RecordingVoiceEngine:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    async def speak(self, text, *, metadata=None):
        self.calls.append({"text": text, "metadata": metadata or {}})
        if self.result:
            return VoiceResult(
                ok=self.result.ok,
                provider=self.result.provider,
                text=text,
                error=self.result.error,
                duration_ms=self.result.duration_ms,
                audio_bytes=self.result.audio_bytes,
            )
        return VoiceResult(ok=True, provider="recording", text=text, duration_ms=12.5, audio_bytes=42)


class _BlockingVoiceEngine:
    provider = "blocking"

    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def speak(self, text, *, metadata=None):
        self.calls.append({"text": text, "metadata": metadata or {}})
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _ExplodingVoiceEngine:
    provider = "exploding"

    async def speak(self, text, *, metadata=None):
        del text, metadata
        raise RuntimeError("voice exploded")


class _FakeConversationAgent:
    def __init__(self, answer):
        self.answer_result = answer
        self.calls = []

    async def answer(self, question, *, telemetry_update=None):
        self.calls.append({"question": question, "telemetry_update": telemetry_update})
        return RaceEngineerAnswer(
            ok=self.answer_result.ok,
            question=question,
            answer=self.answer_result.answer,
            source=self.answer_result.source,
            focus=self.answer_result.focus,
            error=self.answer_result.error,
            metrics=self.answer_result.metrics,
        )


class _FakeSpeechRecognizer:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def transcribe(self, audio, *, content_type=None):
        self.calls.append({"audio": audio, "content_type": content_type})
        return self.result


class _FakeMicrophoneCapture:
    provider = "fake_microphone"

    def __init__(self, *, chunks=None, start_error=None, stop_error=None):
        self.chunks = chunks or []
        self.start_error = start_error
        self.stop_error = stop_error
        self.starts = 0
        self.stops = 0
        self.config = None
        self._active = False

    @property
    def active(self):
        return self._active

    def start(self, on_audio, *, config):
        self.starts += 1
        self.config = config
        if self.start_error:
            raise self.start_error
        self._active = True
        for chunk in self.chunks:
            on_audio(chunk)

    def stop(self):
        self.stops += 1
        if self.stop_error:
            raise self.stop_error
        self._active = False


@contextmanager
def _fake_ipc_module():
    fake_ipc = _FakeIpcModule()
    with patch.dict(sys.modules, {"lib.ipc": fake_ipc}):
        yield fake_ipc


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
        },
        "delta-info": {
            "delta-to-car-in-front": delta_to_front,
            "delta-to-race-leader": position * 1000,
        },
        "lap-info": {
            "last-lap": {"lap-time-ms": last_lap_ms},
            "best-lap": {"lap-time-ms": last_lap_ms - 500},
            "lap-delta-to-session-best-ms": 350,
            "lap-delta-to-session-best-status": "slower",
            "num-pit-stops": 0,
            "corner-cutting-warnings": 0,
            "time-penalties-sec": 0,
            "is-current-lap-invalid": False,
        },
        "tyre-info": {
            "actual-tyre-compound": "Medium",
            "visual-tyre-compound": "Medium",
            "tyre-age": 8,
            "current-wear": {
                "front-left-wear": 30.0,
                "front-right-wear": 32.0,
                "rear-left-wear": 35.0,
                "rear-right-wear": 34.0,
            },
        },
        "fuel-info": {
            "surplus-laps-png": 0.4,
            "surplus-laps-game": 0.3,
            "fuel-remaining-laps": 10.2,
        },
        "ers-info": {
            "ers-percent": 42.0,
            "ers-deploy-mode": "Medium",
            "ers-harvested-this-lap-mj": 0.6,
            "ers-deployed-this-lap-mj": 1.0,
        },
        "damage-info": {
            "front-left-wing-damage": 0,
            "front-right-wing-damage": 0,
            "floor-damage": 0,
            "sidepod-damage": 0,
            "diffuser-damage": 0,
        },
    }


def _trace_lap_samples(*, lap, speed, throttle, brake, timestamp_offset=0.0):
    return [
        _trace_sample(
            lap=lap,
            distance=distance,
            timestamp=timestamp_offset + index,
            speed=speed,
            throttle=throttle,
            brake=brake,
        )
        for index, distance in enumerate(range(0, 321, 10))
    ]


def _trace_sample(*, lap, distance, timestamp, speed=210, throttle=80, brake=0):
    return {
        "ok": True,
        "session-uid": "abc",
        "current-lap": lap,
        "timestamp": timestamp,
        "circuit-enum-name": "Spa",
        "current-lap-invalid": False,
        "lap-distance-m": distance,
        "circuit-length-m": 320,
        "sector": "3" if distance >= 300 else "2",
        "speed-kmph": speed,
        "throttle-pct": throttle,
        "brake-pct": brake,
        "steering-pct": -12,
        "gear": 6,
        "drs": 0,
        "segment-label": None,
        "segment-voice-label": None,
    }


def _stream_sample(*, lap, distance, timestamp, session_uid="abc", speed=210, throttle=0.8, brake=0.0):
    return {
        "session-uid": session_uid,
        "current-lap": lap,
        "timestamp": timestamp,
        "circuit-enum-name": "Spa",
        "hud": {
            "throttle": throttle,
            "brake": brake,
            "speed-kmph": speed,
            "circuit-position": distance,
            "circuit-length": 320,
            "sector": "1",
        },
        "car-telemetry": {
            "steering": 0,
            "throttle": throttle * 100,
            "brake": brake * 100,
        },
    }


def _announcement(advice_id, priority):
    return RaceEngineerAnnouncement(
        text=f"{priority} callout",
        priority=priority,
        category="test",
        cooldown_key=f"test:{advice_id}",
        advice_id=advice_id,
        evidence=[],
        metrics={},
    )


async def _wait_until(predicate, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")
