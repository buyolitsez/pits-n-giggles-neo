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

from dataclasses import asdict, dataclass, fields
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.file_path import resolve_user_file

from .agent_prompts import CATEGORY_ALL, normalise_agent_focus
from .azure_voice import (
    DEFAULT_AZURE_SPEECH_KEY_ENV_VAR,
    DEFAULT_AZURE_SPEECH_OUTPUT_FORMAT,
    DEFAULT_AZURE_SPEECH_VOICE,
)
from .memory import DEFAULT_RACE_ENGINEER_MEMORY_FILE
from .speech_recognition import DEFAULT_AZURE_STT_CONTENT_TYPE, DEFAULT_AZURE_STT_FORMAT, DEFAULT_AZURE_STT_LANGUAGE

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

DEFAULT_RACE_ENGINEER_LAUNCH_PROFILE_FILE = "race_engineer_profile.json"

_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VOICE_PROVIDERS = {"dry_run", "azure", "disabled"}
_SPEECH_RECOGNITION_PROVIDERS = {"azure", "disabled"}
_CONVERSATION_PROVIDERS = {"local_brief", "http", "codex_cli"}
_PUSH_TO_TALK_AUDIO_SOURCES = {"external", "windows_microphone"}
_PRIORITIES = {"critical", "warning", "advisory", "info"}
RACE_ENGINEER_FAST_LIVE_COMMAND_TIMEOUT_MS = 3000
RACE_ENGINEER_QUESTION_TIMEOUT_GRACE_SECONDS = 2.0

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RaceEngineerLaunchProfile:
    """Launcher-managed race engineer profile kept outside the main telemetry config."""

    initial_enabled: bool = True
    focus: str = CATEGORY_ALL
    min_priority: str = "advisory"
    cooldown_seconds: int = 20
    min_voice_interval_seconds: float = 4.0
    max_items: int = 5
    max_queue_size: int = 3

    voice_provider: str = "dry_run"
    azure_region: str = ""
    azure_speech_endpoint: str = ""
    azure_voice: str = DEFAULT_AZURE_SPEECH_VOICE
    azure_key_env_var: str = DEFAULT_AZURE_SPEECH_KEY_ENV_VAR
    azure_output_format: str = DEFAULT_AZURE_SPEECH_OUTPUT_FORMAT
    no_audio_playback: bool = False

    speech_recognition_provider: str = "disabled"
    azure_stt_language: str = DEFAULT_AZURE_STT_LANGUAGE
    azure_stt_format: str = DEFAULT_AZURE_STT_FORMAT
    azure_stt_content_type: str = DEFAULT_AZURE_STT_CONTENT_TYPE
    push_to_talk_audio_source: str = "external"

    conversation_provider: str = "local_brief"
    conversation_endpoint: str = ""
    conversation_key_env_var: str = ""
    conversation_command: str = ""
    conversation_timeout_seconds: float = 10.0

    agent_prompts_file: str = ""
    memory_file: str = DEFAULT_RACE_ENGINEER_MEMORY_FILE
    race_engineer_toggle_udp_action_code: Optional[int] = None
    race_engineer_push_to_talk_udp_action_code: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return profile as a JSON-serializable dictionary."""

        return asdict(self)


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def default_race_engineer_launch_profile_path() -> str:
    """Return the default launcher profile path."""

    return resolve_user_file(DEFAULT_RACE_ENGINEER_LAUNCH_PROFILE_FILE)


def load_race_engineer_launch_profile(path: Optional[str] = None) -> RaceEngineerLaunchProfile:
    """Load the race engineer launch profile, falling back to defaults if absent."""

    path = path or default_race_engineer_launch_profile_path()
    if not Path(path).exists():
        return RaceEngineerLaunchProfile()
    with Path(path).open("r", encoding="utf-8") as file_obj:
        raw = json.load(file_obj)
    return race_engineer_launch_profile_from_dict(raw)


def save_race_engineer_launch_profile(
    profile: RaceEngineerLaunchProfile,
    path: Optional[str] = None,
) -> None:
    """Persist the race engineer launch profile."""

    path = path or default_race_engineer_launch_profile_path()
    target = Path(path)
    if target.parent != Path("."):
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file_obj:
        json.dump(profile.to_dict(), file_obj, indent=4)


def race_engineer_launch_profile_from_dict(value: Any) -> RaceEngineerLaunchProfile:
    """Validate and normalize a raw profile dictionary."""

    raw = value if isinstance(value, dict) else {}
    defaults = RaceEngineerLaunchProfile()
    allowed = {field.name for field in fields(RaceEngineerLaunchProfile)}
    data = {key: raw.get(key, getattr(defaults, key)) for key in allowed}

    profile = RaceEngineerLaunchProfile(
        initial_enabled=_bool(data["initial_enabled"], defaults.initial_enabled),
        focus=normalise_agent_focus(_text(data["focus"])) or defaults.focus,
        min_priority=_choice(_text(data["min_priority"]), _PRIORITIES, defaults.min_priority),
        cooldown_seconds=_bounded_int(data["cooldown_seconds"], 1, 300, defaults.cooldown_seconds),
        min_voice_interval_seconds=_bounded_float(
            data["min_voice_interval_seconds"], 0.0, 60.0, defaults.min_voice_interval_seconds),
        max_items=_bounded_int(data["max_items"], 1, 10, defaults.max_items),
        max_queue_size=_bounded_int(data["max_queue_size"], 1, 10, defaults.max_queue_size),
        voice_provider=_choice(_text(data["voice_provider"]).replace("-", "_"), _VOICE_PROVIDERS, defaults.voice_provider),
        azure_region=_text(data["azure_region"]),
        azure_speech_endpoint=_text(data["azure_speech_endpoint"]),
        azure_voice=_text(data["azure_voice"]) or defaults.azure_voice,
        azure_key_env_var=_env_var_name(data["azure_key_env_var"], defaults.azure_key_env_var),
        azure_output_format=_text(data["azure_output_format"]) or defaults.azure_output_format,
        no_audio_playback=_bool(data["no_audio_playback"], defaults.no_audio_playback),
        speech_recognition_provider=_choice(
            _text(data["speech_recognition_provider"]).replace("-", "_"),
            _SPEECH_RECOGNITION_PROVIDERS,
            defaults.speech_recognition_provider,
        ),
        azure_stt_language=_text(data["azure_stt_language"]) or defaults.azure_stt_language,
        azure_stt_format=_text(data["azure_stt_format"]) or defaults.azure_stt_format,
        azure_stt_content_type=_text(data["azure_stt_content_type"]) or defaults.azure_stt_content_type,
        push_to_talk_audio_source=_choice(
            _text(data["push_to_talk_audio_source"]).replace("-", "_"),
            _PUSH_TO_TALK_AUDIO_SOURCES,
            defaults.push_to_talk_audio_source,
        ),
        conversation_provider=_choice(
            _text(data["conversation_provider"]).replace("-", "_"),
            _CONVERSATION_PROVIDERS,
            defaults.conversation_provider,
        ),
        conversation_endpoint=_text(data["conversation_endpoint"]),
        conversation_key_env_var=_env_var_name(data["conversation_key_env_var"], defaults.conversation_key_env_var),
        conversation_command=_text(data["conversation_command"]),
        conversation_timeout_seconds=_bounded_float(
            data["conversation_timeout_seconds"], 0.1, 120.0, defaults.conversation_timeout_seconds),
        agent_prompts_file=_text(data["agent_prompts_file"]),
        memory_file=_text(data["memory_file"]) or defaults.memory_file,
        race_engineer_toggle_udp_action_code=_udp_action_code(data["race_engineer_toggle_udp_action_code"]),
        race_engineer_push_to_talk_udp_action_code=_udp_action_code(
            data["race_engineer_push_to_talk_udp_action_code"]),
    )
    if (
            profile.race_engineer_toggle_udp_action_code is not None
            and profile.race_engineer_toggle_udp_action_code == profile.race_engineer_push_to_talk_udp_action_code):
        return RaceEngineerLaunchProfile(
            **{
                **profile.to_dict(),
                "race_engineer_push_to_talk_udp_action_code": None,
            }
        )
    return profile


def race_engineer_launch_profile_to_cli_args(profile: RaceEngineerLaunchProfile) -> List[str]:
    """Build CLI arguments for apps.race_engineer from a launch profile."""

    args = [
        "--initial-enabled", _bool_text(profile.initial_enabled),
        "--focus", profile.focus,
        "--min-priority", profile.min_priority,
        "--cooldown-seconds", str(profile.cooldown_seconds),
        "--min-voice-interval-seconds", str(profile.min_voice_interval_seconds),
        "--max-items", str(profile.max_items),
        "--max-queue-size", str(profile.max_queue_size),
        "--voice-provider", profile.voice_provider,
        "--azure-region", profile.azure_region,
        "--azure-speech-endpoint", profile.azure_speech_endpoint,
        "--azure-voice", profile.azure_voice,
        "--azure-key-env-var", profile.azure_key_env_var,
        "--azure-output-format", profile.azure_output_format,
        "--speech-recognition-provider", profile.speech_recognition_provider,
        "--azure-stt-language", profile.azure_stt_language,
        "--azure-stt-format", profile.azure_stt_format,
        "--azure-stt-content-type", profile.azure_stt_content_type,
        "--push-to-talk-audio-source", profile.push_to_talk_audio_source,
        "--conversation-provider", profile.conversation_provider,
        "--conversation-endpoint", profile.conversation_endpoint,
        "--conversation-key-env-var", profile.conversation_key_env_var,
        "--conversation-command", profile.conversation_command,
        "--conversation-timeout-seconds", str(profile.conversation_timeout_seconds),
        "--agent-prompts-file", profile.agent_prompts_file,
        "--memory-file", profile.memory_file,
    ]
    if profile.no_audio_playback:
        args.append("--no-audio-playback")
    return args


def race_engineer_profile_udp_action_codes(profile: RaceEngineerLaunchProfile) -> Dict[str, Optional[int]]:
    """Return the UDP action codes stored in a profile."""

    return {
        "race_engineer_toggle": profile.race_engineer_toggle_udp_action_code,
        "race_engineer_push_to_talk": profile.race_engineer_push_to_talk_udp_action_code,
    }


def race_engineer_profile_udp_action_code(
    profile: RaceEngineerLaunchProfile,
    field_name: str,
    *,
    existing_codes: Optional[Dict[int, str]] = None,
) -> Optional[int]:
    """Return a profile UDP action code unless it conflicts with existing mappings."""

    value = getattr(profile, field_name, None)
    if value is None:
        return None
    if existing_codes and value in existing_codes:
        return None
    return value


def race_engineer_live_question_timeout_ms(profile: RaceEngineerLaunchProfile) -> int:
    """Return the launcher IPC timeout for a live typed question."""

    timeout_seconds = _bounded_float(
        profile.conversation_timeout_seconds,
        0.1,
        120.0,
        RaceEngineerLaunchProfile().conversation_timeout_seconds,
    )
    question_timeout_ms = int((timeout_seconds + RACE_ENGINEER_QUESTION_TIMEOUT_GRACE_SECONDS) * 1000)
    return max(RACE_ENGINEER_FAST_LIVE_COMMAND_TIMEOUT_MS, question_timeout_ms)


def _text(value: Any) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _choice(value: str, choices: set[str], default: str) -> str:
    return value if value in choices else default


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalised in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _bounded_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _env_var_name(value: Any, default: str) -> str:
    text = _text(value)
    if not text:
        return ""
    return text if _ENV_VAR_RE.match(text) else default


def _udp_action_code(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 12 else None
