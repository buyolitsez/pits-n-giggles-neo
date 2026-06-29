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
import logging
from typing import Any, Dict, List, Optional, Protocol

# -------------------------------------- CLASSES -----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class VoiceResult:
    """Result returned by a voice engine after handling a message."""

    ok: bool
    provider: str
    text: str
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    audio_bytes: Optional[int] = None


class VoiceEngine(Protocol):
    """Protocol implemented by speech providers."""

    async def speak(
        self,
        text: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceResult:
        """Speak or record a message."""


class NullVoiceEngine:
    """Voice engine that intentionally drops all messages."""

    provider = "disabled"

    async def speak(
        self,
        text: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceResult:
        return VoiceResult(ok=True, provider=self.provider, text=text)


class DryRunVoiceEngine:
    """Voice engine used for development and tests without external TTS."""

    provider = "dry_run"

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger
        self.messages: List[Dict[str, Any]] = []

    async def speak(
        self,
        text: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceResult:
        record = {
            "text": text,
            "metadata": metadata or {},
        }
        self.messages.append(record)
        if self.logger:
            self.logger.info("[race-engineer][dry-run] %s", text)
        return VoiceResult(ok=True, provider=self.provider, text=text)
