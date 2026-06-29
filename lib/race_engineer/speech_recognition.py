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

# -------------------------------------- IMPORTS -----------------------------------------------------------------------

import asyncio
from dataclasses import dataclass
import json
import os
import time
from typing import Any, Dict, Optional, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .azure_voice import DEFAULT_AZURE_SPEECH_KEY_ENV_VAR

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_AZURE_STT_LANGUAGE = "ru-RU"
DEFAULT_AZURE_STT_FORMAT = "simple"
DEFAULT_AZURE_STT_PROFANITY = "masked"
DEFAULT_AZURE_STT_CONTENT_TYPE = "audio/wav; codecs=audio/pcm; samplerate=16000"
DEFAULT_AZURE_STT_RECOGNITION_PATH = "/speech/recognition/conversation/cognitiveservices/v1"
DEFAULT_AZURE_STT_USER_AGENT = "pits-n-giggles-race-engineer"

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpeechRecognitionResult:
    """Speech recognition result for one push-to-talk recording."""

    ok: bool
    provider: str
    text: str = ""
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    confidence: Optional[float] = None
    status: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class SpeechRecognizer(Protocol):
    """Protocol implemented by speech-to-text providers."""

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: Optional[str] = None,
    ) -> SpeechRecognitionResult:
        """Transcribe one complete audio recording."""


@dataclass(frozen=True, slots=True)
class AzureSpeechRecognitionConfig:
    """Configuration for Azure Speech-to-Text short audio recognition."""

    region: str = ""
    endpoint: Optional[str] = None
    subscription_key: Optional[str] = None
    key_env_var: str = DEFAULT_AZURE_SPEECH_KEY_ENV_VAR
    language: str = DEFAULT_AZURE_STT_LANGUAGE
    result_format: str = DEFAULT_AZURE_STT_FORMAT
    profanity: str = DEFAULT_AZURE_STT_PROFANITY
    content_type: str = DEFAULT_AZURE_STT_CONTENT_TYPE
    timeout_seconds: float = 10.0
    retry_attempts: int = 1
    retry_backoff_seconds: float = 0.2
    user_agent: str = DEFAULT_AZURE_STT_USER_AGENT

    def endpoint_url(self) -> str:
        endpoint = (self.endpoint or "").strip()
        if endpoint:
            return build_azure_stt_endpoint_url(
                endpoint=endpoint,
                language=self.language,
                result_format=self.result_format,
                profanity=self.profanity,
            )
        if not self.region.strip():
            return ""
        return build_azure_stt_endpoint_url(
            region=self.region,
            language=self.language,
            result_format=self.result_format,
            profanity=self.profanity,
        )

    def resolved_key(self) -> Optional[str]:
        if self.subscription_key:
            return self.subscription_key
        if not self.key_env_var:
            return None
        return os.getenv(self.key_env_var)


@dataclass(frozen=True, slots=True)
class AzureSpeechRecognitionResponse:
    """HTTP response details returned by an Azure Speech recognition client."""

    status_code: int
    body: bytes = b""
    error_text: Optional[str] = None


class AzureSpeechRecognitionClient(Protocol):
    """Protocol for the small Azure Speech-to-Text REST surface."""

    async def recognize(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        audio: bytes,
        timeout_seconds: float,
    ) -> AzureSpeechRecognitionResponse:
        """Recognize one audio payload."""


class AioHttpAzureSpeechRecognitionClient:
    """Azure Speech-to-Text REST client implemented with aiohttp or stdlib fallback."""

    async def recognize(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        audio: bytes,
        timeout_seconds: float,
    ) -> AzureSpeechRecognitionResponse:
        try:
            import aiohttp
        except ModuleNotFoundError:
            return await asyncio.to_thread(
                _recognize_with_urllib,
                url=url,
                headers=headers,
                audio=audio,
                timeout_seconds=timeout_seconds,
            )

        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=audio) as response:
                body = await response.read()
                error_text = None
                if response.status >= 400:
                    error_text = body.decode("utf-8", errors="replace")
                return AzureSpeechRecognitionResponse(
                    status_code=response.status,
                    body=body,
                    error_text=error_text,
                )


