from __future__ import annotations

import ctypes
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import qInstallMessageHandler, QtMsgType, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

if __package__ in {None, ""}:
    # Allow running as `python src/app/main.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.app.config.storage import SettingsStorage
    from src.app.resources import asset_path
    from src.app.ui.main_window import MainWindow
else:
    from .config.storage import SettingsStorage
    from .resources import asset_path
    from .ui.main_window import MainWindow


_FATAL_ERROR_MESSAGE = "an error occured, please close and restart the application"
_fatal_error_reported = False


def _format_exception_details(exception: BaseException | None) -> str:
    if exception is None:
        return ""
    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))


def _report_fatal_error(details: str = "") -> None:
    global _fatal_error_reported
    if _fatal_error_reported:
        return

    _fatal_error_reported = True
    app = QApplication.instance()

    if app is not None:
        try:
            message_box = QMessageBox()
            message_box.setIcon(QMessageBox.Icon.Critical)
            message_box.setWindowTitle("Turbo C Editor")
            message_box.setText(_FATAL_ERROR_MESSAGE)
            message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            if not app.windowIcon().isNull():
                message_box.setWindowIcon(app.windowIcon())
            if details:
                message_box.setDetailedText(details)
            message_box.exec()
        except Exception:
            sys.stderr.write(f"{_FATAL_ERROR_MESSAGE}\n")
            if details:
                sys.stderr.write(f"{details}\n")
        finally:
            try:
                app.quit()
            except Exception:
                pass
        return

    sys.stderr.write(f"{_FATAL_ERROR_MESSAGE}\n")
    if details:
        sys.stderr.write(f"{details}\n")


def _handle_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    _report_fatal_error(_format_exception_details(exc_value))


def _handle_thread_exception(args) -> None:
    _handle_unhandled_exception(args.exc_type, args.exc_value, args.exc_traceback)


def _handle_qt_message(message_type: QtMsgType, context, message: str) -> None:
    if "Unable to open monitor interface to" in message:
        return

    if message_type in {QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg}:
        _report_fatal_error(message)
        return

    sys.stderr.write(f"{message}\n")


class TurboCApplication(QApplication):
    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except Exception as exception:
            _report_fatal_error(_format_exception_details(exception))
            return False


def _build_loading_splash(icon_path: Path) -> QSplashScreen:
    splash_pixmap = QPixmap(str(icon_path)) if icon_path.exists() else QPixmap()
    if splash_pixmap.isNull():
        splash_pixmap = QPixmap(520, 280)
        splash_pixmap.fill(QColor("#101722"))
    else:
        splash_pixmap = splash_pixmap.scaled(
            520,
            280,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    splash = QSplashScreen(splash_pixmap)
    splash.showMessage(
        "Loading Turbo C Editor...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#e6edf3"),
    )
    return splash


def _is_valid_directory_text(path_text: str) -> bool:
    if not str(path_text).strip():
        return False
    path = Path(path_text).expanduser()
    return path.exists() and path.is_dir()


def _should_show_loading_splash() -> bool:
    settings = SettingsStorage().load()
    return _is_valid_directory_text(settings.turboc_root) and _is_valid_directory_text(settings.project_root)


def main() -> int:
    qInstallMessageHandler(_handle_qt_message)
    sys.excepthook = _handle_unhandled_exception
    threading.excepthook = _handle_thread_exception
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Codinx.TurboCEditor")
        except Exception:
            pass

    app = TurboCApplication(sys.argv)
    app.setApplicationName("Turbo C Editor")
    app.setApplicationDisplayName("Turbo C Editor")
    app.setOrganizationName("Codinx")
    app.setApplicationVersion("1.0.0")

    splash: QSplashScreen | None = None
    try:
        app_icon_path = asset_path("dos-codinx.ico")
        if app_icon_path.exists():
            app_icon = QIcon(str(app_icon_path))
            app.setWindowIcon(app_icon)

        if _should_show_loading_splash():
            splash = _build_loading_splash(app_icon_path)
            splash.show()
            app.processEvents()

        window = MainWindow()
        if app_icon_path.exists():
            window.setWindowIcon(app.windowIcon())
        app.aboutToQuit.connect(window.shutdown)
        window.show()
        if splash is not None:
            splash.finish(window)
        exit_code = app.exec()
        return 1 if _fatal_error_reported else exit_code
    except Exception as exception:
        if splash is not None:
            splash.close()
        _report_fatal_error(_format_exception_details(exception))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
