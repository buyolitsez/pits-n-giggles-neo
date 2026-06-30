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

import argparse
import asyncio
import json
from dataclasses import replace
import logging
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from lib.child_proc_mgmt import notify_parent_init_complete, report_pid_from_child
from lib.logger import get_logger
from lib.race_engineer import (
    AzureSpeechConfig,
    AzureSpeechRecognitionConfig,
    AzureSpeechRecognizer,
    AzureSpeechVoiceEngine,
    BoundedLatestVoiceQueue,
    CodexCliConversationAgent,
    CodexCliConversationConfig,
    DEFAULT_AZURE_SPEECH_KEY_ENV_VAR,
    DEFAULT_AZURE_SPEECH_OUTPUT_FORMAT,
    DEFAULT_AZURE_SPEECH_VOICE,
    DEFAULT_AZURE_STT_CONTENT_TYPE,
    DEFAULT_AZURE_STT_FORMAT,
    DEFAULT_AZURE_STT_LANGUAGE,
    DEFAULT_AGENT_PROMPTS_FILE_ENV_VAR,
    DEFAULT_MICROPHONE_CHUNK_MS,
    DryRunVoiceEngine,
    DrivingTraceRecorder,
    FallbackConversationAgent,
    HttpConversationAgent,
    HttpConversationConfig,
    LocalBriefConversationAgent,
    MicrophoneCaptureConfig,
    NoOpAudioSink,
    NullVoiceEngine,
    PushToTalkAudioBuffer,
    PushToTalkMicrophoneCapture,
    RaceEngineerAnnouncer,
    RaceEngineerAnnouncement,
    RaceEngineerAnswer,
    RaceEngineerConversationAgent,
    RaceEngineerHistory,
    RaceEngineerProfileDiagnostic,
    SpeechRecognitionResult,
    SpeechRecognizer,
    VoiceEngine,
    VoiceResult,
    WindowsWaveAudioSink,
    WindowsWaveInMicrophoneCapture,
    diagnose_race_engineer_launch_profile,
    format_race_engineer_profile_diagnostics,
    load_race_engineer_launch_profile,
    load_agent_prompt_overrides,
    race_engineer_launch_profile_to_cli_args,
    race_engineer_profile_has_errors,
    sample_from_trace_update,
    save_agent_prompt_override_template,
)
from lib.version import get_version
from meta.meta import APP_NAME

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

_VOICE_PRIORITY_RANK = {
    "critical": 0,
    "warning": 1,
    "advisory": 2,
    "info": 3,
}

_PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL = "external"
_PUSH_TO_TALK_AUDIO_SOURCE_WINDOWS_MICROPHONE = "windows_microphone"
_CONVERSATION_PROVIDER_LOCAL = "local_brief"
_CONVERSATION_PROVIDER_HTTP = "http"
_CONVERSATION_PROVIDER_CODEX_CLI = "codex_cli"
_DEFAULT_PROFILE_PREFLIGHT_QUESTION = "какие шины брать на пит?"

# -------------------------------------- CLASSES -----------------------------------------------------------------------

