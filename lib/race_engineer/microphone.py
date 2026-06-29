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

import ctypes
import ctypes.wintypes
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

from .push_to_talk import (
    DEFAULT_PUSH_TO_TALK_CHANNELS,
    DEFAULT_PUSH_TO_TALK_SAMPLE_RATE_HZ,
    DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES,
)

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_MICROPHONE_CHUNK_MS = 40

_MMSYSERR_NOERROR = 0
_WAVE_FORMAT_PCM = 1
_WAVE_MAPPER = -1
_CALLBACK_NULL = 0
_WHDR_DONE = 0x00000001

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MicrophoneCaptureConfig:
    """Runtime settings for push-to-talk microphone capture."""

    sample_rate_hz: int = DEFAULT_PUSH_TO_TALK_SAMPLE_RATE_HZ
    channels: int = DEFAULT_PUSH_TO_TALK_CHANNELS
    sample_width_bytes: int = DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES
    chunk_ms: int = DEFAULT_MICROPHONE_CHUNK_MS


class PushToTalkMicrophoneCapture(Protocol):
    """Protocol for local push-to-talk microphone capture backends."""

    provider: str

    @property
    def active(self) -> bool:
        """Return True while the microphone is recording."""

    def start(
        self,
        on_audio: Callable[[bytes], None],
        *,
        config: MicrophoneCaptureConfig,
    ) -> None:
        """Start recording and call on_audio with raw PCM chunks."""

    def stop(self) -> None:
        """Stop recording."""


class WindowsWaveInMicrophoneCapture:
    """Capture default Windows microphone audio through WinMM waveIn."""

    provider = "windows_microphone"

    def __init__(
        self,
        *,
        logger: Optional[logging.Logger] = None,
        buffer_count: int = 4,
        poll_interval_seconds: float = 0.01,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.buffer_count = max(2, int(buffer_count))
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self._active = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handle = None
        self._buffers: List[ctypes.Array] = []
        self._headers: List["_WaveHdr"] = []
        self._winmm = None
        self._on_audio: Optional[Callable[[bytes], None]] = None

    @property
    def active(self) -> bool:
        return self._active

    def start(
        self,
        on_audio: Callable[[bytes], None],
        *,
        config: MicrophoneCaptureConfig,
    ) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows microphone capture is only available on Windows.")
        if self._active:
            raise RuntimeError("microphone capture is already active")

        config = _normalise_microphone_config(config)
        block_align = config.channels * config.sample_width_bytes
        chunk_size = max(
            block_align,
            int(config.sample_rate_hz * config.chunk_ms / 1000.0) * block_align,
        )
        chunk_size = max(block_align, chunk_size - (chunk_size % block_align))

        self._winmm = _load_winmm()
        self._handle = ctypes.wintypes.HANDLE()
        self._buffers = []
        self._headers = []
        self._on_audio = on_audio
        self._stop_event.clear()

        fmt = _WaveFormatEx(
            wFormatTag=_WAVE_FORMAT_PCM,
            nChannels=config.channels,
            nSamplesPerSec=config.sample_rate_hz,
            nAvgBytesPerSec=config.sample_rate_hz * block_align,
            nBlockAlign=block_align,
            wBitsPerSample=config.sample_width_bytes * 8,
            cbSize=0,
        )

        try:
            _check_mm_result(
                self._winmm.waveInOpen(
                    ctypes.byref(self._handle),
                    ctypes.c_uint(_WAVE_MAPPER),
                    ctypes.byref(fmt),
                    ctypes.c_size_t(0),
                    ctypes.c_size_t(0),
                    ctypes.c_uint(_CALLBACK_NULL),
                ),
                "waveInOpen",
            )
            for _index in range(self.buffer_count):
                buffer = ctypes.create_string_buffer(chunk_size)
                header = _WaveHdr(
                    lpData=ctypes.addressof(buffer),
                    dwBufferLength=chunk_size,
                    dwBytesRecorded=0,
                    dwUser=0,
                    dwFlags=0,
                    dwLoops=0,
                    lpNext=0,
                    reserved=0,
                )
                _check_mm_result(
                    self._winmm.waveInPrepareHeader(
                        self._handle,
                        ctypes.byref(header),
                        ctypes.sizeof(header),
                    ),
                    "waveInPrepareHeader",
                )
                _check_mm_result(
                    self._winmm.waveInAddBuffer(
                        self._handle,
                        ctypes.byref(header),
                        ctypes.sizeof(header),
                    ),
                    "waveInAddBuffer",
                )
                self._buffers.append(buffer)
                self._headers.append(header)

            _check_mm_result(self._winmm.waveInStart(self._handle), "waveInStart")
            self._active = True
            self._thread = threading.Thread(
                target=self._poll_loop,
                name="race-engineer-microphone",
                daemon=True,
            )
            self._thread.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if not self._handle:
            self._active = False
            self._stop_event.set()
            return

        self._stop_event.set()
        winmm = self._winmm
        handle = self._handle
        if winmm:
            winmm.waveInStop(handle)
            winmm.waveInReset(handle)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        if winmm:
            for header in self._headers:
                winmm.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
            winmm.waveInClose(handle)

        self._active = False
        self._thread = None
        self._handle = None
        self._buffers = []
        self._headers = []
        self._on_audio = None

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            for header in self._headers:
                if not (header.dwFlags & _WHDR_DONE):
                    continue
                if header.dwBytesRecorded:
                    audio = ctypes.string_at(header.lpData, header.dwBytesRecorded)
                    try:
                        if self._on_audio:
                            self._on_audio(audio)
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        self.logger.warning("Microphone audio chunk was ignored: %s", exc)
                header.dwBytesRecorded = 0
                if self._handle and self._winmm:
                    self._winmm.waveInAddBuffer(
                        self._handle,
                        ctypes.byref(header),
                        ctypes.sizeof(header),
                    )
            time.sleep(self.poll_interval_seconds)


class _WaveFormatEx(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_ushort),
        ("nChannels", ctypes.c_ushort),
        ("nSamplesPerSec", ctypes.c_uint),
        ("nAvgBytesPerSec", ctypes.c_uint),
        ("nBlockAlign", ctypes.c_ushort),
        ("wBitsPerSample", ctypes.c_ushort),
        ("cbSize", ctypes.c_ushort),
    ]


