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
import os
import re
import sys
from typing import MutableMapping, Optional, Protocol

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# -------------------------------------- CLASSES -----------------------------------------------------------------------


class UserEnvWriter(Protocol):
    """Small protocol for persistent user environment variable writes."""

    def __call__(self, name: str, value: Optional[str]) -> None:
        """Write or clear one user environment variable."""


@dataclass(frozen=True, slots=True)
class LocalSecretResult:
    """Result for a local secret save/clear operation."""

    ok: bool
    env_var_name: str
    persisted: bool
    error: Optional[str] = None


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def save_local_env_secret(
    env_var_name: str,
    secret_value: str,
    *,
    environ: Optional[MutableMapping[str, str]] = None,
    user_env_writer: Optional[UserEnvWriter] = None,
) -> LocalSecretResult:
    """Save a secret in process env and the OS user environment."""

    name = _normalise_env_var_name(env_var_name)
    secret = str(secret_value or "").strip()
    if not name:
        return LocalSecretResult(False, "", False, "environment variable name is invalid")
    if not secret:
        return LocalSecretResult(False, name, False, "secret value is empty")

    try:
        (user_env_writer or _write_user_environment_variable)(name, secret)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return LocalSecretResult(False, name, False, _safe_error(exc, secret))

    target_env = environ if environ is not None else os.environ
    target_env[name] = secret
    return LocalSecretResult(True, name, True)


def clear_local_env_secret(
    env_var_name: str,
    *,
    environ: Optional[MutableMapping[str, str]] = None,
    user_env_writer: Optional[UserEnvWriter] = None,
) -> LocalSecretResult:
    """Clear a secret from process env and the OS user environment."""

    name = _normalise_env_var_name(env_var_name)
    if not name:
        return LocalSecretResult(False, "", False, "environment variable name is invalid")

    try:
        (user_env_writer or _write_user_environment_variable)(name, None)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return LocalSecretResult(False, name, False, _safe_error(exc))

    target_env = environ if environ is not None else os.environ
    target_env.pop(name, None)
    return LocalSecretResult(True, name, True)


def local_env_secret_is_set(
    env_var_name: str,
    *,
    environ: Optional[MutableMapping[str, str]] = None,
) -> bool:
    """Return True when the env var has a non-empty value."""

    name = _normalise_env_var_name(env_var_name)
    if not name:
        return False
    target_env = environ if environ is not None else os.environ
    return bool(str(target_env.get(name) or "").strip())


def _write_user_environment_variable(name: str, value: Optional[str]) -> None:
    if sys.platform != "win32":
        raise RuntimeError("persistent local secret save is only supported on Windows")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        if value is None:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    _broadcast_environment_change()


def _broadcast_environment_change() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            5000,
            ctypes.byref(result),
        )
    except Exception:
        pass


def _normalise_env_var_name(value: str) -> str:
    text = str(value or "").strip()
    return text if _ENV_VAR_RE.match(text) else ""


def _safe_error(exc: Exception, secret_value: Optional[str] = None) -> str:
    message = str(exc)
    secret = str(secret_value or "")
    if secret:
        message = message.replace(secret, "<redacted>")
    return message
