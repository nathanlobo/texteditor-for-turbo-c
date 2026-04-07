from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

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
    app = QApplication(sys.argv)
    icon_path = Path(__file__).resolve().parent / "assets" / "icon.png"
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)
    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(app.windowIcon())
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