class _WaveHdr(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.c_uint),
        ("dwBytesRecorded", ctypes.c_uint),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", ctypes.c_uint),
        ("dwLoops", ctypes.c_uint),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def _normalise_microphone_config(config: MicrophoneCaptureConfig) -> MicrophoneCaptureConfig:
    sample_rate_hz = _positive_int(config.sample_rate_hz, DEFAULT_PUSH_TO_TALK_SAMPLE_RATE_HZ)
    channels = _positive_int(config.channels, DEFAULT_PUSH_TO_TALK_CHANNELS)
    sample_width_bytes = _positive_int(config.sample_width_bytes, DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES)
    chunk_ms = _positive_int(config.chunk_ms, DEFAULT_MICROPHONE_CHUNK_MS)
    if sample_width_bytes not in {1, 2}:
        sample_width_bytes = DEFAULT_PUSH_TO_TALK_SAMPLE_WIDTH_BYTES
    return MicrophoneCaptureConfig(
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        sample_width_bytes=sample_width_bytes,
        chunk_ms=chunk_ms,
    )


def _load_winmm():
    winmm = ctypes.WinDLL("winmm")
    winmm.waveInOpen.argtypes = [
        ctypes.POINTER(ctypes.wintypes.HANDLE),
        ctypes.c_uint,
        ctypes.POINTER(_WaveFormatEx),
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint,
    ]
    winmm.waveInOpen.restype = ctypes.c_uint
    for name in (
            "waveInPrepareHeader",
            "waveInUnprepareHeader",
            "waveInAddBuffer"):
        fn = getattr(winmm, name)
        fn.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(_WaveHdr), ctypes.c_uint]
        fn.restype = ctypes.c_uint
    for name in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
        fn = getattr(winmm, name)
        fn.argtypes = [ctypes.wintypes.HANDLE]
        fn.restype = ctypes.c_uint
    return winmm


def _check_mm_result(result: int, operation: str) -> None:
    if result != _MMSYSERR_NOERROR:
        raise RuntimeError(f"{operation} failed with WinMM error {result}")


def _positive_int(value: int, default: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
