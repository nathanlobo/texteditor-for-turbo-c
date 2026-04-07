from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config.settings import AppSettings
from ..config.storage import SettingsStorage
from ..domain.models import Severity
from ..services.diagnostics_parser import parse_diagnostics
from ..services.dosbox_service import DosBoxService
from ..services.turboc_service import TurboCService


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Turbo C Upgrade")
        self.resize(980, 700)

        self._storage = SettingsStorage()
        self._settings = self._storage.load()

        self._dosbox_service = DosBoxService()
        self._turbo_service = TurboCService(self._dosbox_service)
        self._exec_auto_fill_enabled = True

        self._init_ui()
        self._apply_settings_to_form()

    def _init_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setSpacing(12)

        form_layout = QFormLayout()
        self.dosbox_input = QLineEdit()
        self.turbo_input = QLineEdit()
        self.project_input = QLineEdit()
        self.source_input = QLineEdit("EXPT1.C")
        self.exec_input = QLineEdit("EXPT1.EXE")

        form_layout.addRow("DOSBox executable", self.dosbox_input)
        form_layout.addRow("Turbo C root", self.turbo_input)
        form_layout.addRow("Project root", self.project_input)
        form_layout.addRow("Source file", self.source_input)
        form_layout.addRow("Executable", self.exec_input)

        main_layout.addLayout(form_layout)

        button_row = QHBoxLayout()
        self.save_settings_btn = QPushButton("Save Settings")
        self.start_btn = QPushButton("Start Turbo C")
        self.stop_btn = QPushButton("Stop Session")
        self.compile_btn = QPushButton("Compile")
        self.run_btn = QPushButton("Run")

        button_row.addWidget(self.save_settings_btn)
        button_row.addWidget(self.start_btn)
        button_row.addWidget(self.stop_btn)
        button_row.addWidget(self.compile_btn)
        button_row.addWidget(self.run_btn)

        main_layout.addLayout(button_row)

        self.status_label = QLabel("Status: idle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(self.status_label)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Operation log and diagnostics appear here.")
        main_layout.addWidget(self.log_output)

        self.save_settings_btn.clicked.connect(self._on_save_settings)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.compile_btn.clicked.connect(self._on_compile)
        self.run_btn.clicked.connect(self._on_run)
        self.source_input.textChanged.connect(self._on_source_changed)
        self.exec_input.textEdited.connect(self._on_exec_edited)

    def _apply_settings_to_form(self) -> None:
        self.dosbox_input.setText(self._settings.dosbox_exe)
        self.turbo_input.setText(self._settings.turboc_root)
        self.project_input.setText(self._settings.project_root)

    def _derived_executable_name(self, source_file: str) -> str:
        source_name = source_file.strip()
        if not source_name:
            return ""

        base_name = Path(source_name).stem
        return f"{base_name}.EXE"

    def _on_source_changed(self, source_text: str) -> None:
        derived_executable = self._derived_executable_name(source_text)
        current_executable = self.exec_input.text().strip()

        if self._exec_auto_fill_enabled or not current_executable:
            self.exec_input.setText(derived_executable)

    def _on_exec_edited(self, _: str) -> None:
        self._exec_auto_fill_enabled = False

    def _collect_settings(self) -> AppSettings:
        return AppSettings(
            dosbox_exe=self.dosbox_input.text().strip(),
            turboc_root=self.turbo_input.text().strip(),
            project_root=self.project_input.text().strip(),
        )

    def _on_save_settings(self) -> None:
        settings = self._collect_settings()
        errors = settings.validate()
        if errors:
            self._show_error("Cannot save settings", "\n".join(errors))
            return

        self._storage.save(settings)
        self._settings = settings
        self._append_log("Settings saved.")

    def _on_start(self) -> None:
        if not self._ensure_valid_settings():
            return

        result = self._dosbox_service.start_turboc_session(
            self._settings.dosbox_exe,
            self._settings.turboc_root,
            self._settings.project_root,
        )
        self._update_status(result.output)
        self._append_log(result.output)

    def _on_stop(self) -> None:
        result = self._dosbox_service.stop_session()
        self._update_status(result.output)
        self._append_log(result.output)

    def _on_compile(self) -> None:
        if not self._ensure_valid_settings():
            return

        source = self.source_input.text().strip()
        result, diagnostics = self._turbo_service.compile(
            self._settings.dosbox_exe,
            self._settings.turboc_root,
            self._settings.project_root,
            source,
        )
        parsed = parse_diagnostics(result.output)
        error_count = sum(1 for d in parsed if d.severity == Severity.ERROR)
        warning_count = sum(1 for d in parsed if d.severity == Severity.WARNING)

        if error_count > 0:
            self._update_status(f"Compile failed: {error_count} error(s), {warning_count} warning(s)")
        elif warning_count > 0:
            self._update_status(f"Compile succeeded with {warning_count} warning(s)")
        elif not result.ok:
            code = result.return_code if result.return_code is not None else "unknown"
            self._update_status(f"Compile failed (exit code {code})")
        else:
            self._update_status("Compile succeeded")

        self._append_log("Compile output:\n" + (diagnostics or result.output or "(no output)"))

    def _on_run(self) -> None:
        if not self._ensure_valid_settings():
            return

        executable = self.exec_input.text().strip()
        result = self._turbo_service.run_program(
            self._settings.dosbox_exe,
            self._settings.turboc_root,
            self._settings.project_root,
            executable,
        )
        self._update_status("Run succeeded" if result.ok else "Run failed")
        self._append_log("Run output:\n" + (result.output or "(no output)"))
        self._append_log(
            "Tip: For graphics screenshots, use DOSBox Ctrl+F5. "
            "Windows Win+Shift+S can interrupt DOS keyboard focus and end the program."
        )

    def _ensure_valid_settings(self) -> bool:
        settings = self._collect_settings()
        errors = settings.validate()
        if errors:
            self._show_error("Invalid settings", "\n".join(errors))
            return False

        self._settings = settings
        return True

    def _append_log(self, text: str) -> None:
        self.log_output.appendPlainText(text)

    def _update_status(self, status: str) -> None:
        self.status_label.setText(f"Status: {status}")

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._dosbox_service.stop_session()
        super().closeEvent(event)
