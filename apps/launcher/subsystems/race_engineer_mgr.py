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

import threading
from dataclasses import replace
from typing import TYPE_CHECKING, List

from PySide6.QtWidgets import QInputDialog, QPushButton

from lib.config import PngSettings
from lib.ipc import IpcClientSync
from lib.race_engineer import (
    RACE_ENGINEER_FAST_LIVE_COMMAND_TIMEOUT_MS,
    RaceEngineerLaunchProfile,
    default_race_engineer_launch_profile_path,
    load_race_engineer_launch_profile,
    race_engineer_launch_profile_to_cli_args,
    race_engineer_launcher_status_from_stats,
    race_engineer_live_question_timeout_ms,
)

from .base_mgr import PngAppMgrBase, PngAppMgrConfig

if TYPE_CHECKING:
    from apps.launcher.gui import PngLauncherWindow

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

RACE_ENGINEER_STATUS_POLL_INTERVAL_SECONDS = 1.0
RACE_ENGINEER_STATUS_POLL_TIMEOUT_MS = 1000

# -------------------------------------- CLASSES -----------------------------------------------------------------------

class RaceEngineerAppMgr(PngAppMgrBase):
    """Implementation of the race engineer assistant subsystem."""

    MODULE_PATH = "apps.race_engineer"
    DISPLAY_NAME = "Race Engineer"
    SHORT_NAME = "ENG"
    START_BY_DEFAULT = False

    def __init__(self, common_cfg: PngAppMgrConfig):
        self.profile_path = default_race_engineer_launch_profile_path()
        self.profile = load_race_engineer_launch_profile(self.profile_path)
        self.common_args = common_cfg.args or []
        self._status_poll_stop = threading.Event()
        self._status_poll_thread: threading.Thread | None = None
        self.base_args = build_race_engineer_manager_args(
            self.common_args,
            common_cfg.debug_mode,
            self.profile,
        )

        config = replace(
            common_cfg,
            args=self.base_args,
            post_start_cb=self.post_start,
            post_stop_cb=self.post_stop,
        )
        super().__init__(config=config)

    def get_buttons(self) -> List[QPushButton]:
        self.start_stop_button = self.build_button(self.get_icon("start"), self.start_stop_callback, "Start")
        self.toggle_enabled_button = self.build_button(
            self.get_icon("show-hide"),
            self.toggle_enabled_callback,
            "Mute engineer",
        )
        self.voice_test_button = self.build_button(
            self.get_icon("updates"),
            self.voice_test_callback,
            "Voice test",
        )
        self.ask_question_button = self.build_button(
            self.get_icon("mfd-interact"),
            self.ask_question_callback,
            "Ask engineer",
        )
        self.settings_button = self.build_button(self.get_icon("settings"), self.open_settings_callback, "Settings")
        self.start_stop_button.setProperty("_png_enabled_when_stopped", True)
        self.toggle_enabled_button.setProperty("_png_enabled_when_stopped", False)
        self.voice_test_button.setProperty("_png_enabled_when_stopped", False)
        self.ask_question_button.setProperty("_png_enabled_when_stopped", False)
        self.settings_button.setProperty("_png_enabled_when_stopped", True)
        return [
            self.start_stop_button,
            self.toggle_enabled_button,
            self.voice_test_button,
            self.ask_question_button,
            self.settings_button,
        ]

    def on_settings_change(self, new_settings: PngSettings) -> bool:
        diff = self.curr_settings.diff(new_settings, {
            "Network": [
                "broker_xpub_port",
            ],
        })
        self.debug_log(f"{self.DISPLAY_NAME} Settings changed: {diff}")
        return bool(diff)

    def post_start(self) -> None:
        self.set_button_icon(self.start_stop_button, self.get_icon("stop"))
        self.set_button_tooltip(self.start_stop_button, "Stop")
        self.set_button_state(self.start_stop_button, True)
        self._set_live_control_state(True)
        self._set_toggle_tooltip(self.profile.initial_enabled)
        self.set_button_state(self.settings_button, True)
        self._start_status_polling()

    def post_stop(self) -> None:
        self._stop_status_polling()
        self.set_button_icon(self.start_stop_button, self.get_icon("start"))
        self.set_button_tooltip(self.start_stop_button, "Start")
        self.set_button_state(self.start_stop_button, True)
        self._set_live_control_state(False)
        self.set_button_state(self.settings_button, True)

    def start_stop_callback(self) -> None:
        self.set_button_state(self.start_stop_button, False)
        self._set_live_control_state(False)
        try:
            self.start_stop("Button pressed")
        except Exception as e: # pylint: disable=broad-exception-caught
            self.debug_log(f"{self.DISPLAY_NAME}: Error during start/stop: {e}")
            self.set_button_state(self.start_stop_button, True)
            self._set_live_control_state(self.is_running and self.ipc_port is not None)

    def start(self, reason: str):
        self._stop_status_polling()
        self._reload_profile_args()
        super().start(reason)

    def stop(self, reason: str):
        self._stop_status_polling()
        super().stop(reason)

    def open_settings_callback(self) -> None:
        from apps.launcher.gui.race_engineer_settings import RaceEngineerSettingsDialog

        dialog = RaceEngineerSettingsDialog(
            self.window,
            profile=self.profile,
            profile_path=self.profile_path,
        )
        if dialog.exec():
            self.profile = dialog.profile
            self._reload_profile_args()
            message = (
                "Race Engineer settings saved. Restart Race Engineer to apply launch options. "
                "Restart the backend to apply UDP action bindings."
            )
            self.show_success("Race Engineer Settings", message)

    def toggle_enabled_callback(self) -> None:
        rsp = self._request_live_command("toggle-enabled", {"announce": True})
        if not rsp:
            return
        enabled = bool(rsp.get("enabled", True))
        self._set_toggle_tooltip(enabled)

    def voice_test_callback(self) -> None:
        self._request_live_command("speak-test", {"text": "Radio check."})

    def ask_question_callback(self) -> None:
        question, ok = QInputDialog.getText(
            self.window,
            "Ask Race Engineer",
            "Question",
        )
        question = question.strip()
        if not ok or not question:
            return

        rsp = self._request_live_command(
            "ask-text",
            {"question": question},
            timeout_ms=race_engineer_live_question_timeout_ms(self.profile),
        )
        if not rsp:
            return

        answer = rsp.get("answer", {})
        if not bool(answer.get("ok", False)):
            self.show_error(
                "Race Engineer",
                str(answer.get("error") or "The assistant could not answer this question."),
            )
            return
        text = str(answer.get("text") or "").strip()
        if text:
            self.show_success("Race Engineer", text)
            return
        self.show_error("Race Engineer", "The assistant returned an empty answer.")

    def _reload_profile_args(self) -> None:
        self.profile = load_race_engineer_launch_profile(self.profile_path)
        self.args = build_race_engineer_manager_args(
            self.common_args,
            self.debug_mode,
            self.profile,
        )

    def _request_live_command(
            self,
            command: str,
            args: dict,
            *,
            timeout_ms: int = RACE_ENGINEER_FAST_LIVE_COMMAND_TIMEOUT_MS) -> dict | None:
        if not self.ipc_port:
            self.show_error(
                "Race Engineer Unavailable",
                "Race Engineer is still starting or is not running yet.",
            )
            return None

        client = IpcClientSync(self.ipc_port, timeout_ms=timeout_ms)
        try:
            rsp = client.request(command, args)
        finally:
            client.close()

        if rsp.get("status") != "success":
            self.show_error(
                "Race Engineer Command Failed",
                rsp.get("message", "The assistant did not accept the command."),
            )
            return None
        return rsp

    def _set_live_control_state(self, enabled: bool) -> None:
        self.set_button_state(self.toggle_enabled_button, enabled)
        self.set_button_state(self.voice_test_button, enabled)
        self.set_button_state(self.ask_question_button, enabled)

    def _set_toggle_tooltip(self, enabled: bool) -> None:
        tooltip = "Mute engineer" if enabled else "Unmute engineer"
        self.set_button_tooltip(self.toggle_enabled_button, tooltip)

    def _start_status_polling(self) -> None:
        self._stop_status_polling()
        self._status_poll_stop = threading.Event()
        self._status_poll_thread = threading.Thread(
            target=self._poll_runtime_status,
            args=(self._status_poll_stop,),
            daemon=True,
            name="Race Engineer-status-poll",
        )
        self._status_poll_thread.start()

    def _stop_status_polling(self) -> None:
        self._status_poll_stop.set()
        thread = self._status_poll_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._status_poll_thread = None

    def _poll_runtime_status(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            self._refresh_runtime_status()
            stop_event.wait(RACE_ENGINEER_STATUS_POLL_INTERVAL_SECONDS)

    def _refresh_runtime_status(self) -> None:
        if not self.is_running or self._is_stopping.is_set() or self._is_restarting.is_set():
            return

        port = self.ipc_port
        if not port:
            return

        client = IpcClientSync(port, timeout_ms=RACE_ENGINEER_STATUS_POLL_TIMEOUT_MS)
        try:
            rsp = client.get_stats()
        finally:
            client.close()

        if rsp.get("status") != "success":
            return

        stats = rsp.get("stats")
        if not isinstance(stats, dict):
            return

        self._stats = stats
        if not self.is_running or self._is_stopping.is_set() or self._is_restarting.is_set():
            return

        self._update_status(race_engineer_launcher_status_from_stats(stats))


def build_race_engineer_manager_args(
        base_args: List[str],
        debug_mode: bool,
        profile: RaceEngineerLaunchProfile) -> List[str]:
    """Build launcher subprocess args for the race engineer profile."""

    args = [*base_args, "--managed", *race_engineer_launch_profile_to_cli_args(profile)]
    if debug_mode:
        args.append("--debug")
    return args