class AzureSpeechRecognizer:
    """Speech recognizer that sends push-to-talk audio to Microsoft Azure Speech."""

    provider = "azure"

    def __init__(
        self,
        config: AzureSpeechRecognitionConfig,
        *,
        client: Optional[AzureSpeechRecognitionClient] = None,
    ) -> None:
        self._config = config
        self._client = client or AioHttpAzureSpeechRecognitionClient()

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: Optional[str] = None,
    ) -> SpeechRecognitionResult:
        started_at = time.perf_counter()
        validation_error = self._validate(audio)
        if validation_error:
            return SpeechRecognitionResult(
                ok=False,
                provider=self.provider,
                error=validation_error,
                duration_ms=_elapsed_ms(started_at),
            )

        subscription_key = self._config.resolved_key()
        if not subscription_key:
            key_source = self._config.key_env_var or "subscription_key"
            return SpeechRecognitionResult(
                ok=False,
                provider=self.provider,
                error=f"Azure Speech subscription key is missing: set {key_source}",
                duration_ms=_elapsed_ms(started_at),
            )

        response, request_error, attempt_count = await self._recognize_with_retries(
            url=self._config.endpoint_url(),
            headers=build_azure_stt_headers(
                self._config,
                subscription_key,
                content_type=content_type or self._config.content_type,
            ),
            audio=audio,
        )
        if request_error:
            return SpeechRecognitionResult(
                ok=False,
                provider=self.provider,
                error=f"Azure Speech recognition failed after {attempt_count} attempt(s): {request_error}",
                duration_ms=_elapsed_ms(started_at),
            )

        if response.status_code != 200:
            return SpeechRecognitionResult(
                ok=False,
                provider=self.provider,
                error=_format_azure_stt_error(response, attempt_count=attempt_count),
                duration_ms=_elapsed_ms(started_at),
            )

        return _recognition_result_from_response(
            response,
            provider=self.provider,
            duration_ms=_elapsed_ms(started_at),
        )

    def _validate(self, audio: bytes) -> Optional[str]:
        if not audio:
            return "Azure Speech recognition audio is empty"
        if not self._config.endpoint_url():
            return "Azure Speech recognition region or endpoint is missing"
        if not self._config.language.strip():
            return "Azure Speech recognition language is missing"
        if self._config.timeout_seconds <= 0:
            return "Azure Speech recognition timeout must be greater than zero"
        if self._config.retry_attempts < 0:
            return "Azure Speech recognition retry attempts must be zero or greater"
        if self._config.retry_backoff_seconds < 0:
            return "Azure Speech recognition retry backoff must be zero or greater"
        return None

    async def _recognize_with_retries(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        audio: bytes,
    ) -> tuple[AzureSpeechRecognitionResponse, Optional[Exception], int]:
        max_attempts = max(1, self._config.retry_attempts + 1)
        attempt_count = 0
        last_response = AzureSpeechRecognitionResponse(status_code=599, error_text="request was not sent")

        for attempt_index in range(max_attempts):
            attempt_count = attempt_index + 1
            try:
                response = await self._client.recognize(
                    url=url,
                    headers=headers,
                    audio=audio,
                    timeout_seconds=self._config.timeout_seconds,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if attempt_index + 1 >= max_attempts:
                    return last_response, exc, attempt_count
                await self._sleep_before_retry(attempt_index)
                continue

            last_response = response
            if not _is_retryable_azure_status(response.status_code) or attempt_index + 1 >= max_attempts:
                return response, None, attempt_count
            await self._sleep_before_retry(attempt_index)

        return last_response, None, attempt_count

    async def _sleep_before_retry(self, attempt_index: int) -> None:
        if self._config.retry_backoff_seconds <= 0:
            return
        await asyncio.sleep(self._config.retry_backoff_seconds * (attempt_index + 1))


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def build_azure_stt_endpoint_url(
    *,
    language: str,
    result_format: str = DEFAULT_AZURE_STT_FORMAT,
    profanity: str = DEFAULT_AZURE_STT_PROFANITY,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> str:
    """Build an Azure Speech-to-Text short-audio endpoint URL."""

    if endpoint:
        base_url = _normalise_stt_endpoint(endpoint)
    else:
        base_url = f"https://{(region or '').strip()}.stt.speech.microsoft.com{DEFAULT_AZURE_STT_RECOGNITION_PATH}"

    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["language"] = language.strip()
    query["format"] = (result_format or DEFAULT_AZURE_STT_FORMAT).strip().lower()
    if profanity:
        query["profanity"] = profanity.strip().lower()
    return urlunparse(parsed._replace(query=urlencode(query)))


def build_azure_stt_headers(
    config: AzureSpeechRecognitionConfig,
    subscription_key: str,
    *,
    content_type: str,
) -> Dict[str, str]:
    """Build headers for the Azure Speech-to-Text REST endpoint."""

    return {
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Content-Type": content_type,
        "Accept": "application/json",
        "User-Agent": config.user_agent,
    }


def _normalise_stt_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    parsed = urlparse(endpoint)
    host = parsed.netloc.lower()
    if DEFAULT_AZURE_STT_RECOGNITION_PATH in parsed.path:
        return endpoint
    if host.endswith(".api.cognitive.microsoft.com"):
        region = host.split(".", maxsplit=1)[0]
        return f"https://{region}.stt.speech.microsoft.com{DEFAULT_AZURE_STT_RECOGNITION_PATH}"
    return f"{endpoint.rstrip('/')}{DEFAULT_AZURE_STT_RECOGNITION_PATH}"


def _recognition_result_from_response(
    response: AzureSpeechRecognitionResponse,
    *,
    provider: str,
    duration_ms: float,
) -> SpeechRecognitionResult:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return SpeechRecognitionResult(
            ok=False,
            provider=provider,
            error=f"Azure Speech recognition returned invalid JSON: {exc}",
            duration_ms=duration_ms,
        )

    status = _safe_text(payload.get("RecognitionStatus"))
    text = _text_from_azure_stt_payload(payload)
    confidence = _confidence_from_azure_stt_payload(payload)
    ok = bool(text) and status in {None, "Success"}
    if ok:
        return SpeechRecognitionResult(
            ok=True,
            provider=provider,
            text=text,
            confidence=confidence,
            status=status,
            duration_ms=duration_ms,
            raw=payload,
        )

    error = payload.get("ErrorDetails") or f"Azure Speech recognition status: {status or 'unknown'}"
    return SpeechRecognitionResult(
        ok=False,
        provider=provider,
        text=text,
        confidence=confidence,
        status=status,
        error=str(error),
        duration_ms=duration_ms,
        raw=payload,
    )


def _text_from_azure_stt_payload(payload: Dict[str, Any]) -> str:
    display_text = _safe_text(payload.get("DisplayText"))
    if display_text:
        return display_text

    nbest = payload.get("NBest")
    if isinstance(nbest, list):
        for item in nbest:
            if not isinstance(item, dict):
                continue
            text = _safe_text(item.get("Display") or item.get("Lexical"))
            if text:
                return text
    return ""


def _confidence_from_azure_stt_payload(payload: Dict[str, Any]) -> Optional[float]:
    nbest = payload.get("NBest")
    if not isinstance(nbest, list) or not nbest or not isinstance(nbest[0], dict):
        return None
    confidence = nbest[0].get("Confidence")
    if isinstance(confidence, bool):
        return None
    if isinstance(confidence, (int, float)):
        return float(confidence)
    return None


def _recognize_with_urllib(
    *,
    url: str,
    headers: Dict[str, str],
    audio: bytes,
    timeout_seconds: float,
) -> AzureSpeechRecognitionResponse:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        data=audio,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            return AzureSpeechRecognitionResponse(
                status_code=int(response.getcode()),
                body=body,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return AzureSpeechRecognitionResponse(
            status_code=int(exc.code),
            body=body,
            error_text=body.decode("utf-8", errors="replace"),
        )


def _format_azure_stt_error(response: AzureSpeechRecognitionResponse, *, attempt_count: int = 1) -> str:
    detail = ""
    if response.error_text:
        detail = f": {response.error_text[:200]}"
    attempt_text = f" after {attempt_count} attempt(s)" if attempt_count > 1 else ""
    return f"Azure Speech recognition request failed with HTTP {response.status_code}{attempt_text}{detail}"


def _is_retryable_azure_status(status_code: int) -> bool:
    return status_code in {408, 429} or status_code >= 500


def _safe_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)
