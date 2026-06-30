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
import os
import unittest
from unittest.mock import patch

from lib.race_engineer import (
    CodexCliConversationAgent,
    CodexCliConversationConfig,
    CommandConversationResponse,
    FallbackConversationAgent,
    HttpConversationAgent,
    HttpConversationConfig,
    HttpConversationResponse,
    LocalBriefConversationAgent,
    build_http_conversation_headers,
    build_codex_conversation_prompt_package,
    build_race_engineer_brief,
    infer_question_focus,
    parse_conversation_command,
)
from tests.tests_mcp_race_engineer_brief import _player_tyre_sets, _snapshot


class TestRaceEngineerConversation(unittest.IsolatedAsyncioTestCase):
    def test_infer_question_focus_handles_russian_and_english_terms(self):
        cases = [
            ("какой износ шин?", "tyres"),
            ("какие шины брать на пит?", "strategy"),
            ("what tyre should I fit?", "strategy"),
            ("how is my fuel?", "fuel"),
            ("какая дельта до машины впереди?", "pace"),
            ("дождь скоро?", "weather"),
            ("should I box for undercut?", "strategy"),
            ("как дела?", "all"),
        ]

        for question, expected_focus in cases:
            with self.subTest(question=question):
                self.assertEqual(infer_question_focus(question), expected_focus)

    async def test_empty_question_is_rejected(self):
        agent = LocalBriefConversationAgent()

        answer = await agent.answer("   ", telemetry_update=_snapshot())

        self.assertFalse(answer.ok)
        self.assertEqual(answer.answer, "I did not catch the question.")
        self.assertEqual(answer.error, "empty question")

    async def test_missing_telemetry_is_reported(self):
        agent = LocalBriefConversationAgent()

        answer = await agent.answer("what is my fuel?", telemetry_update=None)

        self.assertFalse(answer.ok)
        self.assertEqual(answer.answer, "I do not have live telemetry yet.")
        self.assertEqual(answer.error, "missing telemetry")

    async def test_fuel_question_returns_focused_fuel_advice(self):
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.65
        agent = LocalBriefConversationAgent()

        answer = await agent.answer("как у меня с топливом?", telemetry_update=snapshot)

        self.assertTrue(answer.ok)
        self.assertEqual(answer.focus, "fuel")
        self.assertIn("Топливо критично", answer.answer)
        self.assertIn("Лифт-энд-коуст", answer.answer)
        self.assertEqual(answer.metrics["advice_count"], 1)
        self.assertEqual(answer.metrics["focus"], "fuel")
        self.assertEqual(answer.metrics["codex_prompt_focus"], "fuel")
        self.assertIn("agent_context", answer.metrics["codex_prompt_context_keys"])
        self.assertIn("prompt_specs", answer.metrics["codex_prompt_context_keys"])
        self.assertEqual(answer.metrics["codex_prompt_advice_ids"], ["fuel-critical-deficit"])

    async def test_tyre_choice_question_returns_strategy_tyre_call(self):
        snapshot = _snapshot()
        snapshot["current-lap"] = 14
        snapshot["total-laps"] = 27
        snapshot["player-pit-window"] = 13
        snapshot["pit-time-loss"] = 23.0
        snapshot["table-entries"][1]["tyre-info"]["current-wear"]["average"] = 55.0
        snapshot["table-entries"][2]["delta-info"]["delta-to-car-in-front"] = 31000
        snapshot["player-tyre-sets"] = _player_tyre_sets()
        agent = LocalBriefConversationAgent()

        answer = await agent.answer("какие шины брать на пит?", telemetry_update=snapshot)

        self.assertTrue(answer.ok)
        self.assertEqual(answer.focus, "strategy")
        self.assertIn("Пит-окно открыто", answer.answer)
        self.assertIn("Ставим Medium", answer.answer)
        self.assertEqual(answer.metrics["codex_prompt_focus"], "strategy")
        self.assertEqual(answer.metrics["codex_prompt_advice_ids"], ["strategy-pit-clear-air"])

    async def test_unknown_question_falls_back_to_current_brief(self):
        agent = LocalBriefConversationAgent()

        answer = await agent.answer("what should I know?", telemetry_update=_snapshot())

        self.assertTrue(answer.ok)
        self.assertEqual(answer.focus, "all")
        self.assertTrue(answer.answer)

    def test_codex_prompt_package_filters_to_question_focus(self):
        snapshot = _snapshot()
        snapshot["weather-forecast-samples"] = [
            {
                "session-type": "Race",
                "time-offset": 0,
                "weather": "Clear",
                "rain-percentage": 0,
                "track-temperature": 34,
                "air-temperature": 24,
            },
            {
                "session-type": "Race",
                "time-offset": 10,
                "weather": "Light rain",
                "rain-percentage": 70,
                "track-temperature": 29,
                "air-temperature": 22,
            },
        ]
        brief = build_race_engineer_brief(
            telemetry_update=snapshot,
            base_rsp={"available": False, "connected": True, "ok": False},
            focus="weather",
            max_items=5,
        )

        package = build_codex_conversation_prompt_package("дождь скоро?", brief=brief)

        self.assertEqual(package.question, "дождь скоро?")
        self.assertEqual(package.focus, "weather")
        self.assertEqual([message["role"] for message in package.messages], ["system", "user"])
        self.assertIn("same language", package.messages[0]["content"])
        self.assertIn("race-radio", package.messages[0]["content"])
        self.assertIn("Compact context JSON:", package.messages[1]["content"])
        self.assertEqual(package.context["answer_contract"]["language"], "ru")
        self.assertEqual(package.context["answer_contract"]["max_sentences"], 2)
        self.assertTrue(package.context["answer_contract"]["same_language_as_question"])
        self.assertEqual(set(package.context["agent_context"]["categories"].keys()), {"weather"})
        self.assertEqual(set(package.context["prompt_specs"].keys()), {"weather"})
        self.assertTrue(package.context["advice"])
        self.assertEqual(package.context["advice"][0]["category"], "weather")

    def test_codex_prompt_package_does_not_include_raw_telemetry_snapshot(self):
        brief = build_race_engineer_brief(
            telemetry_update=_snapshot(),
            base_rsp={"available": False, "connected": True, "ok": False},
            focus="all",
            max_items=5,
        )

        package = build_codex_conversation_prompt_package(
            "what should I know?",
            brief=brief,
            focus="not-a-real-focus",
        )

        self.assertEqual(package.focus, "all")
        serialised = repr(package.as_dict())
        for raw_key in (
                "table-entries",
                "weather-forecast-samples",
                "race-engineer-trace-update",
                "stream-overlay-update",
                "lap-info",
                "tyre-info",
                "fuel-info",
                "ers-info",
                "damage-info"):
            with self.subTest(raw_key=raw_key):
                self.assertNotIn(raw_key, serialised)

    async def test_http_conversation_agent_sends_compact_prompt_package(self):
        client = _FakeHttpConversationClient(
            HttpConversationResponse(
                status_code=200,
                body=json.dumps({
                    "answer": "Fuel is critical. Lift and coast now.",
                    "focus": "fuel",
                    "metrics": {"model": "codex-proxy"},
                }).encode("utf-8"),
            )
        )
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.7
        agent = HttpConversationAgent(
            HttpConversationConfig(
                endpoint="http://127.0.0.1:8765/race-engineer/answer",
                key_env_var="PNG_TEST_CONVERSATION_KEY",
            ),
            client=client,
        )

        with patch.dict(os.environ, {"PNG_TEST_CONVERSATION_KEY": "secret"}):
            answer = await agent.answer("как топливо?", telemetry_update=snapshot)

        self.assertTrue(answer.ok)
        self.assertEqual(answer.source, "external_http")
        self.assertEqual(answer.focus, "fuel")
        self.assertEqual(answer.answer, "Fuel is critical. Lift and coast now.")
        self.assertEqual(answer.metrics["model"], "codex-proxy")
        self.assertEqual(client.calls[0]["url"], "http://127.0.0.1:8765/race-engineer/answer")
        self.assertEqual(client.calls[0]["headers"]["Authorization"], "Bearer secret")
        payload = client.calls[0]["payload"]
        self.assertEqual(payload["focus"], "fuel")
        self.assertEqual(payload["metadata"]["schema"], "pits-n-giggles.race-engineer.conversation.v1")
        self.assertIn("Compact context JSON:", payload["messages"][1]["content"])
        serialised_payload = repr(payload)
        self.assertIn("prompt_specs", serialised_payload)
        self.assertNotIn("table-entries", serialised_payload)
        self.assertNotIn("fuel-info", serialised_payload)

    async def test_http_conversation_agent_accepts_openai_style_choice(self):
        client = _FakeHttpConversationClient(
            HttpConversationResponse(
                status_code=200,
                body=json.dumps({
                    "choices": [
                        {"message": {"content": "Gap ahead is stable. Keep pressure."}}
                    ]
                }).encode("utf-8"),
            )
        )
        agent = HttpConversationAgent(
            HttpConversationConfig(endpoint="http://127.0.0.1:8765/answer"),
            client=client,
        )

        answer = await agent.answer("what is my gap?", telemetry_update=_snapshot())

        self.assertTrue(answer.ok)
        self.assertEqual(answer.answer, "Gap ahead is stable. Keep pressure.")

    async def test_external_answers_are_normalised_to_radio_length(self):
        client = _FakeHttpConversationClient(
            HttpConversationResponse(
                status_code=200,
                body=json.dumps({
                    "answer": (
                        "Fuel is critical. Lift and coast now. "
                        "Also consider changing your differential settings later."
                    ),
                    "focus": "fuel",
                }).encode("utf-8"),
            )
        )
        agent = HttpConversationAgent(
            HttpConversationConfig(endpoint="http://127.0.0.1:8765/answer"),
            client=client,
        )

        answer = await agent.answer("how is fuel?", telemetry_update=_snapshot())

        self.assertTrue(answer.ok)
        self.assertEqual(answer.answer, "Fuel is critical. Lift and coast now.")

    async def test_fallback_conversation_agent_uses_local_answer_after_http_error(self):
        client = _FakeHttpConversationClient(
            HttpConversationResponse(status_code=503, body=b"busy", error_text="busy")
        )
        primary = HttpConversationAgent(
            HttpConversationConfig(endpoint="http://127.0.0.1:8765/answer"),
            client=client,
        )
        fallback = LocalBriefConversationAgent()
        agent = FallbackConversationAgent(primary, fallback)
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.7

        answer = await agent.answer("how is fuel?", telemetry_update=snapshot)

        self.assertTrue(answer.ok)
        self.assertEqual(answer.source, "local_brief_fallback")
        self.assertEqual(answer.metrics["fallback_from"], "external_http")
        self.assertIn("HTTP 503", answer.metrics["fallback_error"])

    async def test_codex_cli_conversation_agent_sends_compact_prompt_json_to_stdin(self):
        runner = _FakeCommandConversationRunner(
            CommandConversationResponse(
                exit_code=0,
                stdout=json.dumps({
                    "answer": "Fuel is critical. Lift and coast.",
                    "focus": "fuel",
                    "metrics": {"model": "codex-cli"},
                }).encode("utf-8"),
            )
        )
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.7
        agent = CodexCliConversationAgent(
            CodexCliConversationConfig(
                command='codex exec --json',
                timeout_seconds=6.0,
            ),
            runner=runner,
        )

        answer = await agent.answer("как топливо?", telemetry_update=snapshot)

        self.assertTrue(answer.ok)
        self.assertEqual(answer.source, "codex_cli")
        self.assertEqual(answer.focus, "fuel")
        self.assertEqual(answer.answer, "Fuel is critical. Lift and coast.")
        self.assertEqual(answer.metrics["model"], "codex-cli")
        self.assertEqual(runner.calls[0]["argv"], ["codex", "exec", "--json"])
        self.assertEqual(runner.calls[0]["timeout_seconds"], 6.0)
        payload = json.loads(runner.calls[0]["stdin"].decode("utf-8"))
        self.assertEqual(payload["focus"], "fuel")
        self.assertEqual(payload["metadata"]["provider"], "codex_cli")
        self.assertEqual(payload["metadata"]["stdin_contract"], "json")
        serialised_payload = repr(payload)
        self.assertIn("prompt_specs", serialised_payload)
        self.assertNotIn("table-entries", serialised_payload)
        self.assertNotIn("fuel-info", serialised_payload)

    async def test_codex_cli_conversation_agent_accepts_plain_text_stdout(self):
        runner = _FakeCommandConversationRunner(
            CommandConversationResponse(exit_code=0, stdout=b"Gap ahead is stable.")
        )
        agent = CodexCliConversationAgent(
            CodexCliConversationConfig(command="codex-wrapper"),
            runner=runner,
        )

        answer = await agent.answer("what is my gap?", telemetry_update=_snapshot())

        self.assertTrue(answer.ok)
        self.assertEqual(answer.answer, "Gap ahead is stable.")
        self.assertEqual(answer.focus, "pace")

    async def test_codex_cli_json_without_answer_is_rejected_for_fallback(self):
        runner = _FakeCommandConversationRunner(
            CommandConversationResponse(exit_code=0, stdout=json.dumps({"metrics": {"model": "codex"}}).encode("utf-8"))
        )
        agent = CodexCliConversationAgent(
            CodexCliConversationConfig(command="codex-wrapper"),
            runner=runner,
        )

        answer = await agent.answer("what is my gap?", telemetry_update=_snapshot())

        self.assertFalse(answer.ok)
        self.assertEqual(answer.error, "conversation command JSON did not include answer text")

    async def test_codex_cli_conversation_agent_reports_command_failure_for_fallback(self):
        runner = _FakeCommandConversationRunner(
            CommandConversationResponse(exit_code=2, stderr=b"not logged in")
        )
        primary = CodexCliConversationAgent(
            CodexCliConversationConfig(command="codex exec"),
            runner=runner,
        )
        fallback = LocalBriefConversationAgent()
        agent = FallbackConversationAgent(primary, fallback)
        snapshot = _snapshot()
        snapshot["table-entries"][1]["fuel-info"]["surplus-laps-png"] = -0.7

        answer = await agent.answer("how is fuel?", telemetry_update=snapshot)

        self.assertTrue(answer.ok)
        self.assertEqual(answer.source, "local_brief_fallback")
        self.assertEqual(answer.metrics["fallback_from"], "codex_cli")
        self.assertIn("not logged in", answer.metrics["fallback_error"])

    def test_parse_conversation_command_splits_without_shell(self):
        self.assertEqual(
            parse_conversation_command('"C:\\Program Files\\Codex\\codex.exe" exec --json'),
            ["C:\\Program Files\\Codex\\codex.exe", "exec", "--json"],
        )

    def test_http_conversation_headers_omit_auth_when_key_is_missing(self):
        config = HttpConversationConfig(
            endpoint="http://127.0.0.1:8765/answer",
            key_env_var="PNG_TEST_CONVERSATION_KEY",
        )

        with patch.dict(os.environ, {}, clear=True):
            headers = build_http_conversation_headers(config)

        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertNotIn("Authorization", headers)


class _FakeHttpConversationClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def answer(self, *, url, headers, payload, timeout_seconds):
        self.calls.append({
            "url": url,
            "headers": headers,
            "payload": payload,
            "timeout_seconds": timeout_seconds,
        })
        return self.response


class _FakeCommandConversationRunner:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def run(self, *, argv, stdin, timeout_seconds):
        self.calls.append({
            "argv": argv,
            "stdin": stdin,
            "timeout_seconds": timeout_seconds,
        })
        return self.response


if __name__ == "__main__":
    unittest.main()
