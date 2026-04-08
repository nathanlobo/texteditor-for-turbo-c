from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .resources import asset_path

if __package__ in {None, ""}:
    # Allow running as `python src/app/main.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.app.ui.main_window import MainWindow
else:
    from .ui.main_window import MainWindow


def _filter_qt_monitor_warning(message_type: QtMsgType, context, message: str) -> None:
    if "Unable to open monitor interface to" in message:
        return

    sys.stderr.write(f"{message}\n")


def main() -> int:
    qInstallMessageHandler(_filter_qt_monitor_warning)
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Codinx.TurboCEditor")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Turbo C Editor")
    app.setApplicationDisplayName("Turbo C Editor By Nathan Lobo")
    app.setOrganizationName("Codinx")
    app.setApplicationVersion("1.0.0")

    app_icon_path = asset_path("dos-codinx.ico")
    if app_icon_path.exists():
        app_icon = QIcon(str(app_icon_path))
        app.setWindowIcon(app_icon)
    window = MainWindow()
    if app_icon_path.exists():
        window.setWindowIcon(app.windowIcon())
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
