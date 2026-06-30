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

from typing import Optional

from PySide6.QtCore import QProcess, Qt

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from apps.race_engineer.profile_voice_test import (
    DEFAULT_PROFILE_MIC_QUESTION_TEST_SECONDS,
    build_profile_audio_question_test_command,
    build_profile_mic_question_test_command,
    build_profile_preflight_command,
    build_profile_question_test_command,
    build_profile_voice_test_command,
    cleanup_temp_profile_for_smoke_test,
    format_profile_audio_question_test_output,
    format_profile_mic_question_test_output,
    format_profile_preflight_output,
    format_profile_question_test_output,
    write_temp_profile_for_smoke_test,
)
from lib.race_engineer import (
    RaceEngineerLaunchProfile,
    diagnose_race_engineer_launch_profile,
    format_race_engineer_profile_diagnostics,
    race_engineer_profile_has_errors,
    save_agent_prompt_override_template,
    save_race_engineer_launch_profile,
)

# -------------------------------------- CLASSES -----------------------------------------------------------------------


class RaceEngineerSettingsDialog(QDialog):
    """Launcher dialog for the race engineer launch profile."""

    def __init__(
        self,
        parent,
        *,
        profile: RaceEngineerLaunchProfile,
        profile_path: str,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.profile_path = profile_path
        self._voice_test_process: Optional[QProcess] = None
        self._voice_test_profile_path = ""
        self._question_test_process: Optional[QProcess] = None
        self._question_test_profile_path = ""
        self._audio_question_test_process: Optional[QProcess] = None
        self._audio_question_test_profile_path = ""
        self._mic_question_test_process: Optional[QProcess] = None
        self._mic_question_test_profile_path = ""
        self._preflight_process: Optional[QProcess] = None
        self._preflight_profile_path = ""
        self.setWindowTitle("Race Engineer Settings")
        self.setMinimumSize(760, 620)
        self._setup_ui()
        self._load_profile(profile)

    def _setup_ui(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #252526;
                color: #d4d4d4;
            }
            QTabWidget::pane {
                border: 1px solid #3e3e3e;
                background-color: #252526;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #d4d4d4;
                padding: 8px 14px;
                border: 1px solid #3e3e3e;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #0e639c;
            }
            QLabel {
                color: #d4d4d4;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
                padding: 5px;
                min-height: 24px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #0e639c;
            }
            QCheckBox {
                color: #d4d4d4;
                spacing: 8px;
            }
            QPushButton {
                background-color: #3e3e3e;
                color: #d4d4d4;
                border: 1px solid #4e4e4e;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #0e639c;
                border-color: #1177bb;
            }
        """)

        root = QVBoxLayout()
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        title = QLabel("Race Engineer")
        title.setFont(QFont("Formula1", 14, QFont.Weight.Bold))
        title.setStyleSheet("background-color: transparent;")
        root.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_voice_tab(), "Voice")
        self.tabs.addTab(self._build_questions_tab(), "Questions")
        self.tabs.addTab(self._build_prompts_tab(), "Prompts")
        self.tabs.addTab(self._build_controls_tab(), "Controls")
        root.addWidget(self.tabs, stretch=1)

        buttons = QHBoxLayout()
        check = QPushButton("Check")
        check.clicked.connect(self._on_check)
        buttons.addWidget(check)
        self.voice_test_button = QPushButton("Voice Test")
        self.voice_test_button.clicked.connect(self._on_voice_test)
        buttons.addWidget(self.voice_test_button)
        self.question_test_button = QPushButton("Question Test")
        self.question_test_button.clicked.connect(self._on_question_test)
        buttons.addWidget(self.question_test_button)
        self.audio_question_test_button = QPushButton("Audio Q Test")
        self.audio_question_test_button.clicked.connect(self._on_audio_question_test)
        buttons.addWidget(self.audio_question_test_button)
        self.mic_question_test_button = QPushButton("Mic PTT Test")
        self.mic_question_test_button.clicked.connect(self._on_mic_question_test)
        buttons.addWidget(self.mic_question_test_button)
        self.preflight_button = QPushButton("Preflight")
        self.preflight_button.clicked.connect(self._on_preflight)
        buttons.addWidget(self.preflight_button)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self.setLayout(root)

    def _build_general_tab(self) -> QWidget:
        tab, form = self._tab_with_form()
        self.initial_enabled = QCheckBox()
        self.focus = _combo(["all", "pace", "tyres", "fuel", "ers", "damage", "weather", "strategy",
                             "race_control", "driving_coach"])
        self.min_priority = _combo(["critical", "warning", "advisory", "info"])
        self.cooldown_seconds = _spin(1, 300)
        self.min_voice_interval_seconds = _double_spin(0.0, 60.0, 1)
        self.max_items = _spin(1, 10)
        self.max_queue_size = _spin(1, 10)

        form.addRow("Start online", self.initial_enabled)
        form.addRow("Default focus", self.focus)
        form.addRow("Minimum priority", self.min_priority)
        form.addRow("Cooldown seconds", self.cooldown_seconds)
        form.addRow("Minimum voice interval", self.min_voice_interval_seconds)
        form.addRow("Advice items per snapshot", self.max_items)
        form.addRow("Voice queue size", self.max_queue_size)
        return tab

    def _build_voice_tab(self) -> QWidget:
        tab, form = self._tab_with_form()
        self.voice_provider = _combo(["dry_run", "azure", "disabled"])
        self.azure_region = QLineEdit()
        self.azure_speech_endpoint = QLineEdit()
        self.azure_voice = QLineEdit()
        self.azure_key_env_var = QLineEdit()
        self.azure_output_format = QLineEdit()
        self.no_audio_playback = QCheckBox()
        self.speech_recognition_provider = _combo(["disabled", "azure"])
        self.azure_stt_language = QLineEdit()
        self.azure_stt_format = QLineEdit()
        self.azure_stt_content_type = QLineEdit()
        self.push_to_talk_audio_source = _combo(["external", "windows_microphone"])

        form.addRow("Voice provider", self.voice_provider)
        form.addRow("Azure region", self.azure_region)
        form.addRow("Azure endpoint", self.azure_speech_endpoint)
        form.addRow("Azure voice", self.azure_voice)
        form.addRow("Azure key env var", self.azure_key_env_var)
        form.addRow("Azure output format", self.azure_output_format)
        form.addRow("Discard playback audio", self.no_audio_playback)
        form.addRow("Speech recognition", self.speech_recognition_provider)
        form.addRow("STT language", self.azure_stt_language)
        form.addRow("STT format", self.azure_stt_format)
        form.addRow("STT content type", self.azure_stt_content_type)
        form.addRow("Push-to-talk audio", self.push_to_talk_audio_source)
        return tab

    def _build_questions_tab(self) -> QWidget:
        tab, form = self._tab_with_form()
        self.conversation_provider = _combo(["local_brief", "http", "codex_cli"])
        self.conversation_endpoint = QLineEdit()
        self.conversation_key_env_var = QLineEdit()
        self.conversation_command = QLineEdit()
        self.conversation_timeout_seconds = _double_spin(0.1, 120.0, 1)

        form.addRow("Answer provider", self.conversation_provider)
        form.addRow("HTTP endpoint", self.conversation_endpoint)
        form.addRow("HTTP key env var", self.conversation_key_env_var)
        form.addRow("CLI command", self.conversation_command)
        form.addRow("Answer timeout seconds", self.conversation_timeout_seconds)
        return tab

    def _build_prompts_tab(self) -> QWidget:
        tab, form = self._tab_with_form()
        self.agent_prompts_file = QLineEdit()
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_agent_prompts)
        create = QPushButton("Create Template")
        create.clicked.connect(self._create_agent_prompts_template)
        row = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(self.agent_prompts_file, stretch=1)
        row_layout.addWidget(browse)
        row_layout.addWidget(create)
        row.setLayout(row_layout)
        form.addRow("Agent prompts JSON", row)
        return tab

    def _build_controls_tab(self) -> QWidget:
        tab, form = self._tab_with_form()
        self.race_engineer_toggle_udp_action_code = _udp_spin()
        self.race_engineer_push_to_talk_udp_action_code = _udp_spin()
        form.addRow("Toggle engineer UDP action", self.race_engineer_toggle_udp_action_code)
        form.addRow("Push-to-talk UDP action", self.race_engineer_push_to_talk_udp_action_code)
        note = QLabel("UDP action bindings are read by the backend when it starts.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9cdcfe; background-color: transparent;")
        form.addRow("", note)
        return tab

    def _tab_with_form(self) -> tuple[QWidget, QFormLayout]:
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        layout.addLayout(form)
        layout.addStretch()
        tab.setLayout(layout)
        return tab, form

    def _load_profile(self, profile: RaceEngineerLaunchProfile) -> None:
        self.initial_enabled.setChecked(profile.initial_enabled)
        _set_combo(self.focus, profile.focus)
        _set_combo(self.min_priority, profile.min_priority)
        self.cooldown_seconds.setValue(profile.cooldown_seconds)
        self.min_voice_interval_seconds.setValue(profile.min_voice_interval_seconds)
        self.max_items.setValue(profile.max_items)
        self.max_queue_size.setValue(profile.max_queue_size)

        _set_combo(self.voice_provider, profile.voice_provider)
        self.azure_region.setText(profile.azure_region)
        self.azure_speech_endpoint.setText(profile.azure_speech_endpoint)
        self.azure_voice.setText(profile.azure_voice)
        self.azure_key_env_var.setText(profile.azure_key_env_var)
        self.azure_output_format.setText(profile.azure_output_format)
        self.no_audio_playback.setChecked(profile.no_audio_playback)
        _set_combo(self.speech_recognition_provider, profile.speech_recognition_provider)
        self.azure_stt_language.setText(profile.azure_stt_language)
        self.azure_stt_format.setText(profile.azure_stt_format)
        self.azure_stt_content_type.setText(profile.azure_stt_content_type)
        _set_combo(self.push_to_talk_audio_source, profile.push_to_talk_audio_source)

        _set_combo(self.conversation_provider, profile.conversation_provider)
        self.conversation_endpoint.setText(profile.conversation_endpoint)
        self.conversation_key_env_var.setText(profile.conversation_key_env_var)
        self.conversation_command.setText(profile.conversation_command)
        self.conversation_timeout_seconds.setValue(profile.conversation_timeout_seconds)

        self.agent_prompts_file.setText(profile.agent_prompts_file)
        _set_udp_spin(self.race_engineer_toggle_udp_action_code, profile.race_engineer_toggle_udp_action_code)
        _set_udp_spin(
            self.race_engineer_push_to_talk_udp_action_code,
            profile.race_engineer_push_to_talk_udp_action_code,
        )

    def _profile_from_widgets(self) -> RaceEngineerLaunchProfile:
        return RaceEngineerLaunchProfile(
            initial_enabled=self.initial_enabled.isChecked(),
            focus=self.focus.currentText(),
            min_priority=self.min_priority.currentText(),
            cooldown_seconds=self.cooldown_seconds.value(),
            min_voice_interval_seconds=self.min_voice_interval_seconds.value(),
            max_items=self.max_items.value(),
            max_queue_size=self.max_queue_size.value(),
            voice_provider=self.voice_provider.currentText(),
            azure_region=self.azure_region.text().strip(),
            azure_speech_endpoint=self.azure_speech_endpoint.text().strip(),
            azure_voice=self.azure_voice.text().strip(),
            azure_key_env_var=self.azure_key_env_var.text().strip(),
            azure_output_format=self.azure_output_format.text().strip(),
            no_audio_playback=self.no_audio_playback.isChecked(),
            speech_recognition_provider=self.speech_recognition_provider.currentText(),
            azure_stt_language=self.azure_stt_language.text().strip(),
            azure_stt_format=self.azure_stt_format.text().strip(),
            azure_stt_content_type=self.azure_stt_content_type.text().strip(),
            push_to_talk_audio_source=self.push_to_talk_audio_source.currentText(),
            conversation_provider=self.conversation_provider.currentText(),
            conversation_endpoint=self.conversation_endpoint.text().strip(),
            conversation_key_env_var=self.conversation_key_env_var.text().strip(),
            conversation_command=self.conversation_command.text().strip(),
            conversation_timeout_seconds=self.conversation_timeout_seconds.value(),
            agent_prompts_file=self.agent_prompts_file.text().strip(),
            race_engineer_toggle_udp_action_code=_udp_spin_value(self.race_engineer_toggle_udp_action_code),
            race_engineer_push_to_talk_udp_action_code=_udp_spin_value(
                self.race_engineer_push_to_talk_udp_action_code),
        )

    def _browse_agent_prompts(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select agent prompts JSON",
            self.agent_prompts_file.text().strip() or "",
            "JSON files (*.json);;All files (*.*)",
        )
        if path:
            self.agent_prompts_file.setText(path)

    def _create_agent_prompts_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Create agent prompts template",
            self.agent_prompts_file.text().strip() or "race-engineer-prompts.json",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            saved_path = save_agent_prompt_override_template(path, overwrite=True)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Prompt Template Error",
                f"Could not create agent prompts template:\n{exc}",
            )
            return
        self.agent_prompts_file.setText(saved_path)
        QMessageBox.information(
            self,
            "Prompt Template Created",
            "Agent prompts template created. Edit the JSON fields you want to override.",
        )

    def _on_save(self) -> None:
        profile = self._profile_from_widgets()
        if (
                profile.race_engineer_toggle_udp_action_code is not None
                and profile.race_engineer_toggle_udp_action_code
                == profile.race_engineer_push_to_talk_udp_action_code):
            QMessageBox.warning(
                self,
                "Invalid UDP Actions",
                "Toggle and push-to-talk must use different UDP action codes.",
            )
            return

        save_race_engineer_launch_profile(profile, self.profile_path)
        self.profile = profile
        self.accept()

    def _on_check(self) -> None:
        diagnostics = diagnose_race_engineer_launch_profile(self._profile_from_widgets())
        message = format_race_engineer_profile_diagnostics(diagnostics)
        if race_engineer_profile_has_errors(diagnostics):
            QMessageBox.warning(self, "Race Engineer Check", message)
        else:
            QMessageBox.information(self, "Race Engineer Check", message)

    def _on_voice_test(self) -> None:
        if self._voice_test_process is not None:
            return

        profile = self._profile_from_widgets()
        diagnostics = diagnose_race_engineer_launch_profile(profile)
        voice_errors = [
            item for item in diagnostics
            if item.severity == "error" and item.code.startswith("azure-tts")
        ]
        if voice_errors:
            QMessageBox.warning(
                self,
                "Race Engineer Voice Test",
                format_race_engineer_profile_diagnostics(voice_errors),
            )
            return

        try:
            self._voice_test_profile_path = write_temp_profile_for_smoke_test(profile)
            command = build_profile_voice_test_command(self._voice_test_profile_path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Race Engineer Voice Test",
                f"Could not prepare voice test:\n{exc}",
            )
            return

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(self._on_voice_test_finished)
        process.errorOccurred.connect(self._on_voice_test_error)
        self._voice_test_process = process
        self.voice_test_button.setEnabled(False)
        process.start(command[0], command[1:])

    def _on_voice_test_finished(self, exit_code: int, _exit_status) -> None:
        process = self._voice_test_process
        output = ""
        if process is not None:
            output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        self._cleanup_voice_test_process()
        if exit_code == 0:
            QMessageBox.information(self, "Race Engineer Voice Test", "Voice test completed.")
            return
        message = "Voice test failed."
        if output:
            message = f"{message}\n\n{_last_lines(output)}"
        QMessageBox.warning(self, "Race Engineer Voice Test", message)

    def _on_voice_test_error(self, _error) -> None:
        process = self._voice_test_process
        error_text = process.errorString() if process is not None else "Process failed to start."
        self._cleanup_voice_test_process()
        QMessageBox.warning(
            self,
            "Race Engineer Voice Test",
            f"Could not start voice test:\n{error_text}",
        )

    def _cleanup_voice_test_process(self) -> None:
        if self._voice_test_process is not None:
            self._voice_test_process.deleteLater()
            self._voice_test_process = None
        if self._voice_test_profile_path:
            cleanup_temp_profile_for_smoke_test(self._voice_test_profile_path)
            self._voice_test_profile_path = ""
        self.voice_test_button.setEnabled(True)

    def _on_question_test(self) -> None:
        if self._question_test_process is not None:
            return

        question, ok = QInputDialog.getText(
            self,
            "Race Engineer Question Test",
            "Question",
            text="what should I know?",
        )
        question = question.strip()
        if not ok or not question:
            return

        profile = self._profile_from_widgets()
        diagnostics = diagnose_race_engineer_launch_profile(profile)
        question_errors = [
            item for item in diagnostics
            if item.severity == "error"
            and (item.code.startswith("conversation-") or item.code == "agent-prompts-file-missing")
        ]
        if question_errors:
            QMessageBox.warning(
                self,
                "Race Engineer Question Test",
                format_race_engineer_profile_diagnostics(question_errors),
            )
            return

        try:
            self._question_test_profile_path = write_temp_profile_for_smoke_test(profile)
            command = build_profile_question_test_command(
                self._question_test_profile_path,
                question=question,
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Race Engineer Question Test",
                f"Could not prepare question test:\n{exc}",
            )
            return

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(self._on_question_test_finished)
        process.errorOccurred.connect(self._on_question_test_error)
        self._question_test_process = process
        self.question_test_button.setEnabled(False)
        process.start(command[0], command[1:])

    def _on_question_test_finished(self, exit_code: int, _exit_status) -> None:
        process = self._question_test_process
        output = ""
        if process is not None:
            output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        self._cleanup_question_test_process()
        if exit_code == 0:
            QMessageBox.information(
                self,
                "Race Engineer Question Test",
                format_profile_question_test_output(output),
            )
            return
        message = "Question test failed."
        if output:
            message = f"{message}\n\n{_last_lines(output)}"
        QMessageBox.warning(self, "Race Engineer Question Test", message)

    def _on_question_test_error(self, _error) -> None:
        process = self._question_test_process
        error_text = process.errorString() if process is not None else "Process failed to start."
        self._cleanup_question_test_process()
        QMessageBox.warning(
            self,
            "Race Engineer Question Test",
            f"Could not start question test:\n{error_text}",
        )

    def _cleanup_question_test_process(self) -> None:
        if self._question_test_process is not None:
            self._question_test_process.deleteLater()
            self._question_test_process = None
        if self._question_test_profile_path:
            cleanup_temp_profile_for_smoke_test(self._question_test_profile_path)
            self._question_test_profile_path = ""
        self.question_test_button.setEnabled(True)

    def _on_audio_question_test(self) -> None:
        if self._audio_question_test_process is not None:
            return

        audio_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select audio question",
            "",
            "Audio files (*.wav *.wave);;All files (*.*)",
        )
        if not audio_path:
            return

        profile = self._profile_from_widgets()
        diagnostics = diagnose_race_engineer_launch_profile(profile)
        audio_errors = [
            item for item in diagnostics
            if item.severity == "error"
            and (
                item.code.startswith("azure-stt")
                or item.code.startswith("azure-tts")
                or item.code.startswith("conversation-")
                or item.code == "agent-prompts-file-missing"
            )
        ]
        if profile.speech_recognition_provider == "disabled":
            QMessageBox.warning(
                self,
                "Race Engineer Audio Question Test",
                "Speech recognition must be set to azure for an audio question test.",
            )
            return
        if audio_errors:
            QMessageBox.warning(
                self,
                "Race Engineer Audio Question Test",
                format_race_engineer_profile_diagnostics(audio_errors),
            )
            return

        try:
            self._audio_question_test_profile_path = write_temp_profile_for_smoke_test(profile)
            command = build_profile_audio_question_test_command(
                self._audio_question_test_profile_path,
                audio_path,
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Race Engineer Audio Question Test",
                f"Could not prepare audio question test:\n{exc}",
            )
            return

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(self._on_audio_question_test_finished)
        process.errorOccurred.connect(self._on_audio_question_test_error)
        self._audio_question_test_process = process
        self.audio_question_test_button.setEnabled(False)
        process.start(command[0], command[1:])

    def _on_audio_question_test_finished(self, exit_code: int, _exit_status) -> None:
        process = self._audio_question_test_process
        output = ""
        if process is not None:
            output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        self._cleanup_audio_question_test_process()
        message = format_profile_audio_question_test_output(output)
        if exit_code == 0:
            QMessageBox.information(self, "Race Engineer Audio Question Test", message)
            return
        QMessageBox.warning(self, "Race Engineer Audio Question Test", message)

    def _on_audio_question_test_error(self, _error) -> None:
        process = self._audio_question_test_process
        error_text = process.errorString() if process is not None else "Process failed to start."
        self._cleanup_audio_question_test_process()
        QMessageBox.warning(
            self,
            "Race Engineer Audio Question Test",
            f"Could not start audio question test:\n{error_text}",
        )

    def _cleanup_audio_question_test_process(self) -> None:
        if self._audio_question_test_process is not None:
            self._audio_question_test_process.deleteLater()
            self._audio_question_test_process = None
        if self._audio_question_test_profile_path:
            cleanup_temp_profile_for_smoke_test(self._audio_question_test_profile_path)
            self._audio_question_test_profile_path = ""
        self.audio_question_test_button.setEnabled(True)

    def _on_mic_question_test(self) -> None:
        if self._mic_question_test_process is not None:
            return

        seconds, ok = QInputDialog.getDouble(
            self,
            "Race Engineer Mic PTT Test",
            "Recording seconds",
            DEFAULT_PROFILE_MIC_QUESTION_TEST_SECONDS,
            0.5,
            15.0,
            1,
        )
        if not ok:
            return

        profile = self._profile_from_widgets()
        diagnostics = diagnose_race_engineer_launch_profile(profile)
        mic_errors = [
            item for item in diagnostics
            if item.severity == "error"
            and (
                item.code.startswith("azure-stt")
                or item.code.startswith("azure-tts")
                or item.code.startswith("conversation-")
                or item.code == "agent-prompts-file-missing"
                or item.code == "ptt-windows-microphone-platform"
            )
        ]
        if profile.speech_recognition_provider == "disabled":
            QMessageBox.warning(
                self,
                "Race Engineer Mic PTT Test",
                "Speech recognition must be set to azure for a microphone question test.",
            )
            return
        if profile.push_to_talk_audio_source != "windows_microphone":
            QMessageBox.warning(
                self,
                "Race Engineer Mic PTT Test",
                "Push-to-talk audio must be set to windows_microphone for a microphone question test.",
            )
            return
        if mic_errors:
            QMessageBox.warning(
                self,
                "Race Engineer Mic PTT Test",
                format_race_engineer_profile_diagnostics(mic_errors),
            )
            return

        try:
            self._mic_question_test_profile_path = write_temp_profile_for_smoke_test(profile)
            command = build_profile_mic_question_test_command(
                self._mic_question_test_profile_path,
                seconds=seconds,
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Race Engineer Mic PTT Test",
                f"Could not prepare microphone question test:\n{exc}",
            )
            return

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(self._on_mic_question_test_finished)
        process.errorOccurred.connect(self._on_mic_question_test_error)
        self._mic_question_test_process = process
        self.mic_question_test_button.setEnabled(False)
        process.start(command[0], command[1:])

    def _on_mic_question_test_finished(self, exit_code: int, _exit_status) -> None:
        process = self._mic_question_test_process
        output = ""
        if process is not None:
            output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        self._cleanup_mic_question_test_process()
        message = format_profile_mic_question_test_output(output)
        if exit_code == 0:
            QMessageBox.information(self, "Race Engineer Mic PTT Test", message)
            return
        QMessageBox.warning(self, "Race Engineer Mic PTT Test", message)

    def _on_mic_question_test_error(self, _error) -> None:
        process = self._mic_question_test_process
        error_text = process.errorString() if process is not None else "Process failed to start."
        self._cleanup_mic_question_test_process()
        QMessageBox.warning(
            self,
            "Race Engineer Mic PTT Test",
            f"Could not start microphone question test:\n{error_text}",
        )

    def _cleanup_mic_question_test_process(self) -> None:
        if self._mic_question_test_process is not None:
            self._mic_question_test_process.deleteLater()
            self._mic_question_test_process = None
        if self._mic_question_test_profile_path:
            cleanup_temp_profile_for_smoke_test(self._mic_question_test_profile_path)
            self._mic_question_test_profile_path = ""
        self.mic_question_test_button.setEnabled(True)

    def _on_preflight(self) -> None:
        if self._preflight_process is not None:
            return

        try:
            self._preflight_profile_path = write_temp_profile_for_smoke_test(self._profile_from_widgets())
            command = build_profile_preflight_command(self._preflight_profile_path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Race Engineer Preflight",
                f"Could not prepare preflight:\n{exc}",
            )
            return

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(self._on_preflight_finished)
        process.errorOccurred.connect(self._on_preflight_error)
        self._preflight_process = process
        self.preflight_button.setEnabled(False)
        process.start(command[0], command[1:])

    def _on_preflight_finished(self, exit_code: int, _exit_status) -> None:
        process = self._preflight_process
        output = ""
        if process is not None:
            output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        self._cleanup_preflight_process()
        message = format_profile_preflight_output(output)
        if exit_code == 0:
            QMessageBox.information(self, "Race Engineer Preflight", message)
            return
        QMessageBox.warning(self, "Race Engineer Preflight", message)

    def _on_preflight_error(self, _error) -> None:
        process = self._preflight_process
        error_text = process.errorString() if process is not None else "Process failed to start."
        self._cleanup_preflight_process()
        QMessageBox.warning(
            self,
            "Race Engineer Preflight",
            f"Could not start preflight:\n{error_text}",
        )

    def _cleanup_preflight_process(self) -> None:
        if self._preflight_process is not None:
            self._preflight_process.deleteLater()
            self._preflight_process = None
        if self._preflight_profile_path:
            cleanup_temp_profile_for_smoke_test(self._preflight_profile_path)
            self._preflight_profile_path = ""
        self.preflight_button.setEnabled(True)


# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def _combo(values: list[str]) -> QComboBox:
    combo = QComboBox()
    combo.addItems(values)
    return combo


def _set_combo(combo: QComboBox, value: str) -> None:
    index = combo.findText(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _spin(minimum: int, maximum: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    return spin


def _double_spin(minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSingleStep(0.5)
    return spin


def _udp_spin() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 12)
    spin.setSpecialValueText("Not bound")
    return spin


def _set_udp_spin(spin: QSpinBox, value: Optional[int]) -> None:
    spin.setValue(value or 0)


def _udp_spin_value(spin: QSpinBox) -> Optional[int]:
    value = spin.value()
    return value if value > 0 else None


def _last_lines(text: str, *, max_chars: int = 1600) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return "...\n" + text[-max_chars:]
