from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider


class ExtensionIconProvider(QFileIconProvider):
    def __init__(self, theme_mode: str = "dark") -> None:
        super().__init__()
        self._theme_mode = self._normalize_theme_mode(theme_mode)
        self._icon_cache: dict[tuple[str, str], QIcon] = {}

    def set_theme_mode(self, theme_mode: str) -> None:
        mode = self._normalize_theme_mode(theme_mode)
        if mode == self._theme_mode:
            return
        self._theme_mode = mode
        self._icon_cache.clear()

    def icon(self, file_info):
        if not hasattr(file_info, "isDir"):
            return super().icon(file_info)

        if file_info.isDir():
            return super().icon(file_info)

        label = self._file_label(file_info)
        cache_key = (self._theme_mode, label)
        cached_icon = self._icon_cache.get(cache_key)
        if cached_icon is not None:
            return cached_icon

        icon = self._create_badge_icon(label, self._accent_color_for_label(label))
        self._icon_cache[cache_key] = icon
        return icon

    def _normalize_theme_mode(self, theme_mode: str) -> str:
        mode = str(theme_mode).lower()
        return mode if mode in {"light", "dark"} else "dark"

    def _file_label(self, file_info: QFileInfo) -> str:
        suffix = Path(file_info.filePath()).suffix.lower()
        label_map = {
            ".c": "C",
            ".h": "h",
            ".cpp": "C++",
            ".cxx": "C++",
            ".cc": "C++",
            ".c++": "C++",
            ".hpp": "hpp",
            ".hh": "hh",
            ".hxx": "hxx",
            ".cs": "C#",
            ".c#": "C#",
            ".txt": "txt",
        }
        if suffix in label_map:
            return label_map[suffix]
        if suffix:
            return suffix.lstrip(".")[:3]
        return "file"

    def _accent_color_for_label(self, label: str) -> QColor:
        label = label.upper()
        if label in {"C", "C++", "C#"}:
            return QColor("#4fc1ff")
        if label in {"H", "HPP", "HH", "HXX"}:
            return QColor("#0e639c")
        if label == "CS":
            return QColor("#68217a")
        if label == "TXT":
            return QColor("#7a4e00")
        return QColor("#4b5563")

    def _create_badge_icon(self, label: str, accent_color: QColor) -> QIcon:
        size = QSize(28, 28)
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            font = QFont()
            font.setBold(True)
            if len(label) == 1:
                font.setPointSize(15)
            elif len(label) == 2:
                font.setPointSize(11)
            else:
                font.setPointSize(9)
            painter.setFont(font)

            shadow_color = QColor(0, 0, 0, 100)
            painter.setPen(shadow_color)
            painter.drawText(pixmap.rect().adjusted(1, 1, 1, 1), Qt.AlignmentFlag.AlignCenter, label)

            painter.setPen(QColor(accent_color))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, label)
        finally:
            painter.end()

        return QIcon(pixmap)