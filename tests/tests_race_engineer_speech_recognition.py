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
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from lib.race_engineer import (
    AzureSpeechRecognitionConfig,
    AzureSpeechRecognitionResponse,
    AzureSpeechRecognizer,
    build_azure_stt_endpoint_url,
)
from lib.race_engineer.speech_recognition import _recognize_with_urllib


class FakeAzureSpeechRecognitionClient:
    def __init__(self, response=None, responses=None):
        if responses is None:
            responses = [response or _json_response({"RecognitionStatus": "Success", "DisplayText": "Box now."})]
        self.responses = list(responses)
        self.calls = []

    async def recognize(self, *, url, headers, audio, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "audio": audio,
                "timeout_seconds": timeout_seconds,
            }
        )
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


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


class TestRaceEngineerSpeechRecognition(unittest.IsolatedAsyncioTestCase):
    def test_endpoint_url_from_region(self):
        url = build_azure_stt_endpoint_url(region="francecentral", language="ru-RU")

        self.assertEqual(
            url,
            "https://francecentral.stt.speech.microsoft.com/speech/recognition/conversation/"
            "cognitiveservices/v1?language=ru-RU&format=simple&profanity=masked",
        )

    def test_endpoint_url_from_cognitive_endpoint_derives_region(self):
        config = AzureSpeechRecognitionConfig(
            endpoint="https://francecentral.api.cognitive.microsoft.com/",
            language="en-US",
            result_format="detailed",
            profanity="raw",
        )

        self.assertEqual(
            config.endpoint_url(),
            "https://francecentral.stt.speech.microsoft.com/speech/recognition/conversation/"
            "cognitiveservices/v1?language=en-US&format=detailed&profanity=raw",
        )

    def test_endpoint_url_from_resource_endpoint(self):
        config = AzureSpeechRecognitionConfig(
            endpoint="https://my-speech-resource.cognitiveservices.azure.com",
            language="en-US",
        )

        self.assertEqual(
            config.endpoint_url(),
            "https://my-speech-resource.cognitiveservices.azure.com/speech/recognition/conversation/"
            "cognitiveservices/v1?language=en-US&format=simple&profanity=masked",
        )

    async def test_success_sends_audio_and_returns_display_text(self):
        client = FakeAzureSpeechRecognitionClient(
            _json_response({"RecognitionStatus": "Success", "DisplayText": "What is my gap?"}),
        )
        config = AzureSpeechRecognitionConfig(
            region="francecentral",
            subscription_key="secret",
            language="en-US",
            timeout_seconds=4.5,
        )
        recognizer = AzureSpeechRecognizer(config, client=client)

        result = await recognizer.transcribe(b"RIFFaudio")

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "azure")
        self.assertEqual(result.text, "What is my gap?")
        self.assertEqual(result.status, "Success")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["audio"], b"RIFFaudio")
        self.assertEqual(client.calls[0]["timeout_seconds"], 4.5)
        self.assertEqual(client.calls[0]["headers"]["Ocp-Apim-Subscription-Key"], "secret")
        self.assertEqual(client.calls[0]["headers"]["Accept"], "application/json")
        self.assertEqual(
            client.calls[0]["headers"]["Content-Type"],
            "audio/wav; codecs=audio/pcm; samplerate=16000",
        )
        self.assertIn("language=en-US", client.calls[0]["url"])
        self.assertGreaterEqual(result.duration_ms, 0)

    async def test_success_reads_detailed_nbest_text_and_confidence(self):
        client = FakeAzureSpeechRecognitionClient(_json_response({
            "RecognitionStatus": "Success",
            "NBest": [{"Display": "Tell me tyre wear.", "Confidence": 0.91}],
        }))
        recognizer = AzureSpeechRecognizer(
            AzureSpeechRecognitionConfig(region="francecentral", subscription_key="secret", result_format="detailed"),
            client=client,
        )

        result = await recognizer.transcribe(b"RIFFaudio")

        self.assertTrue(result.ok)
        self.assertEqual(result.text, "Tell me tyre wear.")
        self.assertEqual(result.confidence, 0.91)

    async def test_env_key_is_used_when_direct_key_is_absent(self):
        client = FakeAzureSpeechRecognitionClient()
        config = AzureSpeechRecognitionConfig(region="francecentral", key_env_var="PNG_TEST_AZURE_KEY")

        with patch.dict(os.environ, {"PNG_TEST_AZURE_KEY": "from-env"}):
            recognizer = AzureSpeechRecognizer(config, client=client)
            result = await recognizer.transcribe(b"RIFFaudio")

        self.assertTrue(result.ok)
        self.assertEqual(client.calls[0]["headers"]["Ocp-Apim-Subscription-Key"], "from-env")

    async def test_missing_key_fails_before_http_call(self):
        client = FakeAzureSpeechRecognitionClient()
        config = AzureSpeechRecognitionConfig(region="francecentral", key_env_var="PNG_TEST_AZURE_KEY")

        with patch.dict(os.environ, {}, clear=True):
            recognizer = AzureSpeechRecognizer(config, client=client)
            result = await recognizer.transcribe(b"RIFFaudio")

        self.assertFalse(result.ok)
        self.assertIn("subscription key", result.error)
        self.assertEqual(client.calls, [])

    async def test_no_match_status_is_reported_without_text(self):
        client = FakeAzureSpeechRecognitionClient(_json_response({"RecognitionStatus": "NoMatch"}))
        recognizer = AzureSpeechRecognizer(
            AzureSpeechRecognitionConfig(region="francecentral", subscription_key="secret"),
            client=client,
        )

        result = await recognizer.transcribe(b"RIFFaudio")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "NoMatch")
        self.assertIn("NoMatch", result.error)

    async def test_http_error_is_reported(self):
        client = FakeAzureSpeechRecognitionClient(
            AzureSpeechRecognitionResponse(status_code=401, body=b"bad key", error_text="bad key"),
        )
        recognizer = AzureSpeechRecognizer(
            AzureSpeechRecognitionConfig(region="francecentral", subscription_key="secret"),
            client=client,
        )

        result = await recognizer.transcribe(b"RIFFaudio")

        self.assertFalse(result.ok)
        self.assertIn("HTTP 401", result.error)
        self.assertIn("bad key", result.error)

    async def test_retryable_http_error_is_retried(self):
        client = FakeAzureSpeechRecognitionClient(responses=[
            AzureSpeechRecognitionResponse(status_code=429, body=b"rate limit", error_text="rate limit"),
            _json_response({"RecognitionStatus": "Success", "DisplayText": "Attack now."}),
        ])
        recognizer = AzureSpeechRecognizer(
            AzureSpeechRecognitionConfig(
                region="francecentral",
                subscription_key="secret",
                retry_attempts=1,
                retry_backoff_seconds=0.0,
            ),
            client=client,
        )

        result = await recognizer.transcribe(b"RIFFaudio")

        self.assertTrue(result.ok)
        self.assertEqual(result.text, "Attack now.")
        self.assertEqual(len(client.calls), 2)

    async def test_invalid_json_response_is_reported(self):
        client = FakeAzureSpeechRecognitionClient(AzureSpeechRecognitionResponse(status_code=200, body=b"not json"))
        recognizer = AzureSpeechRecognizer(
            AzureSpeechRecognitionConfig(region="francecentral", subscription_key="secret"),
            client=client,
        )

        result = await recognizer.transcribe(b"RIFFaudio")

        self.assertFalse(result.ok)
        self.assertIn("invalid JSON", result.error)

    async def test_validation_fails_without_http_call(self):
        cases = [
            (b"", AzureSpeechRecognitionConfig(region="francecentral", subscription_key="secret"), "audio is empty"),
            (b"RIFF", AzureSpeechRecognitionConfig(subscription_key="secret"), "region or endpoint is missing"),
            (b"RIFF", AzureSpeechRecognitionConfig(region="francecentral", language="", subscription_key="secret"), "language is missing"),
            (b"RIFF", AzureSpeechRecognitionConfig(region="francecentral", timeout_seconds=0, subscription_key="secret"), "timeout must be greater than zero"),
            (b"RIFF", AzureSpeechRecognitionConfig(region="francecentral", retry_attempts=-1, subscription_key="secret"), "retry attempts must be zero or greater"),
            (b"RIFF", AzureSpeechRecognitionConfig(region="francecentral", retry_backoff_seconds=-0.1, subscription_key="secret"), "retry backoff must be zero or greater"),
        ]

        for audio, config, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                client = FakeAzureSpeechRecognitionClient()
                recognizer = AzureSpeechRecognizer(config, client=client)

                result = await recognizer.transcribe(audio)

                self.assertFalse(result.ok)
                self.assertIn(expected_error, result.error)
                self.assertEqual(client.calls, [])

    def test_urllib_transport_posts_audio_and_returns_json_body(self):
        with patch("urllib.request.urlopen", return_value=FakeUrlopenResponse(200, b'{"RecognitionStatus":"Success"}')) as urlopen:
            response = _recognize_with_urllib(
                url="https://francecentral.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1",
                headers={"Ocp-Apim-Subscription-Key": "secret"},
                audio=b"RIFFaudio",
                timeout_seconds=3.5,
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3.5)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Ocp-apim-subscription-key"), "secret")
        self.assertEqual(request.data, b"RIFFaudio")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b'{"RecognitionStatus":"Success"}')

    def test_urllib_transport_returns_http_error_body(self):
        error = urllib.error.HTTPError(
            "https://francecentral.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1",
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b"bad audio"),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            response = _recognize_with_urllib(
                url="https://francecentral.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1",
                headers={"Ocp-Apim-Subscription-Key": "secret"},
                audio=b"RIFFaudio",
                timeout_seconds=3.5,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.body, b"bad audio")
        self.assertEqual(response.error_text, "bad audio")


def _json_response(payload):
    return AzureSpeechRecognitionResponse(status_code=200, body=json.dumps(payload).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
