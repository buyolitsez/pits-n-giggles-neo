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

from dataclasses import dataclass
from io import BytesIO
from typing import Optional
import wave

from .speech_recognition import DEFAULT_AZURE_STT_CONTENT_TYPE

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_PUSH_TO_TALK_AUDIO_FORMAT = "pcm16"
DEFAULT_PUSH_TO_TALK_SAMPLE_RATE_HZ = 16000
DEFAULT_PUSH_TO_TALK_CHANNELS = 1
DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES = 2
DEFAULT_PUSH_TO_TALK_MAX_AUDIO_BYTES = 3_000_000

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PushToTalkAudioClip:
    """One completed push-to-talk recording ready for speech recognition."""

    audio: bytes
    content_type: str
    audio_format: str
    session_id: Optional[str]
    chunk_count: int
    raw_audio_bytes: int
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int


class PushToTalkAudioBuffer:
    """Collect audio chunks between push-to-talk start and stop events."""

    def __init__(self, *, max_audio_bytes: int = DEFAULT_PUSH_TO_TALK_MAX_AUDIO_BYTES) -> None:
        self.max_audio_bytes = max(1, max_audio_bytes)
        self._active = False
        self._session_id: Optional[str] = None
        self._content_type = DEFAULT_AZURE_STT_CONTENT_TYPE
        self._audio_format = DEFAULT_PUSH_TO_TALK_AUDIO_FORMAT
        self._sample_rate_hz = DEFAULT_PUSH_TO_TALK_SAMPLE_RATE_HZ
        self._channels = DEFAULT_PUSH_TO_TALK_CHANNELS
        self._sample_width_bytes = DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES
        self._chunks: list[bytes] = []
        self._raw_audio_bytes = 0

    @property
    def active(self) -> bool:
        return self._active

    @property
    def raw_audio_bytes(self) -> int:
        return self._raw_audio_bytes

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def start(
        self,
        *,
        session_id: Optional[str] = None,
        content_type: str = DEFAULT_AZURE_STT_CONTENT_TYPE,
        audio_format: str = DEFAULT_PUSH_TO_TALK_AUDIO_FORMAT,
        sample_rate_hz: int = DEFAULT_PUSH_TO_TALK_SAMPLE_RATE_HZ,
        channels: int = DEFAULT_PUSH_TO_TALK_CHANNELS,
        sample_width_bytes: int = DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES,
    ) -> None:
        self.cancel()
        self._active = True
        self._session_id = _safe_text(session_id)
        self._content_type = _safe_text(content_type) or DEFAULT_AZURE_STT_CONTENT_TYPE
        self._audio_format = _normalise_audio_format(audio_format)
        self._sample_rate_hz = _positive_int(sample_rate_hz, DEFAULT_PUSH_TO_TALK_SAMPLE_RATE_HZ)
        self._channels = _positive_int(channels, DEFAULT_PUSH_TO_TALK_CHANNELS)
        self._sample_width_bytes = _positive_int(sample_width_bytes, DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES)

    def append(self, audio: bytes) -> None:
        if not self._active:
            raise RuntimeError("push-to-talk audio buffer is not active")
        if not audio:
            return
        next_size = self._raw_audio_bytes + len(audio)
        if next_size > self.max_audio_bytes:
            self.cancel()
            raise ValueError("push-to-talk audio buffer exceeded maximum size")
        self._chunks.append(bytes(audio))
        self._raw_audio_bytes = next_size

    def stop(self) -> Optional[PushToTalkAudioClip]:
        if not self._active:
            return None
        audio = b"".join(self._chunks)
        clip = None
        if audio:
            if self._audio_format == "pcm16":
                output_audio = _pcm16_to_wav(
                    audio,
                    sample_rate_hz=self._sample_rate_hz,
                    channels=self._channels,
                    sample_width_bytes=self._sample_width_bytes,
                )
                output_format = "wav"
                output_content_type = DEFAULT_AZURE_STT_CONTENT_TYPE
            else:
                output_audio = audio
                output_format = self._audio_format
                output_content_type = self._content_type
            clip = PushToTalkAudioClip(
                audio=output_audio,
                content_type=output_content_type,
                audio_format=output_format,
                session_id=self._session_id,
                chunk_count=len(self._chunks),
                raw_audio_bytes=self._raw_audio_bytes,
                sample_rate_hz=self._sample_rate_hz,
                channels=self._channels,
                sample_width_bytes=self._sample_width_bytes,
            )
        self.cancel()
        return clip

    def cancel(self) -> int:
        dropped = self._raw_audio_bytes
        self._active = False
        self._session_id = None
        self._chunks = []
        self._raw_audio_bytes = 0
        return dropped


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def _pcm16_to_wav(
    pcm: bytes,
    *,
    sample_rate_hz: int,
    channels: int,
    sample_width_bytes: int,
) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width_bytes)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


def _normalise_audio_format(value: str) -> str:
    value = (_safe_text(value) or DEFAULT_PUSH_TO_TALK_AUDIO_FORMAT).lower().replace("-", "_")
    if value in {"pcm", "pcm_16", "pcm16", "raw_pcm16"}:
        return "pcm16"
    if value in {"wav", "wave"}:
        return "wav"
    return DEFAULT_PUSH_TO_TALK_AUDIO_FORMAT


def _positive_int(value: int, default: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _safe_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None
