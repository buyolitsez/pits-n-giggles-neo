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

from io import BytesIO
import os
import unittest
import urllib.error
from unittest.mock import patch

from lib.race_engineer import (
    AzureSpeechConfig,
    AzureSpeechResponse,
    AzureSpeechVoiceEngine,
    build_azure_speech_endpoint_url,
    build_azure_speech_ssml,
)
from lib.race_engineer.azure_voice import _synthesize_with_urllib


class FakeAzureSpeechClient:
    def __init__(self, response=None, responses=None):
        if responses is None:
            responses = [response or AzureSpeechResponse(status_code=200, audio=b"RIFFfake")]
        self.responses = list(responses)
        self.calls = []

    async def synthesize(self, *, url, headers, ssml, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "ssml": ssml,
                "timeout_seconds": timeout_seconds,
            }
        )
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


class RecordingAudioSink:
    def __init__(self):
        self.calls = []

    async def play(self, audio, *, metadata=None):
        self.calls.append(
            {
                "audio": audio,
                "metadata": metadata or {},
            }
        )


class FakeUrlopenResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body

    def getcode(self):
        return self.status_code


class TestRaceEngineerAzureVoice(unittest.IsolatedAsyncioTestCase):
    def test_endpoint_url_from_region(self):
        url = build_azure_speech_endpoint_url(region="francecentral")

        self.assertEqual(url, "https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1")

    def test_endpoint_url_from_cognitive_endpoint_derives_region(self):
        config = AzureSpeechConfig(
            region="",
            endpoint="https://francecentral.api.cognitive.microsoft.com/",
            subscription_key="secret",
        )

        self.assertEqual(
            config.endpoint_url(),
            "https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1",
        )

    async def test_missing_key_fails_before_http_call(self):
        client = FakeAzureSpeechClient()
        sink = RecordingAudioSink()
        config = AzureSpeechConfig(region="eastus", key_env_var="PNG_TEST_AZURE_KEY")

        with patch.dict(os.environ, {}, clear=True):
            engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=sink)
            result = await engine.speak("Box this lap.")

        self.assertFalse(result.ok)
        self.assertEqual(result.provider, "azure")
        self.assertIn("subscription key", result.error)
        self.assertEqual(client.calls, [])
        self.assertEqual(sink.calls, [])

    async def test_success_sends_azure_rest_contract_and_plays_audio(self):
        client = FakeAzureSpeechClient(AzureSpeechResponse(status_code=200, audio=b"RIFFwave"))
        sink = RecordingAudioSink()
        config = AzureSpeechConfig(
            region="westeurope",
            voice="en-US-JennyNeural",
            subscription_key="secret",
            timeout_seconds=7.5,
        )
        engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=sink)

        result = await engine.speak(
            "Car behind is within DRS.",
            metadata={"priority": "warning"},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "azure")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["url"], "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1")
        self.assertEqual(client.calls[0]["headers"]["Ocp-Apim-Subscription-Key"], "secret")
        self.assertEqual(client.calls[0]["headers"]["Content-Type"], "application/ssml+xml")
        self.assertEqual(client.calls[0]["headers"]["X-Microsoft-OutputFormat"], "riff-24khz-16bit-mono-pcm")
        self.assertIn('name="en-US-JennyNeural"', client.calls[0]["ssml"])
        self.assertEqual(client.calls[0]["timeout_seconds"], 7.5)
        self.assertEqual(sink.calls[0]["audio"], b"RIFFwave")
        self.assertEqual(sink.calls[0]["metadata"]["priority"], "warning")
        self.assertEqual(sink.calls[0]["metadata"]["provider"], "azure")
        self.assertEqual(sink.calls[0]["metadata"]["audio_bytes"], len(b"RIFFwave"))
        self.assertIsInstance(sink.calls[0]["metadata"]["synthesis_ms"], float)
        self.assertEqual(sink.calls[0]["metadata"]["synthesis_attempts"], 1)
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual(result.audio_bytes, len(b"RIFFwave"))

    async def test_http_error_is_reported_without_playback(self):
        client = FakeAzureSpeechClient(
            AzureSpeechResponse(status_code=401, audio=b"nope", error_text="bad key"),
        )
        sink = RecordingAudioSink()
        config = AzureSpeechConfig(region="eastus", subscription_key="secret")
        engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=sink)

        result = await engine.speak("Recharge on the straight.")

        self.assertFalse(result.ok)
        self.assertIn("HTTP 401", result.error)
        self.assertIn("bad key", result.error)
        self.assertEqual(result.audio_bytes, len(b"nope"))
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(sink.calls, [])

    async def test_http_400_without_body_reports_actionable_hint(self):
        client = FakeAzureSpeechClient(AzureSpeechResponse(status_code=400))
        sink = RecordingAudioSink()
        config = AzureSpeechConfig(region="eastus", subscription_key="secret")
        engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=sink)

        result = await engine.speak("Recharge on the straight.")

        self.assertFalse(result.ok)
        self.assertIn("HTTP 400", result.error)
        self.assertIn("check Azure voice name", result.error)
        self.assertIn("ru-RU-DmitryNeural", result.error)
        self.assertEqual(sink.calls, [])

    async def test_retryable_http_error_is_retried_before_playback(self):
        client = FakeAzureSpeechClient(responses=[
            AzureSpeechResponse(status_code=429, audio=b"slow down", error_text="rate limit"),
            AzureSpeechResponse(status_code=200, audio=b"RIFFretry"),
        ])
        sink = RecordingAudioSink()
        config = AzureSpeechConfig(
            region="eastus",
            subscription_key="secret",
            retry_attempts=1,
            retry_backoff_seconds=0.0,
        )
        engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=sink)

        result = await engine.speak("Recharge and go again.")

        self.assertTrue(result.ok)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(sink.calls[0]["audio"], b"RIFFretry")
        self.assertEqual(sink.calls[0]["metadata"]["synthesis_attempts"], 2)

    async def test_retryable_http_error_reports_final_failure_after_attempts(self):
        client = FakeAzureSpeechClient(responses=[
            AzureSpeechResponse(status_code=503, audio=b"busy", error_text="service busy"),
            AzureSpeechResponse(status_code=500, audio=b"down", error_text="still down"),
        ])
        sink = RecordingAudioSink()
        config = AzureSpeechConfig(
            region="eastus",
            subscription_key="secret",
            retry_attempts=1,
            retry_backoff_seconds=0.0,
        )
        engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=sink)

        result = await engine.speak("Fuel save.")

        self.assertFalse(result.ok)
        self.assertIn("HTTP 500 after 2 attempt", result.error)
        self.assertIn("still down", result.error)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(sink.calls, [])

    async def test_request_exception_is_retried_before_failure(self):
        client = FakeAzureSpeechClient(responses=[
            TimeoutError("temporary timeout"),
            TimeoutError("still timing out"),
        ])
        config = AzureSpeechConfig(
            region="eastus",
            subscription_key="secret",
            retry_attempts=1,
            retry_backoff_seconds=0.0,
        )
        engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=RecordingAudioSink())

        result = await engine.speak("Hold position.")

        self.assertFalse(result.ok)
        self.assertIn("after 2 attempt", result.error)
        self.assertIn("still timing out", result.error)
        self.assertEqual(len(client.calls), 2)

    async def test_env_key_is_used_when_direct_key_is_absent(self):
        client = FakeAzureSpeechClient()
        sink = RecordingAudioSink()
        config = AzureSpeechConfig(region="eastus", key_env_var="PNG_TEST_AZURE_KEY")

        with patch.dict(os.environ, {"PNG_TEST_AZURE_KEY": "from-env"}):
            engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=sink)
            result = await engine.speak("Push now.")

        self.assertTrue(result.ok)
        self.assertEqual(client.calls[0]["headers"]["Ocp-Apim-Subscription-Key"], "from-env")

    async def test_empty_text_fails_without_http_call(self):
        client = FakeAzureSpeechClient()
        config = AzureSpeechConfig(region="eastus", subscription_key="secret")
        engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=RecordingAudioSink())

        result = await engine.speak("   ")

        self.assertFalse(result.ok)
        self.assertIn("text is empty", result.error)
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual(client.calls, [])

    async def test_invalid_config_values_fail_without_http_call(self):
        cases = [
            (AzureSpeechConfig(region="", subscription_key="secret"), "region or endpoint is missing"),
            (AzureSpeechConfig(region="eastus", voice="", subscription_key="secret"), "voice is missing"),
            (
                AzureSpeechConfig(region="eastus", output_format="", subscription_key="secret"),
                "output format is missing",
            ),
            (
                AzureSpeechConfig(region="eastus", timeout_seconds=0, subscription_key="secret"),
                "timeout must be greater than zero",
            ),
            (
                AzureSpeechConfig(region="eastus", retry_attempts=-1, subscription_key="secret"),
                "retry attempts must be zero or greater",
            ),
            (
                AzureSpeechConfig(region="eastus", retry_backoff_seconds=-0.1, subscription_key="secret"),
                "retry backoff must be zero or greater",
            ),
        ]

        for config, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                client = FakeAzureSpeechClient()
                engine = AzureSpeechVoiceEngine(config, client=client, audio_sink=RecordingAudioSink())

                result = await engine.speak("Push.")

                self.assertFalse(result.ok)
                self.assertIn(expected_error, result.error)
                self.assertEqual(client.calls, [])

    def test_ssml_escapes_user_text(self):
        ssml = build_azure_speech_ssml(
            'Push & save <fuel> "now"',
            voice="en-US-GuyNeural",
            locale="en-US",
        )

        self.assertIn("Push &amp; save &lt;fuel&gt;", ssml)
        self.assertIn('"now"', ssml)
        self.assertIn('xml:lang="en-US"', ssml)

    def test_urllib_transport_posts_ssml_and_returns_audio(self):
        with patch("urllib.request.urlopen", return_value=FakeUrlopenResponse(200, b"RIFFstdlib")) as urlopen:
            response = _synthesize_with_urllib(
                url="https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1",
                headers={"Ocp-Apim-Subscription-Key": "secret"},
                ssml="<speak>Race engineer online.</speak>",
                timeout_seconds=4.5,
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 4.5)
        self.assertEqual(request.full_url, "https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Ocp-apim-subscription-key"), "secret")
        self.assertEqual(request.data, b"<speak>Race engineer online.</speak>")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.audio, b"RIFFstdlib")
        self.assertIsNone(response.error_text)

    def test_urllib_transport_returns_azure_http_error_body(self):
        error = urllib.error.HTTPError(
            "https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b"bad key"),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            response = _synthesize_with_urllib(
                url="https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1",
                headers={"Ocp-Apim-Subscription-Key": "secret"},
                ssml="<speak>Race engineer online.</speak>",
                timeout_seconds=4.5,
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.audio, b"bad key")
        self.assertEqual(response.error_text, "bad key")


if __name__ == "__main__":
    unittest.main()