class RaceEngineerApp:
    """Subscribe to telemetry snapshots and emit race engineer voice callouts."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        broker_xpub_port: int,
        voice_engine: VoiceEngine,
        min_priority: str,
        cooldown_seconds: int,
        max_items: int,
        max_queue_size: int,
        focus: str,
        min_voice_interval_seconds: float = 0.0,
        initial_enabled: bool = True,
        conversation_agent: Optional[RaceEngineerConversationAgent] = None,
        speech_recognizer: Optional[SpeechRecognizer] = None,
        push_to_talk_buffer: Optional[PushToTalkAudioBuffer] = None,
        microphone_capture: Optional[PushToTalkMicrophoneCapture] = None,
        monotonic_clock: Optional[Callable[[], float]] = None,
    ) -> None:
        from lib.ipc import IpcSubscriberAsync

        self.logger = logger
        self.voice_engine = voice_engine
        self.focus = focus
        self.min_voice_interval_seconds = max(0.0, min_voice_interval_seconds)
        self._monotonic_clock = monotonic_clock or time.monotonic
        self.subscriber = IpcSubscriberAsync(port=broker_xpub_port, logger=logger)
        self.announcer = RaceEngineerAnnouncer(
            min_priority=min_priority,
            cooldown_seconds=cooldown_seconds,
            max_items=max_items,
            history=RaceEngineerHistory(),
        )
        self.conversation_agent = conversation_agent or LocalBriefConversationAgent()
        self.speech_recognizer = speech_recognizer
        self.push_to_talk_buffer = push_to_talk_buffer or PushToTalkAudioBuffer()
        self.microphone_capture = microphone_capture
        self.voice_queue = BoundedLatestVoiceQueue(max_size=max_queue_size)
        self.trace_recorder = DrivingTraceRecorder()
        self.enabled = bool(initial_enabled)
        self._using_backend_trace = False
        self._voice_task: Optional[asyncio.Task[None]] = None
        self._active_voice_task: Optional[asyncio.Task[None]] = None
        self._active_voice_cancel_reason = "voice playback cancelled"
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._announcements_count = 0
        self._dropped_announcements_count = 0
        self._rate_limited_announcements_count = 0
        self._aborted_announcements_count = 0
        self._control_events_count = 0
        self._questions_answered_count = 0
        self._question_failures_count = 0
        self._speech_questions_count = 0
        self._speech_recognition_failures_count = 0
        self._push_to_talk_sessions_count = 0
        self._push_to_talk_failures_count = 0
        self._voice_failures_count = 0
        self._last_voice_result: Optional[Dict[str, Any]] = None
        self._last_question_result: Optional[Dict[str, Any]] = None
        self._last_speech_recognition_result: Optional[Dict[str, Any]] = None
        self._last_voice_queued_at: Optional[float] = None
        self._session_uid: Optional[str] = None
        self._session_generation = 0
        self._init_routes()

    async def run(self) -> None:
        self.logger.info("Race engineer app started")
        self._voice_task = asyncio.create_task(self._voice_worker(), name="race-engineer-voice")
        try:
            await self.subscriber.run()
        finally:
            await self._stop_voice_worker()

    def close(self) -> None:
        self.subscriber.close()
        self._cancel_push_to_talk_recording()
        if self._voice_task and not self._voice_task.done():
            self._voice_task.cancel()

    def get_stats(self) -> Dict[str, Any]:
        status, status_detail = self._runtime_status()
        return {
            "assistant-status": status,
            "assistant-status-detail": status_detail,
            "announcements-count": self._announcements_count,
            "dropped-announcements-count": self._dropped_announcements_count,
            "rate-limited-announcements-count": self._rate_limited_announcements_count,
            "aborted-announcements-count": self._aborted_announcements_count,
            "voice-failures-count": self._voice_failures_count,
            "control-events-count": self._control_events_count,
            "questions-answered-count": self._questions_answered_count,
            "question-failures-count": self._question_failures_count,
            "speech-questions-count": self._speech_questions_count,
            "speech-recognition-failures-count": self._speech_recognition_failures_count,
            "push-to-talk-sessions-count": self._push_to_talk_sessions_count,
            "push-to-talk-failures-count": self._push_to_talk_failures_count,
            "push-to-talk-active": self.push_to_talk_buffer.active,
            "push-to-talk-buffer-bytes": self.push_to_talk_buffer.raw_audio_bytes,
            "push-to-talk-audio-source": (
                self.microphone_capture.provider if self.microphone_capture else _PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL
            ),
            "push-to-talk-microphone-active": (
                self.microphone_capture.active if self.microphone_capture else False
            ),
            "last-voice-result": self._last_voice_result,
            "last-question-result": self._last_question_result,
            "last-speech-recognition-result": self._last_speech_recognition_result,
            "enabled": self.enabled,
            "has-snapshot": self._last_snapshot is not None,
            "session-uid": self._session_uid,
            "session-generation": self._session_generation,
            "voice-queue-size": self.voice_queue.qsize(),
            "min-voice-interval-seconds": self.min_voice_interval_seconds,
            "trace-reference-laps": self.trace_recorder.reference_lap_count,
            "subscriber": self.subscriber.get_stats(),
        }

    def _runtime_status(self) -> tuple[str, str]:
        if not self.enabled:
            return "muted", "Race engineer muted"
        if self.push_to_talk_buffer.active:
            return "listening", "Push-to-talk recording"
        if self._active_voice_task is not None and not self._active_voice_task.done():
            return "speaking", "Speaking callout"
        voice_queue_size = self.voice_queue.qsize()
        if voice_queue_size:
            return "voice-queued", f"{voice_queue_size} voice callout(s) queued"
        if self._last_voice_result and not self._last_voice_result.get("ok", False):
            detail = str(self._last_voice_result.get("error") or "Voice output failed")
            return "voice-error", detail
        if self._last_speech_recognition_result and not self._last_speech_recognition_result.get("ok", False):
            detail = str(self._last_speech_recognition_result.get("error") or "Speech recognition failed")
            return "speech-error", detail
        if self._last_question_result and not self._last_question_result.get("ok", False):
            detail = str(self._last_question_result.get("error") or "Question answer failed")
            return "question-error", detail
        if self._last_snapshot is None:
            return "waiting-for-telemetry", "Waiting for race-table telemetry"
        return "online", "Race engineer online"

    def _init_routes(self) -> None:
        @self.subscriber.route("race-table-update")
        async def _handle_race_table_update(msg: Dict[str, Any]) -> None:
            self._reset_for_new_session_if_needed(_extract_session_uid(msg))
            self._last_snapshot = msg
            if not self.enabled:
                return
            announcements = self.announcer.process_snapshot(
                msg,
                focus=self.focus,
            )
            for announcement in announcements:
                self._queue_announcement(announcement)

        @self.subscriber.route("stream-overlay-update")
        async def _handle_stream_overlay_update(msg: Dict[str, Any]) -> None:
            self._reset_for_new_session_if_needed(_extract_session_uid(msg))
            if not self.enabled:
                return
            if self._using_backend_trace:
                return
            advice = self.trace_recorder.update_from_stream_overlay(msg)
            self._queue_trace_advice(advice)

        @self.subscriber.route("race-engineer-trace-update")
        async def _handle_race_engineer_trace_update(msg: Dict[str, Any]) -> None:
            self._reset_for_new_session_if_needed(_extract_session_uid(msg))
            if not self.enabled:
                return
            sample = sample_from_trace_update(msg)
            if sample is None:
                return
            self._using_backend_trace = True
            advice = self.trace_recorder.update_sample(sample)
            self._queue_trace_advice(advice)

        @self.subscriber.route("race-engineer-control")
        async def _handle_race_engineer_control(msg: Dict[str, Any]) -> None:
            self.handle_control_message(msg)

        @self.subscriber.route("race-engineer-question")
        async def _handle_race_engineer_question(msg: Dict[str, Any]) -> None:
            await self.handle_question_message(msg)

        @self.subscriber.route_raw("race-engineer-audio-question")
        async def _handle_race_engineer_audio_question(audio: bytes) -> None:
            await self.handle_audio_question(audio)

        @self.subscriber.route("race-engineer-ptt-control")
        async def _handle_race_engineer_ptt_control(msg: Dict[str, Any]) -> None:
            await self.handle_push_to_talk_control(msg)

        @self.subscriber.route_raw("race-engineer-ptt-audio")
        async def _handle_race_engineer_ptt_audio(audio: bytes) -> None:
            self.handle_push_to_talk_audio(audio)

    def handle_control_message(self, msg: Dict[str, Any]) -> bool:
        """Apply a runtime control message received from the backend or launcher."""

        if not isinstance(msg, dict):
            self.logger.warning("Ignored invalid race engineer control message: %r", msg)
            return False

        command = str(msg.get("command", "")).strip().lower().replace("-", "_")
        next_enabled: Optional[bool]
        if command == "toggle":
            next_enabled = not self.enabled
        elif command in {"enable", "enabled", "on", "unmute"}:
            next_enabled = True
        elif command in {"disable", "disabled", "off", "mute"}:
            next_enabled = False
        else:
            next_enabled = _bool_from_control_value(msg.get("enabled"))

        if next_enabled is None:
            self.logger.warning("Ignored unknown race engineer control command: %r", msg)
            return False

        changed = self.set_enabled(
            next_enabled,
            announce=bool(msg.get("announce", True)),
            source=str(msg.get("source", "control")),
        )
        if changed:
            self._control_events_count += 1
        return changed

    async def handle_question_message(self, msg: Dict[str, Any]) -> bool:
        """Answer a text question received from push-to-talk or another client."""

        if not isinstance(msg, dict):
            self.logger.warning("Ignored invalid race engineer question message: %r", msg)
            return False
        question = str(msg.get("question", "")).strip()
        source = str(msg.get("source", "question"))
        result = await self.ask_text_question(question, source=source)
        return result.ok

    async def handle_audio_question(self, audio: bytes, *, content_type: Optional[str] = None) -> bool:
        """Transcribe one audio question and answer it."""

        self._speech_questions_count += 1
        if not self.enabled:
            answer = await self.ask_text_question("", source="speech")
            return answer.ok
        if not self.speech_recognizer:
            self._speech_recognition_failures_count += 1
            self._last_speech_recognition_result = {
                "ok": False,
                "provider": "disabled",
                "error": "speech recognition is not configured",
                "text": "",
            }
            self._queue_system_announcement(
                "Speech recognition is not configured.",
                "race-engineer-speech-not-configured",
            )
            return False

        result = await self.speech_recognizer.transcribe(audio, content_type=content_type)
        self._record_speech_recognition_result(result)
        if not result.ok:
            self._queue_system_announcement("I did not catch that.", "race-engineer-speech-not-recognized")
            return False

        answer = await self.ask_text_question(result.text, source="speech")
        return answer.ok

    async def handle_push_to_talk_control(self, msg: Dict[str, Any]) -> bool:
        """Handle push-to-talk lifecycle commands."""

        if not isinstance(msg, dict):
            self.logger.warning("Ignored invalid push-to-talk control message: %r", msg)
            return False
        command = str(msg.get("command", "")).strip().lower().replace("-", "_")
        if command in {"start", "begin", "press"}:
            if not self.enabled:
                await self.ask_text_question("", source="push-to-talk")
                return False
            sample_rate_hz = _int_or_default(msg.get("sample_rate_hz") or msg.get("sample-rate-hz"), 16000)
            channels = _int_or_default(msg.get("channels"), 1)
            sample_width_bytes = _int_or_default(
                msg.get("sample_width_bytes") or msg.get("sample-width-bytes"),
                2,
            )
            self.push_to_talk_buffer.start(
                session_id=_safe_optional_text(msg.get("session_id") or msg.get("session-uid")),
                content_type=str(msg.get("content_type") or msg.get("content-type") or DEFAULT_AZURE_STT_CONTENT_TYPE),
                audio_format=str(msg.get("audio_format") or msg.get("audio-format") or "pcm16"),
                sample_rate_hz=sample_rate_hz,
                channels=channels,
                sample_width_bytes=sample_width_bytes,
            )
            try:
                self._start_microphone_capture_if_configured(
                    MicrophoneCaptureConfig(
                        sample_rate_hz=sample_rate_hz,
                        channels=channels,
                        sample_width_bytes=sample_width_bytes,
                        chunk_ms=_int_or_default(
                            msg.get("chunk_ms") or msg.get("chunk-ms"),
                            DEFAULT_MICROPHONE_CHUNK_MS,
                        ),
                    )
                )
            except (OSError, RuntimeError, ValueError) as exc:
                self.push_to_talk_buffer.cancel()
                self._push_to_talk_failures_count += 1
                self.logger.warning("Push-to-talk microphone failed to start: %s", exc)
                self._queue_system_announcement("Microphone unavailable.", "race-engineer-microphone-unavailable")
                return False
            self._push_to_talk_sessions_count += 1
            return True
        if command in {"stop", "end", "release"}:
            return await self.finish_push_to_talk()
        if command == "cancel":
            self._cancel_push_to_talk_recording()
            return True
        self.logger.warning("Ignored unknown push-to-talk command: %r", msg)
        return False

    def handle_push_to_talk_audio(self, audio: bytes) -> bool:
        """Append one push-to-talk audio chunk."""

        try:
            self.push_to_talk_buffer.append(audio)
        except (RuntimeError, ValueError) as exc:
            self._push_to_talk_failures_count += 1
            self.logger.warning("Push-to-talk audio chunk ignored: %s", exc)
            return False
        return True

    async def finish_push_to_talk(self) -> bool:
        """Stop recording and answer the buffered push-to-talk audio."""

        try:
            self._stop_microphone_capture_if_active()
        except (OSError, RuntimeError, ValueError) as exc:
            self._push_to_talk_failures_count += 1
            self.logger.warning("Push-to-talk microphone failed to stop: %s", exc)
        clip = self.push_to_talk_buffer.stop()
        if clip is None:
            self._push_to_talk_failures_count += 1
            self._queue_system_announcement("I did not hear anything.", "race-engineer-ptt-empty")
            return False
        return await self.handle_audio_question(clip.audio, content_type=clip.content_type)

    async def ask_text_question(self, question: str, *, source: str = "question") -> RaceEngineerAnswer:
        """Answer one text question and queue the spoken answer."""

        if not self.enabled:
            answer = RaceEngineerAnswer(
                ok=False,
                question=question,
                answer="Race engineer muted.",
                source=source,
                error="race engineer muted",
            )
            self._record_question_result(answer)
            self._queue_system_announcement(answer.answer, "race-engineer-muted-question")
            return answer

        answer = await self.conversation_agent.answer(
            question,
            telemetry_update=self._last_snapshot,
        )
        self._record_question_result(answer)
        self._queue_question_answer(answer, source=source)
        return answer

    def set_enabled(self, enabled: bool, *, announce: bool = True, source: str = "control") -> bool:
        """Enable or mute automatic race engineer callouts at runtime."""

        enabled = bool(enabled)
        if enabled == self.enabled:
            return False

        self.enabled = enabled
        self._last_voice_queued_at = None
        self.announcer.clear()
        self.trace_recorder.clear()
        self._using_backend_trace = False
        dropped = self.voice_queue.clear()
        if dropped:
            self._dropped_announcements_count += dropped
            self.logger.info("Dropped %d queued race engineer callouts after %s", dropped, source)

        if enabled:
            self.logger.info("Race engineer enabled by %s", source)
            if announce:
                self._queue_system_announcement("Race engineer online.", "race-engineer-online")
        else:
            self.logger.info("Race engineer muted by %s", source)
            self._cancel_active_voice("race engineer muted during playback")
            self._cancel_push_to_talk_recording()
            if announce:
                self._queue_system_announcement("Race engineer muted.", "race-engineer-muted")
        return True

    def queue_system_announcement(self, text: str, advice_id: str = "race-engineer-system") -> None:
        """Queue a short system callout from a management command."""

        text = str(text or "").strip()
        if not text:
            return
        self._queue_system_announcement(text, advice_id)

    def _start_microphone_capture_if_configured(self, config: MicrophoneCaptureConfig) -> None:
        if not self.microphone_capture:
            return
        self.microphone_capture.start(self.handle_push_to_talk_audio, config=config)

    def _stop_microphone_capture_if_active(self) -> None:
        if not self.microphone_capture or not self.microphone_capture.active:
            return
        self.microphone_capture.stop()

    def _cancel_push_to_talk_recording(self) -> None:
        if self.microphone_capture and self.microphone_capture.active:
            try:
                self.microphone_capture.stop()
            except (OSError, RuntimeError, ValueError) as exc:
                self.logger.warning("Push-to-talk microphone failed to cancel: %s", exc)
        self.push_to_talk_buffer.cancel()

    def _record_question_result(self, answer: RaceEngineerAnswer) -> None:
        if answer.ok:
            self._questions_answered_count += 1
        else:
            self._question_failures_count += 1
        self._last_question_result = {
            "ok": answer.ok,
            "question": answer.question,
            "answer": answer.answer,
            "source": answer.source,
            "focus": answer.focus,
            "error": answer.error,
            "metrics": answer.metrics or {},
        }

    def _record_speech_recognition_result(self, result: SpeechRecognitionResult) -> None:
        if not result.ok:
            self._speech_recognition_failures_count += 1
        self._last_speech_recognition_result = {
            "ok": result.ok,
            "provider": result.provider,
            "text": result.text,
            "error": result.error,
            "duration-ms": result.duration_ms,
            "confidence": result.confidence,
            "status": result.status,
        }

    def _reset_for_new_session_if_needed(self, session_uid: Optional[str]) -> None:
        if session_uid is None:
            return
        if self._session_uid is None:
            dropped = self.voice_queue.clear()
            if dropped:
                self._dropped_announcements_count += dropped
                self.logger.info("Dropped %d queued race engineer callouts after session initialization", dropped)
            self._session_uid = session_uid
            self._session_generation += 1
            self._last_voice_queued_at = None
            self._cancel_active_voice("session changed during playback")
            return
        if session_uid == self._session_uid:
            return

        dropped = self.voice_queue.clear()
        if dropped:
            self._dropped_announcements_count += dropped
            self.logger.info("Dropped %d queued race engineer callouts after session change", dropped)
        self._session_uid = session_uid
        self._session_generation += 1
        self._last_snapshot = None
        self._using_backend_trace = False
        self._last_voice_queued_at = None
        self._cancel_active_voice("session changed during playback")
        self.announcer.clear()
        self.trace_recorder.clear()

    def _queue_trace_advice(self, advice: List[Dict[str, Any]]) -> None:
        announcements = self.announcer.process_advice_items(
            advice,
            focus=self.focus,
        )
        for announcement in announcements:
            self._queue_announcement(announcement)

    def _queue_announcement(self, announcement: Any, *, bypass_rate_limit: bool = False) -> None:
        announcement = self._tag_announcement(announcement)
        priority_rank = _voice_priority_rank(getattr(announcement, "priority", None))
        is_critical = priority_rank == _VOICE_PRIORITY_RANK["critical"]
        queued_at = self._monotonic_clock()

        if not is_critical and not bypass_rate_limit and self._is_voice_rate_limited(queued_at):
            self._dropped_announcements_count += 1
            self._rate_limited_announcements_count += 1
            self.logger.debug("Dropped race engineer callout inside global voice interval")
            return

        if is_critical:
            dropped_lower_priority = self.voice_queue.drop_matching(
                lambda queued: _voice_priority_rank(getattr(queued, "priority", None)) > _VOICE_PRIORITY_RANK["critical"],
            )
            if dropped_lower_priority:
                self._dropped_announcements_count += dropped_lower_priority
                self.logger.info("Dropped %d lower-priority callouts before queueing critical advice",
                                 dropped_lower_priority)

        push_result = self.voice_queue.push(announcement)
        if push_result.dropped_oldest:
            self._dropped_announcements_count += 1
            self.logger.debug("Dropped stale race engineer callout before queueing latest")
        if not push_result.enqueued:
            self._dropped_announcements_count += 1
            self.logger.warning("Race engineer voice queue is full; dropping callout")
            return
        self._last_voice_queued_at = queued_at

    def _tag_announcement(self, announcement: Any) -> Any:
        if isinstance(announcement, RaceEngineerAnnouncement):
            return replace(announcement, session_generation=self._session_generation)
        return announcement

    def _is_voice_rate_limited(self, now: float) -> bool:
        if self.min_voice_interval_seconds <= 0:
            return False
        if self._last_voice_queued_at is None:
            return False
        return (now - self._last_voice_queued_at) < self.min_voice_interval_seconds

    def _is_obsolete_announcement(self, announcement: Any) -> bool:
        generation = getattr(announcement, "session_generation", self._session_generation)
        return generation != self._session_generation

    def _queue_system_announcement(self, text: str, advice_id: str) -> None:
        self._queue_announcement(
            RaceEngineerAnnouncement(
                text=text,
                priority="info",
                category="system",
                cooldown_key=f"system:{advice_id}",
                advice_id=advice_id,
                evidence=["runtime control command"],
                metrics={"enabled": self.enabled},
            ),
            bypass_rate_limit=True,
        )

    def _queue_question_answer(self, answer: RaceEngineerAnswer, *, source: str) -> None:
        self._queue_announcement(
            RaceEngineerAnnouncement(
                text=answer.answer,
                priority="info",
                category="system",
                cooldown_key=f"question:{answer.focus}:{self._questions_answered_count + self._question_failures_count}",
                advice_id="race-engineer-question-answer" if answer.ok else "race-engineer-question-error",
                evidence=[
                    f"source={source}",
                    f"focus={answer.focus}",
                ],
                metrics={
                    "ok": answer.ok,
                    "focus": answer.focus,
                    **(answer.metrics or {}),
                },
            ),
            bypass_rate_limit=True,
        )

    def _cancel_active_voice(self, reason: str) -> None:
        task = self._active_voice_task
        if task and not task.done():
            self._active_voice_cancel_reason = reason
            task.cancel()

    async def _voice_worker(self) -> None:
        while True:
            announcement = await self.voice_queue.get()
            try:
                if self._is_obsolete_announcement(announcement):
                    self._record_aborted_announcement(announcement, "session changed before playback")
                    continue

                active_voice_task = asyncio.create_task(
                    self._speak_announcement(announcement),
                    name="race-engineer-active-voice",
                )
                self._active_voice_task = active_voice_task
                try:
                    await active_voice_task
                except asyncio.CancelledError:
                    if asyncio.current_task() and asyncio.current_task().cancelling():
                        raise
                    self._record_aborted_announcement(announcement, self._active_voice_cancel_reason)
                finally:
                    self._active_voice_cancel_reason = "voice playback cancelled"
                    if self._active_voice_task is active_voice_task:
                        self._active_voice_task = None
            finally:
                self.voice_queue.task_done()

    async def _speak_announcement(self, announcement: Any) -> None:
        if self._is_obsolete_announcement(announcement):
            self._record_aborted_announcement(announcement, "session changed before playback")
            return
        try:
            result = await self.voice_engine.speak(
                announcement.text,
                metadata={
                    "priority": announcement.priority,
                    "category": announcement.category,
                    "cooldown_key": announcement.cooldown_key,
                    "advice_id": announcement.advice_id,
                    "evidence": announcement.evidence,
                    "metrics": announcement.metrics,
                    "session_generation": getattr(announcement, "session_generation", None),
                },
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            result = VoiceResult(
                ok=False,
                provider=getattr(self.voice_engine, "provider", "unknown"),
                text=getattr(announcement, "text", ""),
                error=str(exc),
            )
        if self._is_obsolete_announcement(announcement):
            self._record_aborted_announcement(announcement, "session changed during playback")
            return
        if result.ok:
            self._announcements_count += 1
        else:
            self._voice_failures_count += 1
            self.logger.warning("Voice engine failed: %s", result.error)
        self._last_voice_result = {
            "ok": result.ok,
            "provider": result.provider,
            "error": result.error,
            "duration-ms": result.duration_ms,
            "audio-bytes": result.audio_bytes,
            "priority": announcement.priority,
            "category": announcement.category,
            "advice-id": announcement.advice_id,
            "cooldown-key": announcement.cooldown_key,
            "session-generation": getattr(announcement, "session_generation", None),
        }

    def _record_aborted_announcement(self, announcement: Any, reason: str) -> None:
        self._aborted_announcements_count += 1
        self._dropped_announcements_count += 1
        self._last_voice_result = {
            "ok": False,
            "provider": getattr(self.voice_engine, "provider", "unknown"),
            "error": reason,
            "duration-ms": None,
            "audio-bytes": None,
            "priority": getattr(announcement, "priority", None),
            "category": getattr(announcement, "category", None),
            "advice-id": getattr(announcement, "advice_id", None),
            "cooldown-key": getattr(announcement, "cooldown_key", None),
            "session-generation": getattr(announcement, "session_generation", None),
        }

    async def _stop_voice_worker(self) -> None:
        self._cancel_push_to_talk_recording()
        if not self._voice_task:
            return
        self._voice_task.cancel()
        try:
            await self._voice_task
        except asyncio.CancelledError:
            pass
        if self._active_voice_task and not self._active_voice_task.done():
            self._active_voice_task.cancel()
        self._voice_task = None


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Race Engineer")
    parser.add_argument("--config-file", nargs="?", default="png_config.json", help="Configuration file name")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--managed", action="store_true", help="Indicates if process is managed by parent")
    parser.add_argument("--log-file", type=str, default="png_race_engineer.log", help="Log file name")
    parser.add_argument("--wd", type=str, default=None, help="Working directory")
    parser.add_argument(
        "--profile-check",
        action="store_true",
        help="Check the launcher race_engineer_profile.json and exit without telemetry or audio",
    )
    parser.add_argument(
        "--profile-file",
        type=str,
        default=_env("PNG_RACE_ENGINEER_PROFILE_FILE", ""),
        help="Optional race engineer launch profile path for profile smoke commands",
    )
    parser.add_argument(
        "--profile-voice-test",
        nargs="?",
        const="Race engineer online.",
        default=None,
        help="Speak one test message using the saved launcher profile and exit without telemetry",
    )
    parser.add_argument(
        "--profile-question-test",
        nargs="?",
        const="what should I know?",
        default=None,
        help="Ask one text question using the saved launcher profile and exit without telemetry",
    )
    parser.add_argument(
        "--profile-audio-question-test",
        type=str,
        default="",
        help="Transcribe one audio file, answer it, and speak the answer using the saved launcher profile",
    )
    parser.add_argument(
        "--profile-mic-question-test-seconds",
        type=float,
        default=0.0,
        help="Record the configured push-to-talk microphone for N seconds, answer it, and speak the answer",
    )
    parser.add_argument(
        "--profile-preflight",
        action="store_true",
        help="Run launcher profile diagnostics, voice, and question smoke tests, then exit",
    )
    parser.add_argument(
        "--profile-preflight-question",
        type=str,
        default=_DEFAULT_PROFILE_PREFLIGHT_QUESTION,
        help="Question to ask during --profile-preflight",
    )
    parser.add_argument("--focus", type=str, default=_env("PNG_RACE_ENGINEER_FOCUS", "all"),
                        help="Advice focus category")
    parser.add_argument("--min-priority", type=str, default=_env("PNG_RACE_ENGINEER_MIN_PRIORITY", "advisory"),
                        help="Minimum priority to announce")
    parser.add_argument("--cooldown-seconds", type=int, default=_env_int("PNG_RACE_ENGINEER_COOLDOWN_SECONDS", 20),
                        help="Cooldown per message key")
    parser.add_argument("--max-items", type=int, default=_env_int("PNG_RACE_ENGINEER_MAX_ITEMS", 5),
                        help="Maximum advice items per snapshot")
    parser.add_argument("--max-queue-size", type=int, default=_env_int("PNG_RACE_ENGINEER_MAX_QUEUE_SIZE", 3),
                        help="Maximum queued voice callouts")
    parser.add_argument(
        "--min-voice-interval-seconds",
        type=float,
        default=_env_float("PNG_RACE_ENGINEER_MIN_VOICE_INTERVAL_SECONDS", 4.0),
        help="Minimum interval between non-critical queued voice callouts",
    )
    parser.add_argument(
        "--initial-enabled",
        type=_arg_bool,
        default=_env_bool("PNG_RACE_ENGINEER_INITIAL_ENABLED", True),
        help="Whether the race engineer starts online or muted",
    )
    parser.add_argument(
        "--voice-provider",
        type=str,
        default=_env("PNG_RACE_ENGINEER_VOICE_PROVIDER", "dry_run"),
        help="Voice provider: dry_run, azure, or disabled",
    )
    parser.add_argument(
        "--speech-recognition-provider",
        type=str,
        default=_env("PNG_RACE_ENGINEER_SPEECH_RECOGNITION_PROVIDER", "disabled"),
        help="Speech recognition provider: azure or disabled",
    )
    parser.add_argument("--azure-region", type=str, default=_env("PNG_AZURE_SPEECH_REGION", ""),
                        help="Azure Speech region, for example eastus")
    parser.add_argument("--azure-speech-endpoint", type=str, default=_env("PNG_AZURE_SPEECH_ENDPOINT", ""),
                        help="Azure Speech endpoint, for example https://francecentral.api.cognitive.microsoft.com/")
    parser.add_argument(
        "--azure-voice",
        type=str,
        default=_env("PNG_AZURE_SPEECH_VOICE", DEFAULT_AZURE_SPEECH_VOICE),
        help="Azure Speech voice name",
    )
    parser.add_argument(
        "--azure-key-env-var",
        type=str,
        default=_env("PNG_AZURE_SPEECH_KEY_ENV_VAR", DEFAULT_AZURE_SPEECH_KEY_ENV_VAR),
        help="Environment variable containing the Azure Speech key",
    )
    parser.add_argument(
        "--azure-output-format",
        type=str,
        default=_env("PNG_AZURE_SPEECH_OUTPUT_FORMAT", DEFAULT_AZURE_SPEECH_OUTPUT_FORMAT),
        help="Azure Speech output format",
    )
    parser.add_argument(
        "--azure-stt-language",
        type=str,
        default=_env("PNG_AZURE_STT_LANGUAGE", DEFAULT_AZURE_STT_LANGUAGE),
        help="Azure Speech-to-Text language, for example ru-RU or en-US",
    )
    parser.add_argument(
        "--azure-stt-format",
        type=str,
        default=_env("PNG_AZURE_STT_FORMAT", DEFAULT_AZURE_STT_FORMAT),
        help="Azure Speech-to-Text result format: simple or detailed",
    )
    parser.add_argument(
        "--azure-stt-content-type",
        type=str,
        default=_env("PNG_AZURE_STT_CONTENT_TYPE", DEFAULT_AZURE_STT_CONTENT_TYPE),
        help="Content-Type for push-to-talk audio sent to Azure Speech-to-Text",
    )
    parser.add_argument(
        "--push-to-talk-audio-source",
        type=str,
        default=_env("PNG_RACE_ENGINEER_PUSH_TO_TALK_AUDIO_SOURCE", _PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL),
        help="Push-to-talk audio source: external or windows_microphone",
    )
    parser.add_argument(
        "--agent-prompts-file",
        type=str,
        default=_env(DEFAULT_AGENT_PROMPTS_FILE_ENV_VAR, ""),
        help="Optional JSON file with race engineer prompt overrides by category",
    )
    parser.add_argument(
        "--write-agent-prompts-template",
        type=str,
        default="",
        help="Write an editable category prompt template JSON and exit",
    )
    parser.add_argument(
        "--overwrite-agent-prompts-template",
        action="store_true",
        help="Allow --write-agent-prompts-template to overwrite an existing file",
    )
    parser.add_argument(
        "--conversation-provider",
        type=str,
        default=_env("PNG_RACE_ENGINEER_CONVERSATION_PROVIDER", _CONVERSATION_PROVIDER_LOCAL),
        help="Question answer provider: local_brief, http, or codex_cli",
    )
    parser.add_argument(
        "--conversation-endpoint",
        type=str,
        default=_env("PNG_RACE_ENGINEER_CONVERSATION_ENDPOINT", ""),
        help="HTTP endpoint for a Codex-compatible race engineer answer provider",
    )
    parser.add_argument(
        "--conversation-key-env-var",
        type=str,
        default=_env("PNG_RACE_ENGINEER_CONVERSATION_KEY_ENV_VAR", ""),
        help="Optional environment variable containing a bearer token for the conversation endpoint",
    )
    parser.add_argument(
        "--conversation-command",
        type=str,
        default=_env("PNG_RACE_ENGINEER_CONVERSATION_COMMAND", ""),
        help="Local Codex CLI compatible command that reads a prompt JSON from stdin",
    )
    parser.add_argument(
        "--conversation-timeout-seconds",
        type=float,
        default=_env_float("PNG_RACE_ENGINEER_CONVERSATION_TIMEOUT_SECONDS", 10.0),
        help="Timeout for the HTTP conversation provider",
    )
    parser.add_argument(
        "--no-audio-playback",
        action="store_true",
        help="Request Azure audio but discard it instead of playing it locally",
    )
    parser.add_argument(
        "--voice-test",
        nargs="?",
        const="Race engineer online.",
        default=None,
        help="Speak one test message and exit without connecting to telemetry",
    )
    parser.add_argument(
        "--question-test",
        nargs="?",
        const="what should I know?",
        default=None,
        help="Ask one text question and exit without connecting to live telemetry",
    )
    parser.add_argument(
        "--question-snapshot",
        type=str,
        default="",
        help="Optional race-table-update JSON file for --question-test; uses sample telemetry when omitted",
    )
    return parser.parse_args(argv)


def build_voice_engine(args: argparse.Namespace, logger: logging.Logger) -> VoiceEngine:
    """Build the requested voice engine from CLI arguments."""

    provider = _normalise_voice_provider(getattr(args, "voice_provider", "dry_run"))
    if provider == "disabled":
        return NullVoiceEngine()
    if provider == "azure":
        return _build_azure_voice_engine(args, logger)
    return DryRunVoiceEngine(logger=logger)


def build_speech_recognizer(args: argparse.Namespace) -> Optional[SpeechRecognizer]:
    """Build the requested speech recognition provider from CLI arguments."""

    provider = _normalise_speech_recognition_provider(
        getattr(args, "speech_recognition_provider", "disabled")
    )
    if provider == "azure":
        return AzureSpeechRecognizer(
            AzureSpeechRecognitionConfig(
                region=getattr(args, "azure_region", ""),
                endpoint=getattr(args, "azure_speech_endpoint", "") or None,
                key_env_var=getattr(args, "azure_key_env_var", DEFAULT_AZURE_SPEECH_KEY_ENV_VAR),
                language=getattr(args, "azure_stt_language", DEFAULT_AZURE_STT_LANGUAGE),
                result_format=getattr(args, "azure_stt_format", DEFAULT_AZURE_STT_FORMAT),
                content_type=getattr(args, "azure_stt_content_type", DEFAULT_AZURE_STT_CONTENT_TYPE),
            )
        )
    return None


def build_microphone_capture(
        args: argparse.Namespace,
        logger: logging.Logger) -> Optional[PushToTalkMicrophoneCapture]:
    """Build the requested push-to-talk microphone capture backend."""

    audio_source = _normalise_push_to_talk_audio_source(
        getattr(args, "push_to_talk_audio_source", _PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL)
    )
    if audio_source == _PUSH_TO_TALK_AUDIO_SOURCE_WINDOWS_MICROPHONE:
        if sys.platform != "win32":
            logger.warning("Windows microphone capture is not available on this platform")
            return None
        return WindowsWaveInMicrophoneCapture(logger=logger)
    return None


def build_agent_prompt_overrides(
        args: argparse.Namespace,
        logger: logging.Logger) -> Dict[str, Dict[str, str]]:
    """Load optional agent prompt overrides for the conversation provider."""

    path = str(getattr(args, "agent_prompts_file", "") or "").strip()
    if not path:
        return {}
    try:
        overrides = load_agent_prompt_overrides(path)
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring race engineer agent prompt overrides file %s: %s", path, exc)
        return {}
    logger.info("Loaded race engineer agent prompt overrides from %s", path)
    return overrides


def build_conversation_agent(
        args: argparse.Namespace,
        logger: logging.Logger,
        agent_prompt_overrides: Dict[str, Dict[str, str]]) -> RaceEngineerConversationAgent:
    """Build the requested question-answer provider."""

    local_agent = LocalBriefConversationAgent(agent_prompt_overrides=agent_prompt_overrides)
    provider = _normalise_conversation_provider(
        getattr(args, "conversation_provider", _CONVERSATION_PROVIDER_LOCAL)
    )
    if provider == _CONVERSATION_PROVIDER_CODEX_CLI:
        command = str(getattr(args, "conversation_command", "") or "").strip()
        if not command:
            logger.warning("Codex CLI conversation provider requested but no command was configured; using local brief")
            return local_agent
        cli_agent = CodexCliConversationAgent(
            CodexCliConversationConfig(
                command=command,
                timeout_seconds=max(0.1, float(getattr(args, "conversation_timeout_seconds", 10.0) or 10.0)),
                provider_name="codex_cli",
            ),
            agent_prompt_overrides=agent_prompt_overrides,
        )
        return FallbackConversationAgent(cli_agent, local_agent)

    if provider != _CONVERSATION_PROVIDER_HTTP:
        return local_agent

    endpoint = str(getattr(args, "conversation_endpoint", "") or "").strip()
    if not endpoint:
        logger.warning("HTTP conversation provider requested but no endpoint was configured; using local brief")
        return local_agent

    http_agent = HttpConversationAgent(
        HttpConversationConfig(
            endpoint=endpoint,
            key_env_var=str(getattr(args, "conversation_key_env_var", "") or "").strip(),
            timeout_seconds=max(0.1, float(getattr(args, "conversation_timeout_seconds", 10.0) or 10.0)),
            provider_name="external_http",
        ),
        agent_prompt_overrides=agent_prompt_overrides,
    )
    return FallbackConversationAgent(http_agent, local_agent)


async def main(args: argparse.Namespace) -> None:
    if args.wd:
        os.chdir(args.wd)

    if getattr(args, "profile_check", False):
        if not run_profile_check(args):
            raise SystemExit(2)
        return
    if getattr(args, "write_agent_prompts_template", ""):
        run_write_agent_prompts_template(args)
        return

    logger = get_logger(
        "race_engineer",
        args.debug,
        jsonl=bool(args.managed),
        file_path=None if args.managed else args.log_file,
    )
    if getattr(args, "profile_preflight", False):
        summary = await run_profile_preflight(args, logger)
        if not summary.get("ok", False):
            raise SystemExit(2)
        return
    if getattr(args, "profile_audio_question_test", ""):
        summary = await run_profile_audio_question_test(args, logger)
        if not summary.get("ok", False):
            raise RuntimeError(summary.get("error") or "Race engineer profile audio question test failed")
        return
    if float(getattr(args, "profile_mic_question_test_seconds", 0.0) or 0.0) > 0.0:
        summary = await run_profile_mic_question_test(args, logger)
        if not summary.get("ok", False):
            raise RuntimeError(summary.get("error") or "Race engineer profile microphone question test failed")
        return
    if getattr(args, "profile_voice_test", None) is not None:
        result = await run_profile_voice_test(args, logger)
        if not result.ok:
            raise RuntimeError(result.error or "Race engineer profile voice test failed")
        return
    if getattr(args, "profile_question_test", None) is not None:
        answer = await run_profile_question_test(args, logger)
        if not answer.ok:
            raise RuntimeError(answer.error or "Race engineer profile question test failed")
        return

    agent_prompt_overrides = build_agent_prompt_overrides(args, logger)
    conversation_agent = build_conversation_agent(args, logger, agent_prompt_overrides)
    if getattr(args, "question_test", None) is not None:
        answer = await run_question_test(
            conversation_agent,
            logger,
            args.question_test,
            snapshot_path=getattr(args, "question_snapshot", ""),
        )
        if not answer.ok:
            raise RuntimeError(answer.error or "Race engineer question test failed")
        return

    voice_engine = build_voice_engine(args, logger)
    speech_recognizer = build_speech_recognizer(args)
    microphone_capture = build_microphone_capture(args, logger)
    if getattr(args, "voice_test", None) is not None:
        result = await run_voice_test(voice_engine, logger, args.voice_test)
        if not result.ok:
            raise RuntimeError(result.error or "Race engineer voice test failed")
        return

    from lib.config import load_config_from_json
    from .mgmt import init_ipc_task

    settings = load_config_from_json(args.config_file, logger, fail_if_missing=True)
    app = RaceEngineerApp(
        logger=logger,
        broker_xpub_port=settings.Network.broker_xpub_port,
        voice_engine=voice_engine,
        min_priority=args.min_priority,
        cooldown_seconds=args.cooldown_seconds,
        max_items=args.max_items,
        max_queue_size=args.max_queue_size,
        focus=args.focus,
        min_voice_interval_seconds=args.min_voice_interval_seconds,
        initial_enabled=args.initial_enabled,
        conversation_agent=conversation_agent,
        speech_recognizer=speech_recognizer,
        microphone_capture=microphone_capture,
    )
    tasks: List[asyncio.Task] = []

    logger.info("Starting %s race engineer, version %s", APP_NAME, get_version())
    app_task = asyncio.create_task(app.run(), name="Race Engineer Subscriber")
    tasks.append(app_task)
    if args.managed:
        logger.debug("Managed mode enabled")
        init_ipc_task(logger, app, tasks)
        notify_parent_init_complete()

    try:
        await asyncio.gather(*tasks)
    finally:
        app.close()


def entry_point() -> None:
    args = parse_args()
    if args.managed and not getattr(args, "profile_check", False):
        report_pid_from_child()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        sys.exit(0)


def run_profile_check(args: argparse.Namespace) -> bool:
    """Run offline race engineer profile diagnostics and print a concise report."""

    profile_path = str(getattr(args, "profile_file", "") or "").strip() or None
    try:
        profile = load_race_engineer_launch_profile(profile_path)
    except (OSError, ValueError) as exc:
        print(f"Error: Failed to load Race Engineer profile: {exc}")
        return False

    diagnostics = diagnose_race_engineer_launch_profile(profile)
    print(format_race_engineer_profile_diagnostics(diagnostics))
    return not race_engineer_profile_has_errors(diagnostics)


def run_write_agent_prompts_template(args: argparse.Namespace) -> str:
    """Write an editable race engineer prompt override template."""

    path = save_agent_prompt_override_template(
        getattr(args, "write_agent_prompts_template", ""),
        overwrite=bool(getattr(args, "overwrite_agent_prompts_template", False)),
    )
    print(f"Wrote Race Engineer agent prompt template: {path}")
    return path


async def run_profile_voice_test(
    args: argparse.Namespace,
    logger: logging.Logger,
) -> VoiceResult:
    """Speak one test callout using the launcher race engineer profile."""

    profile_path = str(getattr(args, "profile_file", "") or "").strip() or None
    profile = load_race_engineer_launch_profile(profile_path)
    profile_args = parse_args([
        *race_engineer_launch_profile_to_cli_args(profile),
        "--voice-test",
        str(getattr(args, "profile_voice_test", "") or "Race engineer online."),
    ])
    profile_args.debug = bool(getattr(args, "debug", False))
    profile_args.managed = bool(getattr(args, "managed", False))
    profile_args.log_file = str(getattr(args, "log_file", profile_args.log_file) or profile_args.log_file)
    profile_args.profile_file = str(getattr(args, "profile_file", "") or "")

    voice_engine = build_voice_engine(profile_args, logger)
    return await run_voice_test(voice_engine, logger, profile_args.voice_test)


async def run_profile_question_test(
    args: argparse.Namespace,
    logger: logging.Logger,
    *,
    print_result: bool = True,
) -> RaceEngineerAnswer:
    """Answer one test question using the launcher race engineer profile."""

    profile_path = str(getattr(args, "profile_file", "") or "").strip() or None
    profile = load_race_engineer_launch_profile(profile_path)
    profile_args = parse_args([
        *race_engineer_launch_profile_to_cli_args(profile),
        "--question-test",
        str(getattr(args, "profile_question_test", "") or "what should I know?"),
    ])
    profile_args.debug = bool(getattr(args, "debug", False))
    profile_args.managed = bool(getattr(args, "managed", False))
    profile_args.log_file = str(getattr(args, "log_file", profile_args.log_file) or profile_args.log_file)
    profile_args.profile_file = str(getattr(args, "profile_file", "") or "")
    profile_args.question_snapshot = str(getattr(args, "question_snapshot", "") or "")

    agent_prompt_overrides = build_agent_prompt_overrides(profile_args, logger)
    conversation_agent = build_conversation_agent(profile_args, logger, agent_prompt_overrides)
    return await run_question_test(
        conversation_agent,
        logger,
        profile_args.question_test,
        snapshot_path=profile_args.question_snapshot,
        print_result=print_result,
    )


async def run_profile_preflight(
    args: argparse.Namespace,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """Run profile diagnostics plus voice and question smoke tests."""

    profile_path = str(getattr(args, "profile_file", "") or "").strip() or None
    try:
        profile = load_race_engineer_launch_profile(profile_path)
    except (OSError, ValueError) as exc:
        summary = {
            "ok": False,
            "diagnostics": [{
                "severity": "error",
                "code": "profile-load-failed",
                "message": f"Failed to load Race Engineer profile: {exc}",
            }],
            "voice": {"ok": False, "skipped": True, "error": "profile load failed"},
            "question": {"ok": False, "skipped": True, "error": "profile load failed"},
            "push_to_talk": {"ok": False, "skipped": True, "error": "profile load failed"},
            "next_steps": [
                "Open Race Engineer settings, save a valid profile, then run Preflight again.",
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    diagnostics = diagnose_race_engineer_launch_profile(profile)
    diagnostic_payload = [_profile_diagnostic_to_dict(item) for item in diagnostics]
    has_diagnostic_errors = race_engineer_profile_has_errors(diagnostics)
    voice_errors = [
        item for item in diagnostics
        if item.severity == "error" and item.code.startswith("azure-tts")
    ]
    question_errors = [
        item for item in diagnostics
        if item.severity == "error"
        and (item.code.startswith("conversation-") or item.code == "agent-prompts-file-missing")
    ]

    if voice_errors:
        voice_payload: Dict[str, Any] = {
            "ok": False,
            "skipped": True,
            "error": format_race_engineer_profile_diagnostics(voice_errors),
        }
    else:
        try:
            voice_result = await run_profile_voice_test(args, logger)
            voice_payload = _voice_result_to_dict(voice_result)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Race engineer profile preflight voice test failed: %s", exc)
            voice_payload = {"ok": False, "skipped": False, "error": str(exc)}

    if question_errors:
        question_payload: Dict[str, Any] = {
            "ok": False,
            "skipped": True,
            "error": format_race_engineer_profile_diagnostics(question_errors),
        }
    else:
        try:
            question_args = argparse.Namespace(**vars(args))
            question_args.profile_question_test = str(
                getattr(args, "profile_preflight_question", "") or _DEFAULT_PROFILE_PREFLIGHT_QUESTION
            )
            answer = await run_profile_question_test(question_args, logger, print_result=False)
            question_payload = _answer_to_dict(answer)
            question_payload["skipped"] = False
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Race engineer profile preflight question test failed: %s", exc)
            question_payload = {"ok": False, "skipped": False, "error": str(exc)}

    push_to_talk_payload = _preflight_push_to_talk_payload(profile, diagnostics)
    next_steps = _preflight_next_steps(
        profile,
        diagnostics,
        voice_payload,
        question_payload,
        push_to_talk_payload,
    )
    summary = {
        "ok": (
            not has_diagnostic_errors
            and bool(voice_payload.get("ok", False))
            and bool(question_payload.get("ok", False))
            and bool(push_to_talk_payload.get("ok", False))
        ),
        "diagnostics": diagnostic_payload,
        "voice": voice_payload,
        "question": question_payload,
        "push_to_talk": push_to_talk_payload,
        "next_steps": next_steps,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


async def run_profile_audio_question_test(
    args: argparse.Namespace,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """Transcribe, answer, and speak one audio question using the launcher profile."""

    audio_path = str(getattr(args, "profile_audio_question_test", "") or "").strip()
    if not audio_path:
        summary = {
            "ok": False,
            "error": "audio file is required",
            "speech": {"ok": False, "error": "audio file is required"},
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    try:
        with open(audio_path, "rb") as file_obj:
            audio = file_obj.read()
    except OSError as exc:
        summary = {
            "ok": False,
            "error": f"failed to read audio file: {exc}",
            "audio": {"path": audio_path, "bytes": 0},
            "speech": {"ok": False, "error": str(exc)},
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    profile_args = _profile_args_for_smoke_test(args)
    summary = await _run_profile_audio_question_pipeline(
        profile_args,
        logger,
        audio,
        audio_payload={"path": audio_path, "bytes": len(audio)},
        content_type=getattr(profile_args, "azure_stt_content_type", DEFAULT_AZURE_STT_CONTENT_TYPE),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


async def run_profile_mic_question_test(
    args: argparse.Namespace,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """Record the configured microphone, answer the question, and speak the answer."""

    seconds = max(0.1, float(getattr(args, "profile_mic_question_test_seconds", 0.0) or 0.0))
    profile_args = _profile_args_for_smoke_test(args)
    microphone_capture = build_microphone_capture(profile_args, logger)
    if microphone_capture is None:
        summary = {
            "ok": False,
            "error": "push-to-talk microphone capture is not configured",
            "audio": {"source": "microphone", "seconds": seconds, "bytes": 0},
            "speech": {"ok": False, "skipped": True},
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    audio_buffer = PushToTalkAudioBuffer()
    config = MicrophoneCaptureConfig()
    audio_buffer.start(
        session_id="profile-mic-question-test",
        content_type=getattr(profile_args, "azure_stt_content_type", DEFAULT_AZURE_STT_CONTENT_TYPE),
        audio_format="pcm16",
        sample_rate_hz=config.sample_rate_hz,
        channels=config.channels,
        sample_width_bytes=config.sample_width_bytes,
    )
    started_at = time.monotonic()
    try:
        microphone_capture.start(audio_buffer.append, config=config)
        await asyncio.sleep(seconds)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        try:
            _stop_microphone_capture_for_test(microphone_capture)
        except Exception as stop_exc:  # pylint: disable=broad-exception-caught
            logger.warning("Race engineer microphone test stop after failure also failed: %s", stop_exc)
        audio_buffer.cancel()
        summary = {
            "ok": False,
            "error": f"microphone recording failed: {exc}",
            "audio": {"source": "microphone", "seconds": seconds, "bytes": 0},
            "speech": {"ok": False, "skipped": True},
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    try:
        _stop_microphone_capture_for_test(microphone_capture)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        audio_buffer.cancel()
        summary = {
            "ok": False,
            "error": f"microphone recording failed to stop: {exc}",
            "audio": {"source": "microphone", "seconds": seconds, "bytes": 0},
            "speech": {"ok": False, "skipped": True},
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    clip = audio_buffer.stop()
    elapsed_seconds = round(time.monotonic() - started_at, 3)
    if clip is None:
        summary = {
            "ok": False,
            "error": "microphone recording was empty",
            "audio": {"source": "microphone", "seconds": elapsed_seconds, "bytes": 0},
            "speech": {"ok": False, "skipped": True},
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    summary = await _run_profile_audio_question_pipeline(
        profile_args,
        logger,
        clip.audio,
        audio_payload={
            "source": "microphone",
            "seconds": elapsed_seconds,
            "bytes": len(clip.audio),
            "raw_bytes": clip.raw_audio_bytes,
            "chunks": clip.chunk_count,
            "provider": microphone_capture.provider,
        },
        content_type=clip.content_type,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


async def _run_profile_audio_question_pipeline(
    profile_args: argparse.Namespace,
    logger: logging.Logger,
    audio: bytes,
    *,
    audio_payload: Dict[str, Any],
    content_type: Optional[str],
) -> Dict[str, Any]:
    """Run speech-to-text, answer, and voice output for one audio question."""

    speech_recognizer = build_speech_recognizer(profile_args)
    if speech_recognizer is None:
        speech_payload = {
            "ok": False,
            "provider": "disabled",
            "error": "speech recognition is not configured",
        }
        summary = {
            "ok": False,
            "error": speech_payload["error"],
            "audio": audio_payload,
            "speech": speech_payload,
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        return summary

    speech_result = await speech_recognizer.transcribe(
        audio,
        content_type=content_type,
    )
    speech_payload = _speech_result_to_dict(speech_result)
    if not speech_result.ok:
        summary = {
            "ok": False,
            "error": speech_result.error or "speech recognition failed",
            "audio": audio_payload,
            "speech": speech_payload,
            "question": {"ok": False, "skipped": True},
            "voice": {"ok": False, "skipped": True},
        }
        return summary

    agent_prompt_overrides = build_agent_prompt_overrides(profile_args, logger)
    conversation_agent = build_conversation_agent(profile_args, logger, agent_prompt_overrides)
    answer = await run_question_test(
        conversation_agent,
        logger,
        speech_result.text,
        snapshot_path=profile_args.question_snapshot,
        print_result=False,
    )
    question_payload = _answer_to_dict(answer)
    if not answer.ok:
        summary = {
            "ok": False,
            "error": answer.error or "question answer failed",
            "audio": audio_payload,
            "speech": speech_payload,
            "question": question_payload,
            "voice": {"ok": False, "skipped": True},
        }
        return summary

    voice_engine = build_voice_engine(profile_args, logger)
    voice_result = await run_voice_test(voice_engine, logger, answer.answer)
    voice_payload = _voice_result_to_dict(voice_result)
    summary = {
        "ok": bool(voice_result.ok),
        "error": None if voice_result.ok else voice_result.error,
        "audio": audio_payload,
        "speech": speech_payload,
        "question": question_payload,
        "voice": voice_payload,
    }
    return summary


def _profile_args_for_smoke_test(args: argparse.Namespace) -> argparse.Namespace:
    profile_path = str(getattr(args, "profile_file", "") or "").strip() or None
    profile = load_race_engineer_launch_profile(profile_path)
    profile_args = parse_args([
        *race_engineer_launch_profile_to_cli_args(profile),
    ])
    profile_args.debug = bool(getattr(args, "debug", False))
    profile_args.managed = bool(getattr(args, "managed", False))
    profile_args.log_file = str(getattr(args, "log_file", profile_args.log_file) or profile_args.log_file)
    profile_args.profile_file = str(getattr(args, "profile_file", "") or "")
    profile_args.question_snapshot = str(getattr(args, "question_snapshot", "") or "")
    return profile_args


def _stop_microphone_capture_for_test(microphone_capture: PushToTalkMicrophoneCapture) -> None:
    if microphone_capture.active:
        microphone_capture.stop()


async def run_question_test(
    conversation_agent: RaceEngineerConversationAgent,
    logger: logging.Logger,
    question: str,
    *,
    snapshot_path: str = "",
    print_result: bool = True,
) -> RaceEngineerAnswer:
    """Answer one text question without connecting to live telemetry."""

    telemetry_update = load_question_test_snapshot(snapshot_path)
    answer = await conversation_agent.answer(question, telemetry_update=telemetry_update)
    payload = {
        "ok": answer.ok,
        "question": answer.question,
        "answer": answer.answer,
        "source": answer.source,
        "focus": answer.focus,
        "error": answer.error,
        "metrics": answer.metrics or {},
    }
    if print_result:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if answer.ok:
        logger.info("Race engineer question test answered through %s", answer.source)
    else:
        logger.warning("Race engineer question test failed through %s: %s", answer.source, answer.error)
    return answer


def _profile_diagnostic_to_dict(item: RaceEngineerProfileDiagnostic) -> Dict[str, str]:
    return {
        "severity": item.severity,
        "code": item.code,
        "message": item.message,
    }


def _voice_result_to_dict(result: VoiceResult) -> Dict[str, Any]:
    return {
        "ok": result.ok,
        "skipped": False,
        "provider": result.provider,
        "text": result.text,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "audio_bytes": result.audio_bytes,
    }


def _answer_to_dict(answer: RaceEngineerAnswer) -> Dict[str, Any]:
    return {
        "ok": answer.ok,
        "question": answer.question,
        "answer": answer.answer,
        "source": answer.source,
        "focus": answer.focus,
        "error": answer.error,
        "metrics": answer.metrics or {},
    }


def _preflight_push_to_talk_payload(
    profile: Any,
    diagnostics: List[RaceEngineerProfileDiagnostic],
) -> Dict[str, Any]:
    ptt_bound = profile.race_engineer_push_to_talk_udp_action_code is not None
    speech_provider = str(profile.speech_recognition_provider or "disabled")
    audio_source = str(profile.push_to_talk_audio_source or "external")
    blocking_codes = {
        item.code for item in diagnostics
        if item.severity == "error"
        and (
            item.code.startswith("azure-stt")
            or item.code == "ptt-speech-recognition-disabled"
            or item.code == "ptt-windows-microphone-platform"
            or item.code == "udp-action-conflict"
        )
    }

    payload: Dict[str, Any] = {
        "ok": True,
        "skipped": False,
        "configured": speech_provider == "azure" or ptt_bound,
        "udp_action_bound": ptt_bound,
        "speech_provider": speech_provider,
        "audio_source": audio_source,
        "live_tested": False,
        "live_test_recommended": False,
        "message": "",
    }

    if blocking_codes:
        payload.update({
            "ok": False,
            "error": "Push-to-talk setup has blocking profile diagnostics.",
            "diagnostic_codes": sorted(blocking_codes),
        })
        return payload

    if speech_provider != "azure":
        payload.update({
            "ok": not ptt_bound,
            "skipped": not ptt_bound,
            "configured": False,
            "message": "Push-to-talk voice questions are not configured.",
        })
        if ptt_bound:
            payload["error"] = "Push-to-talk UDP action is bound, but speech recognition is disabled."
        return payload

    if audio_source == _PUSH_TO_TALK_AUDIO_SOURCE_WINDOWS_MICROPHONE:
        payload.update({
            "message": "Windows microphone push-to-talk is configured. Run Mic PTT Test for a live recording check.",
            "live_test_recommended": True,
        })
        return payload

    if audio_source == _PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL:
        payload.update({
            "message": "External push-to-talk audio is configured; another client must publish audio chunks.",
            "external_audio_required": True,
        })
        return payload

    payload.update({
        "ok": False,
        "error": f"Unsupported push-to-talk audio source: {audio_source}",
    })
    return payload


def _preflight_next_steps(
    profile: Any,
    diagnostics: List[RaceEngineerProfileDiagnostic],
    voice_payload: Dict[str, Any],
    question_payload: Dict[str, Any],
    push_to_talk_payload: Dict[str, Any],
) -> List[str]:
    """Build short post-preflight actions for launcher users."""

    steps: List[str] = []
    diagnostic_codes = {item.code for item in diagnostics}
    if diagnostic_codes:
        if any(code.startswith("azure-tts") or code.startswith("azure-stt") for code in diagnostic_codes):
            steps.append(
                f"Set {profile.azure_key_env_var} to your Azure Speech key, verify endpoint/region, then rerun Preflight."
            )
        if any(code.startswith("conversation-") for code in diagnostic_codes):
            steps.append("Fix the conversation provider settings, then run Question Test.")
        if "agent-prompts-file-missing" in diagnostic_codes:
            steps.append("Create or choose an agent prompts JSON file, then rerun Check.")
        if "udp-action-conflict" in diagnostic_codes:
            steps.append("Use different UDP action codes for toggle and push-to-talk.")
        if "ptt-speech-recognition-disabled" in diagnostic_codes:
            steps.append("Enable Azure speech recognition or clear the push-to-talk UDP action binding.")
        if "ptt-windows-microphone-platform" in diagnostic_codes:
            steps.append("Use Windows microphone capture only on Windows, or switch push-to-talk audio to external.")

    if not voice_payload.get("ok", False) and not voice_payload.get("skipped", False):
        steps.append("Run Voice Test again after fixing Azure voice settings.")
    if not question_payload.get("ok", False) and not question_payload.get("skipped", False):
        steps.append("Run Question Test again after fixing the answer provider.")

    if push_to_talk_payload.get("live_test_recommended", False):
        steps.append("Run Mic PTT Test before driving to verify the real microphone path.")
    if push_to_talk_payload.get("external_audio_required", False):
        steps.append("Start the external push-to-talk audio publisher before using the wheel hold binding.")
    if push_to_talk_payload.get("udp_action_bound", False):
        steps.append("Restart the backend after changing UDP action bindings.")

    if not steps:
        steps.append("Start the launcher stack, enable Race Engineer, then drive one out lap to populate live telemetry.")

    return _dedupe_next_steps(steps)


def _dedupe_next_steps(steps: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for step in steps:
        text = str(step or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _speech_result_to_dict(result: SpeechRecognitionResult) -> Dict[str, Any]:
    return {
        "ok": result.ok,
        "provider": result.provider,
        "text": result.text,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "confidence": result.confidence,
        "status": result.status,
    }


def load_question_test_snapshot(snapshot_path: str) -> Dict[str, Any]:
    """Load a question-test race-table snapshot or return sample telemetry."""

    path = str(snapshot_path or "").strip()
    if not path:
        return _sample_question_test_snapshot()
    with open(path, "r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError("question snapshot must be a JSON object")
    for key in ("race-table-update", "telemetry_update", "telemetry-update"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


async def run_voice_test(
    voice_engine: VoiceEngine,
    logger: logging.Logger,
    text: str,
) -> Any:
    """Speak one test callout without connecting to telemetry."""

    result = await voice_engine.speak(
        text,
        metadata={
            "priority": "info",
            "category": "system",
            "cooldown_key": "voice-test",
            "advice_id": "voice-test",
            "evidence": ["manual voice test"],
            "metrics": {},
        },
    )
    if result.ok:
        logger.info(
            "Race engineer voice test succeeded using %s in %s ms (%s audio bytes)",
            result.provider,
            result.duration_ms,
            result.audio_bytes,
        )
    else:
        logger.error("Race engineer voice test failed: %s", result.error)
    return result


def _build_azure_voice_engine(args: argparse.Namespace, logger: logging.Logger) -> VoiceEngine:
    audio_sink = NoOpAudioSink()
    no_audio_playback = bool(getattr(args, "no_audio_playback", False))
    if not no_audio_playback:
        if sys.platform == "win32":
            audio_sink = WindowsWaveAudioSink()
        else:
            logger.warning("Azure audio playback is not configured for this platform; discarding synthesized audio")

    return AzureSpeechVoiceEngine(
        AzureSpeechConfig(
            region=getattr(args, "azure_region", ""),
            voice=getattr(args, "azure_voice", DEFAULT_AZURE_SPEECH_VOICE),
            key_env_var=getattr(args, "azure_key_env_var", DEFAULT_AZURE_SPEECH_KEY_ENV_VAR),
            output_format=getattr(args, "azure_output_format", DEFAULT_AZURE_SPEECH_OUTPUT_FORMAT),
            endpoint=getattr(args, "azure_speech_endpoint", "") or None,
        ),
        audio_sink=audio_sink,
        logger=logger,
    )


def _sample_question_test_snapshot() -> Dict[str, Any]:
    """Return a compact synthetic race table snapshot for offline Q&A smoke tests."""

    return {
        "session-uid": 9001,
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
            _sample_question_test_row(
                name="Driver Ahead",
                index=3,
                position=4,
                is_player=False,
                delta_to_front=4200,
                last_lap_ms=90750,
                fuel_surplus=0.4,
            ),
            _sample_question_test_row(
                name="Player",
                index=7,
                position=5,
                is_player=True,
                delta_to_front=1250,
                last_lap_ms=90400,
                fuel_surplus=-0.65,
            ),
            _sample_question_test_row(
                name="Driver Behind",
                index=11,
                position=6,
                is_player=False,
                delta_to_front=1800,
                last_lap_ms=90300,
                fuel_surplus=0.2,
            ),
        ],
    }


def _sample_question_test_row(
    *,
    name: str,
    index: int,
    position: int,
    is_player: bool,
    delta_to_front: int,
    last_lap_ms: int,
    fuel_surplus: float,
) -> Dict[str, Any]:
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
            "surplus-laps-png": fuel_surplus,
            "surplus-laps-game": fuel_surplus,
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


def _normalise_voice_provider(provider: str) -> str:
    provider = (provider or "dry_run").strip().lower().replace("-", "_")
    if provider not in {"dry_run", "azure", "disabled"}:
        return "dry_run"
    return provider


def _normalise_speech_recognition_provider(provider: str) -> str:
    provider = (provider or "disabled").strip().lower().replace("-", "_")
    if provider not in {"azure", "disabled"}:
        return "disabled"
    return provider


def _normalise_push_to_talk_audio_source(source: str) -> str:
    source = (source or _PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL).strip().lower().replace("-", "_")
    if source in {"microphone", "windows", "winmm"}:
        return _PUSH_TO_TALK_AUDIO_SOURCE_WINDOWS_MICROPHONE
    if source not in {_PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL, _PUSH_TO_TALK_AUDIO_SOURCE_WINDOWS_MICROPHONE}:
        return _PUSH_TO_TALK_AUDIO_SOURCE_EXTERNAL
    return source


def _normalise_conversation_provider(provider: str) -> str:
    provider = (provider or _CONVERSATION_PROVIDER_LOCAL).strip().lower().replace("-", "_")
    if provider in {"local", "local_brief", "brief"}:
        return _CONVERSATION_PROVIDER_LOCAL
    if provider in {"http", "external_http", "codex", "codex_http"}:
        return _CONVERSATION_PROVIDER_HTTP
    if provider in {"codex_cli", "cli", "command", "external_command"}:
        return _CONVERSATION_PROVIDER_CODEX_CLI
    return _CONVERSATION_PROVIDER_LOCAL


def _arg_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalised = str(value or "").strip().lower()
    if normalised in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalised in {"0", "false", "no", "off", "disabled"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got {value!r}")


def _bool_from_control_value(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if normalised in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _safe_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return _arg_bool(value)
    except argparse.ArgumentTypeError:
        return default


def _extract_session_uid(msg: Any) -> Optional[str]:
    if not isinstance(msg, dict):
        return None
    value = msg.get("session-uid")
    if value in (None, ""):
        return None
    return str(value)


def _voice_priority_rank(priority: Any) -> int:
    if not isinstance(priority, str):
        return _VOICE_PRIORITY_RANK["info"]
    return _VOICE_PRIORITY_RANK.get(priority.strip().lower(), _VOICE_PRIORITY_RANK["info"])
