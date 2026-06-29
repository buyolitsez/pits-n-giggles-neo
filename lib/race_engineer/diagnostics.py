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
from pathlib import Path
import os
import shutil
import sys
from typing import Mapping, Optional
from urllib.parse import urlparse

from .conversation import parse_conversation_command
from .launch_profile import RaceEngineerLaunchProfile

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RaceEngineerProfileDiagnostic:
    """One offline setup check for the launcher-managed race engineer profile."""

    severity: str
    code: str
    message: str


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def diagnose_race_engineer_launch_profile(
    profile: RaceEngineerLaunchProfile,
    *,
    environ: Optional[Mapping[str, str]] = None,
    platform: Optional[str] = None,
    command_exists=None,
    path_exists=None,
) -> list[RaceEngineerProfileDiagnostic]:
    """Run offline setup checks for a race engineer launch profile.

    The diagnostics never read or return secret values. They only check whether
    the configured environment-variable names exist.
    """

    env = environ if environ is not None else os.environ
    platform = platform if platform is not None else sys.platform
    command_exists = command_exists or _command_exists
    path_exists = path_exists or _path_exists
    issues: list[RaceEngineerProfileDiagnostic] = []

    _check_azure_voice(profile, env, issues)
    _check_azure_stt(profile, env, platform, issues)
    _check_conversation(profile, issues, command_exists)
    _check_prompt_file(profile, issues, path_exists)
    _check_udp_actions(profile, issues)

    return issues


def format_race_engineer_profile_diagnostics(
    diagnostics: list[RaceEngineerProfileDiagnostic],
) -> str:
    """Format diagnostics for a launcher message box."""

    if not diagnostics:
        return "Race Engineer profile looks ready."
    lines = []
    for item in diagnostics:
        label = "Error" if item.severity == "error" else "Warning"
        lines.append(f"{label}: {item.message}")
    return "\n".join(lines)


def race_engineer_profile_has_errors(diagnostics: list[RaceEngineerProfileDiagnostic]) -> bool:
    """Return True if diagnostics contain blocking setup errors."""

    return any(item.severity == "error" for item in diagnostics)


def _check_azure_voice(
    profile: RaceEngineerLaunchProfile,
    env: Mapping[str, str],
    issues: list[RaceEngineerProfileDiagnostic],
) -> None:
    if profile.voice_provider != "azure":
        return
    _check_azure_location(profile, issues, "azure-tts-location")
    _check_env_var_present(
        profile.azure_key_env_var,
        env,
        issues,
        code="azure-tts-key-missing",
        message=f"Azure TTS key environment variable {profile.azure_key_env_var!r} is not set.",
    )


def _check_azure_stt(
    profile: RaceEngineerLaunchProfile,
    env: Mapping[str, str],
    platform: str,
    issues: list[RaceEngineerProfileDiagnostic],
) -> None:
    if profile.speech_recognition_provider != "azure":
        return
    _check_azure_location(profile, issues, "azure-stt-location")
    _check_env_var_present(
        profile.azure_key_env_var,
        env,
        issues,
        code="azure-stt-key-missing",
        message=f"Azure STT key environment variable {profile.azure_key_env_var!r} is not set.",
    )
    if profile.push_to_talk_audio_source == "external":
        issues.append(RaceEngineerProfileDiagnostic(
            severity="warning",
            code="ptt-external-audio",
            message="Push-to-talk audio is external; another client must publish audio chunks.",
        ))
    if profile.push_to_talk_audio_source == "windows_microphone" and platform != "win32":
        issues.append(RaceEngineerProfileDiagnostic(
            severity="error",
            code="ptt-windows-microphone-platform",
            message="Windows microphone capture is selected but this platform is not Windows.",
        ))


