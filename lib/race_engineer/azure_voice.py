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
from html import escape
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, Optional, Protocol
from urllib.parse import urlparse

from .voice import VoiceResult

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_AZURE_SPEECH_ENDPOINT_TEMPLATE = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
DEFAULT_AZURE_SPEECH_SYNTHESIS_PATH = "/cognitiveservices/v1"
DEFAULT_AZURE_SPEECH_OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"
DEFAULT_AZURE_SPEECH_USER_AGENT = "pits-n-giggles-race-engineer"
DEFAULT_AZURE_SPEECH_VOICE = "en-US-GuyNeural"
DEFAULT_AZURE_SPEECH_KEY_ENV_VAR = "PNG_AZURE_SPEECH_KEY"

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AzureSpeechConfig:
    """Configuration for Azure Speech Text to Speech."""

    region: str
    voice: str = DEFAULT_AZURE_SPEECH_VOICE
    subscription_key: Optional[str] = None
    key_env_var: str = DEFAULT_AZURE_SPEECH_KEY_ENV_VAR
    output_format: str = DEFAULT_AZURE_SPEECH_OUTPUT_FORMAT
    endpoint: Optional[str] = None
    timeout_seconds: float = 10.0
    retry_attempts: int = 1
    retry_backoff_seconds: float = 0.2
    user_agent: str = DEFAULT_AZURE_SPEECH_USER_AGENT
    locale: Optional[str] = None
    endpoint_template: str = DEFAULT_AZURE_SPEECH_ENDPOINT_TEMPLATE

    def endpoint_url(self) -> str:
        endpoint = (self.endpoint or "").strip()
        if endpoint:
            return build_azure_speech_endpoint_url(endpoint=endpoint)
        region = self.region.strip()
        if not region:
            return ""
        return build_azure_speech_endpoint_url(
            region=region,
            endpoint_template=self.endpoint_template,
        )

    def resolved_key(self) -> Optional[str]:
        if self.subscription_key:
            return self.subscription_key
        if not self.key_env_var:
            return None
        return os.getenv(self.key_env_var)

    def resolved_locale(self) -> str:
        if self.locale and self.locale.strip():
            return self.locale.strip()
        parts = self.voice.split("-")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return f"{parts[0]}-{parts[1]}"
        return "en-US"


@dataclass(frozen=True, slots=True)
class AzureSpeechResponse:
    """HTTP response details returned by an Azure Speech client."""

    status_code: int
    audio: bytes = b""
    error_text: Optional[str] = None


class AzureSpeechClient(Protocol):
    """Protocol for the small Azure Speech REST surface used by the voice engine."""

    async def synthesize(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        ssml: str,
        timeout_seconds: float,
    ) -> AzureSpeechResponse:
        """Synthesize SSML into audio bytes."""


