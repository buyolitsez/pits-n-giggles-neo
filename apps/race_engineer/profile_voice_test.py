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

import json
import os
import sys
import tempfile
from typing import Any, List, Optional

from lib.race_engineer import RaceEngineerLaunchProfile, save_race_engineer_launch_profile

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_PROFILE_VOICE_TEST_MESSAGE = "Radio check."
DEFAULT_PROFILE_QUESTION_TEST_MESSAGE = "what should I know?"
DEFAULT_PROFILE_PREFLIGHT_QUESTION = "какие шины брать на пит?"
DEFAULT_PROFILE_MIC_QUESTION_TEST_SECONDS = 3.0

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def build_profile_voice_test_command(
        profile_file: str,
        *,
        message: str = DEFAULT_PROFILE_VOICE_TEST_MESSAGE,
        executable: Optional[str] = None,
        frozen: Optional[bool] = None) -> List[str]:
    """Build a command that runs the race engineer profile voice smoke test."""

    return _build_profile_smoke_test_command(
        profile_file,
        flag="--profile-voice-test",
        message=message,
        executable=executable,
        frozen=frozen,
    )


def build_profile_question_test_command(
        profile_file: str,
        *,
        question: str = DEFAULT_PROFILE_QUESTION_TEST_MESSAGE,
        executable: Optional[str] = None,
        frozen: Optional[bool] = None) -> List[str]:
    """Build a command that runs the race engineer profile question smoke test."""

    return _build_profile_smoke_test_command(
        profile_file,
        flag="--profile-question-test",
        message=question,
        executable=executable,
        frozen=frozen,
    )


def build_profile_audio_question_test_command(
        profile_file: str,
        audio_file: str,
        *,
        executable: Optional[str] = None,
        frozen: Optional[bool] = None) -> List[str]:
    """Build a command that runs the race engineer profile audio question smoke test."""

    executable = executable or sys.executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    module_args = ["--profile-file", profile_file, "--profile-audio-question-test", audio_file]
    if frozen:
        return [executable, "--module", "apps.race_engineer", *module_args]
    return [executable, "-m", "apps.race_engineer", *module_args]


def build_profile_mic_question_test_command(
        profile_file: str,
        *,
        seconds: float = DEFAULT_PROFILE_MIC_QUESTION_TEST_SECONDS,
        executable: Optional[str] = None,
        frozen: Optional[bool] = None) -> List[str]:
    """Build a command that records the configured microphone and runs a voice question smoke test."""

    executable = executable or sys.executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    module_args = [
        "--profile-file",
        profile_file,
        "--profile-mic-question-test-seconds",
        str(max(0.1, float(seconds or DEFAULT_PROFILE_MIC_QUESTION_TEST_SECONDS))),
    ]
    if frozen:
        return [executable, "--module", "apps.race_engineer", *module_args]
    return [executable, "-m", "apps.race_engineer", *module_args]


def build_profile_preflight_command(
        profile_file: str,
        *,
        question: str = DEFAULT_PROFILE_PREFLIGHT_QUESTION,
        executable: Optional[str] = None,
        frozen: Optional[bool] = None) -> List[str]:
    """Build a command that runs the race engineer profile preflight check."""

    executable = executable or sys.executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    module_args = [
        "--profile-file",
        profile_file,
        "--profile-preflight",
        "--profile-preflight-question",
        question,
    ]
    if frozen:
        return [executable, "--module", "apps.race_engineer", *module_args]
    return [executable, "-m", "apps.race_engineer", *module_args]


def _build_profile_smoke_test_command(
        profile_file: str,
        *,
        flag: str,
        message: str,
        executable: Optional[str] = None,
        frozen: Optional[bool] = None) -> List[str]:
    """Build a command that runs one race engineer profile smoke test."""

    executable = executable or sys.executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    module_args = ["--profile-file", profile_file, flag, message]
    if frozen:
        return [executable, "--module", "apps.race_engineer", *module_args]
    return [executable, "-m", "apps.race_engineer", *module_args]


def write_temp_profile_for_voice_test(
        profile: RaceEngineerLaunchProfile,
        *,
        directory: Optional[str] = None) -> str:
    """Write a temporary launch profile for testing unsaved settings."""

    return write_temp_profile_for_smoke_test(profile, directory=directory)


def write_temp_profile_for_smoke_test(
        profile: RaceEngineerLaunchProfile,
        *,
        directory: Optional[str] = None) -> str:
    """Write a temporary launch profile for testing unsaved settings."""

    with tempfile.NamedTemporaryFile(
            prefix="png-race-engineer-profile-",
            suffix=".json",
            dir=directory,
            delete=False) as temp_file:
        path = temp_file.name
    try:
        save_race_engineer_launch_profile(profile, path)
    except Exception:
        _remove_file_if_exists(path)
        raise
    return path


def cleanup_temp_profile_for_voice_test(path: str) -> None:
    """Remove a temporary profile created for a smoke test."""

    cleanup_temp_profile_for_smoke_test(path)


def cleanup_temp_profile_for_smoke_test(path: str) -> None:
    """Remove a temporary profile created for a smoke test."""

    _remove_file_if_exists(path)