def _check_conversation(
    profile: RaceEngineerLaunchProfile,
    issues: list[RaceEngineerProfileDiagnostic],
    command_exists,
) -> None:
    if profile.conversation_provider == "http":
        endpoint = profile.conversation_endpoint.strip()
        if not endpoint:
            issues.append(RaceEngineerProfileDiagnostic(
                severity="error",
                code="conversation-http-endpoint-missing",
                message="HTTP conversation provider is selected but no endpoint is configured.",
            ))
            return
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            issues.append(RaceEngineerProfileDiagnostic(
                severity="error",
                code="conversation-http-endpoint-invalid",
                message="HTTP conversation endpoint must be an http:// or https:// URL.",
            ))
    elif profile.conversation_provider == "codex_cli":
        argv = parse_conversation_command(profile.conversation_command)
        if not argv:
            issues.append(RaceEngineerProfileDiagnostic(
                severity="error",
                code="conversation-command-missing",
                message="Codex CLI conversation provider is selected but no command is configured.",
            ))
            return
        if not command_exists(argv[0]):
            issues.append(RaceEngineerProfileDiagnostic(
                severity="warning",
                code="conversation-command-not-found",
                message=f"Conversation command executable {argv[0]!r} was not found on PATH.",
            ))


def _check_prompt_file(
    profile: RaceEngineerLaunchProfile,
    issues: list[RaceEngineerProfileDiagnostic],
    path_exists,
) -> None:
    if not profile.agent_prompts_file:
        return
    if not path_exists(profile.agent_prompts_file):
        issues.append(RaceEngineerProfileDiagnostic(
            severity="error",
            code="agent-prompts-file-missing",
            message=f"Agent prompts file {profile.agent_prompts_file!r} does not exist.",
        ))


def _check_udp_actions(
    profile: RaceEngineerLaunchProfile,
    issues: list[RaceEngineerProfileDiagnostic],
) -> None:
    toggle = profile.race_engineer_toggle_udp_action_code
    ptt = profile.race_engineer_push_to_talk_udp_action_code
    if toggle is not None and toggle == ptt:
        issues.append(RaceEngineerProfileDiagnostic(
            severity="error",
            code="udp-action-conflict",
            message="Toggle and push-to-talk must use different UDP action codes.",
        ))
    if ptt is not None and profile.speech_recognition_provider != "azure":
        issues.append(RaceEngineerProfileDiagnostic(
            severity="error",
            code="ptt-speech-recognition-disabled",
            message="Push-to-talk UDP action is bound, but speech recognition is disabled.",
        ))


def _check_azure_location(
    profile: RaceEngineerLaunchProfile,
    issues: list[RaceEngineerProfileDiagnostic],
    code: str,
) -> None:
    endpoint = profile.azure_speech_endpoint.strip()
    region = profile.azure_region.strip()
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            issues.append(RaceEngineerProfileDiagnostic(
                severity="error",
                code=code,
                message="Azure Speech endpoint must be an https:// URL.",
            ))
        return
    if not region:
        issues.append(RaceEngineerProfileDiagnostic(
            severity="error",
            code=code,
            message="Azure Speech needs either an endpoint or a region.",
        ))


def _check_env_var_present(
    env_var_name: str,
    env: Mapping[str, str],
    issues: list[RaceEngineerProfileDiagnostic],
    *,
    code: str,
    message: str,
) -> None:
    if not env_var_name:
        issues.append(RaceEngineerProfileDiagnostic(
            severity="error",
            code=code,
            message="Azure Speech key environment variable name is not configured.",
        ))
        return
    if env_var_name not in env or not str(env.get(env_var_name) or "").strip():
        issues.append(RaceEngineerProfileDiagnostic(
            severity="error",
            code=code,
            message=message,
        ))


def _command_exists(executable: str) -> bool:
    if not executable:
        return False
    path = Path(executable)
    if path.parent != Path("."):
        return path.exists()
    return shutil.which(executable) is not None


def _path_exists(path: str) -> bool:
    return Path(path).exists()