class AudioSink(Protocol):
    """Protocol for playing synthesized audio bytes."""

    async def play(
        self,
        audio: bytes,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Play audio bytes."""


class AioHttpAzureSpeechClient:
    """Azure Speech REST client implemented with aiohttp or a stdlib fallback."""

    async def synthesize(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        ssml: str,
        timeout_seconds: float,
    ) -> AzureSpeechResponse:
        try:
            import aiohttp
        except ModuleNotFoundError:
            return await asyncio.to_thread(
                _synthesize_with_urllib,
                url=url,
                headers=headers,
                ssml=ssml,
                timeout_seconds=timeout_seconds,
            )

        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=ssml.encode("utf-8")) as response:
                body = await response.read()
                error_text = None
                if response.status >= 400:
                    error_text = body.decode("utf-8", errors="replace")
                return AzureSpeechResponse(
                    status_code=response.status,
                    audio=body,
                    error_text=error_text,
                )


class NoOpAudioSink:
    """Audio sink used when synthesized audio should be ignored."""

    async def play(
        self,
        audio: bytes,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        del audio, metadata


class WindowsWaveAudioSink:
    """Play RIFF/WAV audio bytes on Windows without extra dependencies."""

    def __init__(self, *, temp_dir: Optional[str] = None) -> None:
        self._temp_dir = temp_dir

    async def play(
        self,
        audio: bytes,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        del metadata
        await asyncio.to_thread(self._play_sync, audio)

    def _play_sync(self, audio: bytes) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsWaveAudioSink requires Windows")
        import winsound

        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                dir=self._temp_dir,
                suffix=".wav",
            ) as wav_file:
                wav_file.write(audio)
                temp_path = Path(wav_file.name)
            winsound.PlaySound(str(temp_path), winsound.SND_FILENAME)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)


class AzureSpeechVoiceEngine:
    """Voice engine that sends callouts to Microsoft Azure Speech."""

    provider = "azure"

    def __init__(
        self,
        config: AzureSpeechConfig,
        *,
        client: Optional[AzureSpeechClient] = None,
        audio_sink: Optional[AudioSink] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._config = config
        self._client = client or AioHttpAzureSpeechClient()
        self._audio_sink = audio_sink or NoOpAudioSink()
        self._logger = logger

    async def speak(
        self,
        text: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceResult:
        started_at = time.perf_counter()
        validation_error = self._validate(text)
        if validation_error:
            return VoiceResult(
                ok=False,
                provider=self.provider,
                text=text,
                error=validation_error,
                duration_ms=_elapsed_ms(started_at),
            )

        subscription_key = self._config.resolved_key()
        if not subscription_key:
            key_source = self._config.key_env_var or "subscription_key"
            return VoiceResult(
                ok=False,
                provider=self.provider,
                text=text,
                error=f"Azure Speech subscription key is missing: set {key_source}",
                duration_ms=_elapsed_ms(started_at),
            )

        ssml = build_azure_speech_ssml(
            text,
            voice=self._config.voice.strip(),
            locale=self._config.resolved_locale(),
        )
        headers = build_azure_speech_headers(self._config, subscription_key)

        synth_started_at = time.perf_counter()
        response, request_error, attempt_count = await self._synthesize_with_retries(
            url=self._config.endpoint_url(),
            headers=headers,
            ssml=ssml,
        )
        synth_ms = _elapsed_ms(synth_started_at)

        if request_error:
            return VoiceResult(
                ok=False,
                provider=self.provider,
                text=text,
                error=f"Azure Speech request failed after {attempt_count} attempt(s): {request_error}",
                duration_ms=_elapsed_ms(started_at),
            )

        if response.status_code != 200:
            return VoiceResult(
                ok=False,
                provider=self.provider,
                text=text,
                error=_format_azure_error(response, attempt_count=attempt_count),
                duration_ms=_elapsed_ms(started_at),
                audio_bytes=len(response.audio),
            )

        playback_started_at = time.perf_counter()
        try:
            await self._audio_sink.play(
                response.audio,
                metadata={
                    **(metadata or {}),
                    "provider": self.provider,
                    "output_format": self._config.output_format,
                    "audio_bytes": len(response.audio),
                    "synthesis_ms": synth_ms,
                    "synthesis_attempts": attempt_count,
                },
            )
        except (OSError, RuntimeError) as exc:
            return VoiceResult(
                ok=False,
                provider=self.provider,
                text=text,
                error=f"Azure Speech audio playback failed: {exc}",
                duration_ms=_elapsed_ms(started_at),
                audio_bytes=len(response.audio),
            )
        playback_ms = _elapsed_ms(playback_started_at)

        if self._logger:
            self._logger.info(
                "[race-engineer][azure] %.1f ms synth, %.1f ms playback, %d bytes: %s",
                synth_ms,
                playback_ms,
                len(response.audio),
                text,
            )
        return VoiceResult(
            ok=True,
            provider=self.provider,
            text=text,
            duration_ms=_elapsed_ms(started_at),
            audio_bytes=len(response.audio),
        )

    def _validate(self, text: str) -> Optional[str]:
        if not text or not text.strip():
            return "Azure Speech text is empty"
        if not self._config.endpoint_url():
            return "Azure Speech region or endpoint is missing"
        if not self._config.voice or not self._config.voice.strip():
            return "Azure Speech voice is missing"
        if not self._config.output_format or not self._config.output_format.strip():
            return "Azure Speech output format is missing"
        if self._config.timeout_seconds <= 0:
            return "Azure Speech timeout must be greater than zero"
        if self._config.retry_attempts < 0:
            return "Azure Speech retry attempts must be zero or greater"
        if self._config.retry_backoff_seconds < 0:
            return "Azure Speech retry backoff must be zero or greater"
        return None

    async def _synthesize_with_retries(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        ssml: str,
    ) -> tuple[AzureSpeechResponse, Optional[Exception], int]:
        max_attempts = max(1, self._config.retry_attempts + 1)
        attempt_count = 0
        last_response = AzureSpeechResponse(status_code=599, error_text="request was not sent")

        for attempt_index in range(max_attempts):
            attempt_count = attempt_index + 1
            try:
                response = await self._client.synthesize(
                    url=url,
                    headers=headers,
                    ssml=ssml,
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


def build_azure_speech_ssml(text: str, *, voice: str, locale: str) -> str:
    """Build SSML accepted by the Azure Speech Text to Speech REST endpoint."""

    escaped_text = escape(text, quote=False)
    escaped_voice = escape(voice, quote=True)
    escaped_locale = escape(locale, quote=True)
    return (
        f'<speak version="1.0" xml:lang="{escaped_locale}">'
        f'<voice xml:lang="{escaped_locale}" name="{escaped_voice}">'
        f"{escaped_text}"
        "</voice>"
        "</speak>"
    )


def build_azure_speech_headers(config: AzureSpeechConfig, subscription_key: str) -> Dict[str, str]:
    """Build headers for the Azure Speech Text to Speech REST endpoint."""

    return {
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": config.output_format,
        "User-Agent": config.user_agent,
    }


def build_azure_speech_endpoint_url(
    *,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    endpoint_template: str = DEFAULT_AZURE_SPEECH_ENDPOINT_TEMPLATE,
) -> str:
    """Build an Azure Speech Text to Speech REST endpoint URL."""

    endpoint = (endpoint or "").strip()
    if endpoint:
        return _normalise_speech_endpoint(endpoint)
    region = (region or "").strip()
    if not region:
        return ""
    return endpoint_template.format(region=region)


def _normalise_speech_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    parsed = urlparse(endpoint)
    host = parsed.netloc.lower()
    if DEFAULT_AZURE_SPEECH_SYNTHESIS_PATH in parsed.path:
        return endpoint
    if host.endswith(".api.cognitive.microsoft.com"):
        region = host.split(".", maxsplit=1)[0]
        return f"https://{region}.tts.speech.microsoft.com{DEFAULT_AZURE_SPEECH_SYNTHESIS_PATH}"
    return f"{endpoint.rstrip('/')}{DEFAULT_AZURE_SPEECH_SYNTHESIS_PATH}"


def _synthesize_with_urllib(
    *,
    url: str,
    headers: Dict[str, str],
    ssml: str,
    timeout_seconds: float,
) -> AzureSpeechResponse:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        data=ssml.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            audio = response.read()
            return AzureSpeechResponse(
                status_code=int(response.getcode()),
                audio=audio,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return AzureSpeechResponse(
            status_code=int(exc.code),
            audio=body,
            error_text=body.decode("utf-8", errors="replace"),
        )


def _format_azure_error(response: AzureSpeechResponse, *, attempt_count: int = 1) -> str:
    detail = ""
    if response.error_text:
        detail = f": {response.error_text[:200]}"
    attempt_text = f" after {attempt_count} attempt(s)" if attempt_count > 1 else ""
    return f"Azure Speech request failed with HTTP {response.status_code}{attempt_text}{detail}"


def _is_retryable_azure_status(status_code: int) -> bool:
    return status_code in {408, 429} or status_code >= 500


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)