def format_profile_question_test_output(output: str) -> str:
    """Format profile question-test stdout for a launcher message box."""

    payload = _extract_json_object(output)
    if isinstance(payload, dict):
        if bool(payload.get("ok", False)):
            answer = str(payload.get("answer") or "").strip()
            source = str(payload.get("source") or "").strip()
            focus = str(payload.get("focus") or "").strip()
            details = " | ".join(part for part in (source, focus) if part)
            if details:
                return f"{answer}\n\n{details}" if answer else details
            return answer or "Question test completed."
        error = str(payload.get("error") or "").strip()
        if error:
            return error
    return _last_lines(output) or "Question test completed without an answer."


def format_profile_audio_question_test_output(output: str) -> str:
    """Format profile audio question-test stdout for a launcher message box."""

    return _format_audio_question_pipeline_output(output, label="Audio question test")


def format_profile_mic_question_test_output(output: str) -> str:
    """Format profile microphone question-test stdout for a launcher message box."""

    return _format_audio_question_pipeline_output(output, label="Mic PTT test")


def _format_audio_question_pipeline_output(output: str, *, label: str) -> str:
    """Format audio-question pipeline stdout for a launcher message box."""

    payload = _extract_json_object(output)
    if not isinstance(payload, dict):
        return _last_lines(output) or f"{label} did not return a summary."

    if not payload.get("ok", False):
        error = str(payload.get("error") or "").strip()
        if error:
            return error

    speech = payload.get("speech") if isinstance(payload.get("speech"), dict) else {}
    question = payload.get("question") if isinstance(payload.get("question"), dict) else {}
    voice = payload.get("voice") if isinstance(payload.get("voice"), dict) else {}

    lines = [f"{label} completed." if payload.get("ok", False) else f"{label} found issues."]
    transcript = str(speech.get("text") or "").strip()
    answer = str(question.get("answer") or "").strip()
    if transcript:
        lines.append(f"Transcript: {transcript}")
    if answer:
        lines.append(f"Answer: {answer}")

    speech_provider = str(speech.get("provider") or "").strip()
    answer_source = str(question.get("source") or "").strip()
    voice_provider = str(voice.get("provider") or "").strip()
    if speech_provider:
        lines.append(f"Speech: {_ok_label(speech)} ({speech_provider})")
    if answer_source:
        lines.append(f"Question: {_ok_label(question)} ({answer_source})")
    if voice_provider:
        lines.append(f"Voice: {_ok_label(voice)} ({voice_provider})")

    for section in (speech, question, voice):
        error = str(section.get("error") or "").strip()
        if error:
            lines.append(f"Error: {error}")
            break
    return "\n".join(lines)


def format_profile_preflight_output(output: str) -> str:
    """Format profile preflight stdout for a launcher message box."""

    payload = _extract_json_object(output)
    if not isinstance(payload, dict):
        return _last_lines(output) or "Preflight did not return a summary."

    lines = ["Preflight completed." if payload.get("ok", False) else "Preflight found issues."]
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "info").title()
            message = str(item.get("message") or item.get("code") or "").strip()
            if message:
                lines.append(f"- {severity}: {message}")

    lines.append("")
    lines.append(f"Voice: {_format_preflight_section(payload.get('voice'))}")
    lines.append(f"Question: {_format_preflight_section(payload.get('question'))}")
    lines.append(f"Push-to-talk: {_format_preflight_section(payload.get('push_to_talk'))}")

    question = payload.get("question")
    if isinstance(question, dict):
        answer = str(question.get("answer") or "").strip()
        source = str(question.get("source") or "").strip()
        focus = str(question.get("focus") or "").strip()
        details = " | ".join(part for part in (source, focus) if part)
        if answer:
            lines.append("")
            lines.append(answer)
        if details:
            lines.append(details)

    push_to_talk = payload.get("push_to_talk")
    if isinstance(push_to_talk, dict):
        message = str(push_to_talk.get("message") or "").strip()
        if message:
            lines.append("")
            lines.append(message)

    return "\n".join(lines)


def _format_preflight_section(section: Any) -> str:
    if not isinstance(section, dict):
        return "missing"
    if section.get("skipped", False):
        error = str(section.get("error") or "").strip()
        return f"skipped ({error})" if error else "skipped"
    if section.get("ok", False):
        provider = str(section.get("provider") or section.get("source") or "").strip()
        return f"OK ({provider})" if provider else "OK"
    error = str(section.get("error") or "").strip()
    return f"failed ({error})" if error else "failed"


def _ok_label(section: dict[str, Any]) -> str:
    return "OK" if section.get("ok", False) else "failed"


def _remove_file_if_exists(path: str) -> None:
    try:
        if path:
            os.remove(path)
    except FileNotFoundError:
        pass


def _extract_json_object(output: str) -> Optional[dict[str, Any]]:
    text = str(output or "").strip()
    if not text:
        return None
    for candidate in (text, _json_slice(text)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _json_slice(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start:end + 1]


def _last_lines(text: str, *, max_chars: int = 1600) -> str:
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    return "...\n" + text[-max_chars:]
