from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QByteArray, QFile, QDir, QEvent, QPoint, QRectF, QSize, Qt, QTimer, QUrl, QMimeData
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QFontDatabase, QIcon, QKeyEvent, QKeySequence, QPalette, QPainter, QPen, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QFileDialog,
    QFileSystemModel,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QTreeView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config.settings import AppSettings, resolve_dosbox_executable_path
from ..config.storage import SettingsStorage
from ..domain.models import Severity
from ..resources import asset_path
from ..services.diagnostics_parser import parse_diagnostics
from ..services.dosbox_service import DosBoxService
from ..services.turboc_service import TurboCService
from .file_icon_provider import ExtensionIconProvider
from .syntax_highlighter import CFamilySyntaxHighlighter


class CodeEditor(QPlainTextEdit):
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Tab and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertText("    ")
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return

        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                block_text = cursor.block().text()
                leading_whitespace = []
                for character in block_text:
                    if character in {" ", "\t"}:
                        leading_whitespace.append(character)
                    else:
                        break

                cursor.beginEditBlock()
                cursor.insertBlock()
                if leading_whitespace:
                    cursor.insertText("".join(leading_whitespace))
                cursor.endEditBlock()
                self.setTextCursor(cursor)
                return

        super().keyPressEvent(event)


class ThemeSwitch(QCheckBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_mode = "light"
        self.setText("")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_theme_mode(self, theme_mode: str) -> None:
        mode = str(theme_mode).lower()
        if mode not in {"light", "dark"}:
            mode = "light"
        if mode == self._theme_mode:
            return
        self._theme_mode = mode
        self.update()

    def sizeHint(self) -> QSize:
        height = max(18, self.fontMetrics().height() + 6)
        width = max(34, round(height * 1.9))
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            if rect.width() <= 0 or rect.height() <= 0:
                return

            checked = self.isChecked()
            enabled = self.isEnabled()

            if self._theme_mode == "dark":
                off_track = QColor("#4b4b4b")
                off_border = QColor("#5a5a5a")
                on_track = QColor("#0e639c")
                on_border = QColor("#1177bb")
                knob_fill = QColor("#f8f9fb")
                knob_border = QColor("#c8d0da")
                shadow = QColor(0, 0, 0, 70)
                focus = QColor("#4fc1ff")
                disabled_track = QColor("#343434")
                disabled_border = QColor("#474747")
            else:
                off_track = QColor("#d0d7de")
                off_border = QColor("#b7c0ca")
                on_track = QColor("#0e639c")
                on_border = QColor("#0d5a8c")
                knob_fill = QColor("#ffffff")
                knob_border = QColor("#b8c2cc")
                shadow = QColor(0, 0, 0, 35)
                focus = QColor("#0e639c")
                disabled_track = QColor("#d7dbe0")
                disabled_border = QColor("#c4ccd5")

            track_color = on_track if checked else off_track
            border_color = on_border if checked else off_border
            if not enabled:
                track_color = disabled_track
                border_color = disabled_border

            radius = rect.height() / 2.0
            painter.setPen(QPen(border_color, 1))
            painter.setBrush(track_color)
            painter.drawRoundedRect(rect, radius, radius)

            knob_margin = max(2, round(rect.height() * 0.16))
            knob_size = rect.height() - (knob_margin * 2)
            if knob_size > 0:
                knob_y = rect.top() + knob_margin
                if checked:
                    knob_x = rect.right() - knob_margin - knob_size
                else:
                    knob_x = rect.left() + knob_margin

                knob_rect = QRectF(knob_x, knob_y, knob_size, knob_size)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(shadow)
                painter.drawEllipse(knob_rect.translated(1, 1))
                painter.setBrush(knob_fill)
                painter.drawEllipse(knob_rect)
                painter.setPen(QPen(knob_border, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(knob_rect)

            if self.hasFocus():
                focus_color = QColor(focus)
                focus_color.setAlpha(120)
                painter.setPen(QPen(focus_color, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
        finally:
            painter.end()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Turbo C Editor By Nathan Lobo")
        self._about_version = "1.0.0"
        self.resize(1440, 900)

        self._storage = SettingsStorage()
        self._settings = self._storage.load()
        self._theme_mode = self._normalize_theme_mode(self._settings.theme_mode)
        self._settings.theme_mode = self._theme_mode
        self._workspace_root = self._initial_workspace_root()
        self._selected_source_file: Path | None = None
        self._current_editor_file: Path | None = None
        self._editor_dirty = False
        self._updating_editor_programmatically = False
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(600)
        self._auto_save_timer.timeout.connect(self._flush_pending_auto_save)
        self._fullscreen_restore_mode = "normal"
        self._window_mode_restored = False
        self._zoom_base_scale = 0.92
        self._zoom_step = 0.08
        self._zoom_min_level = -2
        self._zoom_max_level = 8
        self._zoom_level = max(
            self._zoom_min_level,
            min(self._zoom_max_level, int(getattr(self._settings, "zoom_level", 0))),
        )
        self._settings.zoom_level = self._zoom_level
        self._ui_scale = self._zoom_base_scale + (self._zoom_step * self._zoom_level)
        self._output_panel_visible = True
        self._code_highlighter: CFamilySyntaxHighlighter | None = None

        self._dosbox_service = DosBoxService()
        self._turbo_service = TurboCService(self._dosbox_service)
        self._recent_logo_path = asset_path("dos-codinx.ico")
        self._logo_path = asset_path("icon.png")
        self._settings_icon_path = asset_path("settings.svg")
        self._notification_icon_path = asset_path("bell.svg")
        self._zoom_icon_path = asset_path("zoom.svg")
        self._about_github_icon_path = asset_path("about-github.svg")
        self._about_email_icon_path = asset_path("about-email.svg")
        self._about_whatsapp_icon_path = asset_path("about-whatsapp.svg")
        self._workspace_icon_provider = ExtensionIconProvider(self._theme_mode)
        self._startup_prompt_shown = False
        self._about_icon_cache: dict[str, QIcon] = {}
        self._codinx_site_url = "https://codinx.app"
        self._codinx_support_url = "https://codinx.app/support"
        self._about_social_links = {
            "GitHub": "https://github.com/nathanlobo",
            "Email": "mailto:lobonathan2209@gmail.com",
            "WhatsApp": "https://wa.me/+919689137817",
            "Support": self._codinx_support_url,
        }

        self._build_actions()
        self._build_menus()
        self._build_ui()
        self._apply_theme()
        self._apply_settings_to_form()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._restore_window_geometry()
        self._set_workspace_root(self._workspace_root, sync_project_input=bool(self._settings.project_root))
        self._refresh_source_display()
        self._refresh_view_actions()
        self._refresh_action_states()

    def _initial_workspace_root(self) -> Path:
        project_root = Path(self._settings.project_root) if self._settings.project_root else Path.cwd()
        return project_root if project_root.exists() else Path.cwd()

    def _build_actions(self) -> None:
        self.act_new_text = self._action("New Text File", self._on_new_file, shortcut="Ctrl+N")
        self.act_new_file = self._action("New File...", self._on_new_file)
        self.act_new_window = self._action("New Window", enabled=False)
        self.act_new_window_profile = self._action("New Window with Profile", enabled=False)
        self.act_open_file = self._action("Open File...", self._on_open_file, shortcut="Ctrl+O")
        self.act_open_folder = self._action("Open Folder...", self._on_open_workspace_folder)
        self.act_open_workspace_from_file = self._action("Open Workspace from File...", enabled=False)
        self.act_open_recent = self._action("Open Recent", enabled=False)
        self.act_add_folder = self._action("Add Folder to Workspace...", self._on_open_workspace_folder)
        self.act_save_workspace_as = self._action("Save Workspace As...", enabled=False)
        self.act_duplicate_workspace = self._action("Duplicate Workspace", enabled=False)
        self.act_save = self._action("Save", self._on_save_file, shortcut="Ctrl+S")
        self.act_save_as = self._action("Save As...", self._on_save_as, shortcut="Ctrl+Shift+S")
        self.act_save_all = self._action("Save All", enabled=False)
        self.act_share = self._action("Share", enabled=False)
        self.act_auto_save = self._action("Auto Save", enabled=False)
        self.act_preferences = self._action("Preferences", self._toggle_settings_panel)
        self.act_revert_file = self._action("Revert File", self._on_revert_file)
        self.act_close_editor = self._action("Close Editor", self._on_close_editor)
        self.act_close_folder = self._action("Close Folder", enabled=False)
        self.act_close_window = self._action("Close Window", self.close)
        self.act_exit = self._action("Exit", self.close)

        self.act_toggle_explorer_sidebar = QAction("Explorer Sidebar", self)
        self.act_toggle_explorer_sidebar.setCheckable(True)
        self.act_toggle_explorer_sidebar.setChecked(True)
        self.act_toggle_explorer_sidebar.triggered.connect(lambda _checked=False: self._toggle_explorer_sidebar())
        self.act_toggle_explorer_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        self.act_toggle_explorer_sidebar.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

        self.act_toggle_output_panel = QAction("Output", self)
        self.act_toggle_output_panel.setCheckable(True)
        self.act_toggle_output_panel.setChecked(True)
        self.act_toggle_output_panel.triggered.connect(lambda _checked=False: self._toggle_output_panel())
        self.act_toggle_output_panel.setShortcut(QKeySequence("Ctrl+J"))
        self.act_toggle_output_panel.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

        self.act_toggle_full_screen = QAction("Toggle Full Screen", self)
        self.act_toggle_full_screen.setCheckable(True)
        self.act_toggle_full_screen.triggered.connect(lambda _checked=False: self._toggle_full_screen())
        self.act_toggle_full_screen.setShortcut(QKeySequence("F11"))
        self.act_toggle_full_screen.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

        self.act_zoom_in = self._action("Zoom In", self._zoom_in, shortcut=QKeySequence(QKeySequence.StandardKey.ZoomIn))
        self.act_zoom_out = self._action("Zoom Out", self._zoom_out, shortcut=QKeySequence(QKeySequence.StandardKey.ZoomOut))
        self.act_reset_zoom = self._action("Reset Zoom", self._reset_zoom, shortcut="Ctrl+0")
        self.act_zoom_in.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_zoom_in.setShortcuts([QKeySequence(QKeySequence.StandardKey.ZoomIn), QKeySequence("Ctrl+=")])
        self.act_zoom_out.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_zoom_out.setShortcuts([
            QKeySequence(QKeySequence.StandardKey.ZoomOut),
            QKeySequence("Ctrl+-"),
            QKeySequence("Ctrl+Minus"),
            QKeySequence("Ctrl+_")
        ])
        self.act_reset_zoom.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

        self.act_undo = self._action("Undo", lambda: self.code_editor.undo(), shortcut="Ctrl+Z")
        self.act_redo = self._action("Redo", lambda: self.code_editor.redo(), shortcut="Ctrl+Y")
        self.act_cut = self._action("Cut", lambda: self.code_editor.cut(), shortcut="Ctrl+X")
        self.act_copy = self._action("Copy", lambda: self.code_editor.copy(), shortcut="Ctrl+C")
        self.act_paste = self._action("Paste", lambda: self.code_editor.paste(), shortcut="Ctrl+V")
        self.act_select_all = self._action("Select All", lambda: self.code_editor.selectAll(), shortcut="Ctrl+A")
        self.act_find = self._action("Find", enabled=False)
        self.act_replace = self._action("Replace", enabled=False)
        self.act_find_in_files = self._action("Find in Files", enabled=False)
        self.act_replace_in_files = self._action("Replace in Files", enabled=False)
        self.act_toggle_line_comment = self._action("Toggle Line Comment", enabled=False)
        self.act_toggle_block_comment = self._action("Toggle Block Comment", enabled=False)

        self.act_start_turboc = self._action("Start Turbo C", self._on_start)
        self.act_compile = self._action("Compile", self._on_compile)
        self.act_run = self._action("Run", self._on_run)
        self.act_stop_session = self._action("Stop Session", self._on_stop)
        self.act_compile.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self.act_compile.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_run.setShortcut(QKeySequence("F5"))
        self.act_run.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

        self.act_welcome = self._action("Welcome", self._show_welcome)
        self.act_support = self._action("Support", self._open_support_page)
        self.act_feature_request = self._action("Feature request", enabled=False)
        self.act_report_issue = self._action("Report", enabled=False)
        self.act_check_updates = self._action("Check for updates", enabled=False)
        self.act_about = self._action("About", self._show_about)

    def _action(
        self,
        text: str,
        callback: Callable[[], None] | None = None,
        *,
        enabled: bool = True,
        shortcut: str | QKeySequence | None = None,
    ) -> QAction:
        action = QAction(text, self)
        action.setEnabled(enabled)
        if callback is not None:
            action.triggered.connect(lambda _checked=False, fn=callback: fn())
        if shortcut is not None:
            action.setShortcut(shortcut if isinstance(shortcut, QKeySequence) else QKeySequence(shortcut))
        return action

    def _build_menus(self) -> None:
        self.file_menu = QMenu(self)
        for action in [
            self.act_new_text,
            self.act_new_file,
            self.act_new_window,
            self.act_new_window_profile,
            self.act_open_file,
            self.act_open_folder,
            self.act_open_workspace_from_file,
            self.act_open_recent,
            self.act_add_folder,
            self.act_save_workspace_as,
            self.act_duplicate_workspace,
            self.act_save,
            self.act_save_as,
            self.act_save_all,
            self.act_share,
            self.act_auto_save,
            self.act_preferences,
            self.act_revert_file,
            self.act_close_editor,
            self.act_close_folder,
            self.act_close_window,
            self.act_exit,
        ]:
            self.file_menu.addAction(action)

        self.edit_menu = QMenu(self)
        for action in [
            self.act_undo,
            self.act_redo,
            self.act_cut,
            self.act_copy,
            self.act_paste,
            self.act_select_all,
            self.act_find,
            self.act_replace,
            self.act_find_in_files,
            self.act_replace_in_files,
            self.act_toggle_line_comment,
            self.act_toggle_block_comment,
        ]:
            self.edit_menu.addAction(action)

        self.view_menu = QMenu(self)
        for action in [self.act_toggle_full_screen, self.act_zoom_in, self.act_zoom_out, self.act_reset_zoom, self.act_toggle_explorer_sidebar, self.act_toggle_output_panel]:
            self.view_menu.addAction(action)

        self.run_menu = QMenu(self)
        for action in [self.act_start_turboc, self.act_compile, self.act_run, self.act_stop_session]:
            self.run_menu.addAction(action)

        self.help_menu = QMenu(self)
        for action in [self.act_welcome, self.act_support, self.act_feature_request, self.act_report_issue, self.act_check_updates, self.act_about]:
            self.help_menu.addAction(action)

    def _build_ui(self) -> None:
        root = QWidget(objectName="Root")
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_top_bar())

        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)

        self.sidebar_widget = QWidget(objectName="Sidebar")
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addWidget(self._build_explorer_card(), 1)
        self.settings_panel = self._build_settings_card()
        self.settings_dialog = self._build_settings_dialog()

        self.main_panel_widget = QWidget(objectName="MainPanel")
        main_layout = QVBoxLayout(self.main_panel_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        main_layout.addWidget(self._build_editor_card(), 1)

        self.body_splitter.addWidget(self.sidebar_widget)
        self.body_splitter.addWidget(self.main_panel_widget)
        self.body_splitter.setSizes([360, 1080])

        self.output_card = self._build_output_card()
        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.body_splitter)
        self.workspace_splitter.addWidget(self.output_card)
        self.workspace_splitter.setSizes([760, 220])
        self.workspace_splitter.setStretchFactor(0, 4)
        self.workspace_splitter.setStretchFactor(1, 1)

        layout.addWidget(self.workspace_splitter, 1)
        layout.addWidget(self._build_footer())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._window_mode_restored:
            return
        self._window_mode_restored = True
        if self._settings.window_display_mode == "fullscreen":
            self.showFullScreen()
        elif self._settings.window_display_mode == "maximized":
            self.showMaximized()
        QTimer.singleShot(0, self._refresh_view_actions)
        QTimer.singleShot(0, self._apply_output_panel_visibility)
        self._prompt_for_missing_startup_paths()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_editor_file_label()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
            if event.modifiers() & Qt.ControlModifier:
                key = event.key()
                if key in {Qt.Key_Minus, Qt.Key_Underscore}:
                    event.accept()
                    self._zoom_out()
                    return True
                if key in {Qt.Key_Plus, Qt.Key_Equal}:
                    event.accept()
                    self._zoom_in()
                    return True
                if key == Qt.Key_0:
                    event.accept()
                    self._reset_zoom()
                    return True
        return super().eventFilter(obj, event)

    def _build_top_bar(self) -> QFrame:
        top_bar = QFrame(objectName="TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(6, 4, 6, 4)
        top_layout.setSpacing(4)

        if self._logo_path.exists():
            self.setWindowIcon(QIcon(str(self._logo_path)))

        top_layout.addWidget(self._menu_button("File", self.file_menu))
        top_layout.addWidget(self._menu_button("Edit", self.edit_menu))
        top_layout.addWidget(self._menu_button("View", self.view_menu))
        top_layout.addWidget(self._menu_button("Run", self.run_menu))
        top_layout.addWidget(self._menu_button("Help", self.help_menu))
        top_layout.addStretch(1)

        self.top_bar_logo = QLabel(objectName="TopBarLogo")
        if self._logo_path.exists():
            pixmap = QPixmap(str(self._logo_path)).scaled(
                self._scaled(18),
                self._scaled(18),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.top_bar_logo.setPixmap(pixmap)
        top_layout.addWidget(self.top_bar_logo)

        self.top_bar_title = QLabel("Turbo C Editor By Nathan Lobo", objectName="TopBarTitle")
        top_layout.addWidget(self.top_bar_title)
        return top_bar

    def _menu_button(self, text: str, menu: QMenu) -> QToolButton:
        button = QToolButton()
        button.setObjectName("TopMenuButton")
        button.setText(text)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolTip(text)
        return button

    def _build_explorer_card(self) -> QFrame:
        card = QFrame(objectName="Card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("Explorer", objectName="SectionLabel"))
        header.addStretch(1)
        self.create_folder_button = QPushButton("New Folder")
        self.create_folder_button.clicked.connect(self._on_create_workspace_folder)
        header.addWidget(self.create_folder_button)
        self.workspace_root_button = QPushButton("Open Folder")
        self.workspace_root_button.clicked.connect(self._on_open_workspace_folder)
        header.addWidget(self.workspace_root_button)
        layout.addLayout(header)

        self.workspace_root_label = QLabel(objectName="MutedLabel")
        self.workspace_root_label.setWordWrap(True)
        layout.addWidget(self.workspace_root_label)

        self.workspace_model = QFileSystemModel(self)
        self.workspace_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.workspace_model.setIconProvider(self._workspace_icon_provider)
        self.workspace_model.setRootPath(str(self._workspace_root))

        self.workspace_tree = QTreeView()
        self.workspace_tree.setModel(self.workspace_model)
        self.workspace_tree.setHeaderHidden(True)
        self.workspace_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.workspace_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.workspace_tree.setAnimated(True)
        self.workspace_tree.setIndentation(18)
        self.workspace_tree.setIconSize(QSize(self._scaled(28), self._scaled(28)))
        self.workspace_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.workspace_tree.setColumnHidden(1, True)
        self.workspace_tree.setColumnHidden(2, True)
        self.workspace_tree.setColumnHidden(3, True)
        self.workspace_tree.clicked.connect(self._on_workspace_clicked)
        self.workspace_tree.doubleClicked.connect(self._on_workspace_double_clicked)
        self.workspace_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.workspace_tree.customContextMenuRequested.connect(self._show_workspace_context_menu)
        layout.addWidget(self.workspace_tree, 1)

        self.source_info_label = QLabel(objectName="MutedLabel")
        self.source_info_label.setWordWrap(True)
        layout.addWidget(self.source_info_label)

        self.executable_info_label = QLabel(objectName="MutedLabel")
        self.executable_info_label.setWordWrap(True)
        layout.addWidget(self.executable_info_label)
        return card

    def _build_settings_card(self) -> QFrame:
        self.settings_panel = QFrame(objectName="Card")
        layout = QVBoxLayout(self.settings_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Environment", objectName="SectionLabel"))
        note = QLabel("Turbo C root and project directory are required. DOSBox is auto-detected from the Turbo C root.")
        note.setWordWrap(True)
        note.setObjectName("MutedLabel")
        layout.addWidget(note)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.turbo_input = QLineEdit()
        self.project_input = QLineEdit()
        self.dosbox_path_label = QLabel(objectName="MutedLabel")
        self.dosbox_path_label.setWordWrap(True)
        self.dosbox_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.turbo_input.textChanged.connect(self._update_dosbox_path_preview)
        form.addRow("Turbo C root", self.turbo_input)
        form.addRow("Project root", self.project_input)
        form.addRow("DOSBox executable", self.dosbox_path_label)
        layout.addLayout(form)

        self.fullscreen_output_checkbox = QCheckBox("Show output panel in fullscreen")
        layout.addWidget(self.fullscreen_output_checkbox)

        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(self.save_settings_btn)
        return self.settings_panel

    def _build_settings_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setWindowFlag(Qt.WindowType.Tool, True)
        dialog.setModal(False)
        dialog.setMinimumWidth(self._scaled(520))

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addWidget(self.settings_panel)

        dialog.finished.connect(self._on_settings_dialog_closed)
        return dialog

    def _is_valid_directory(self, path_text: str) -> bool:
        if not str(path_text).strip():
            return False

        path = Path(path_text).expanduser()
        return path.exists() and path.is_dir()

    def _update_dosbox_path_preview(self) -> None:
        if not hasattr(self, "dosbox_path_label"):
            return

        turbo_root = self.turbo_input.text().strip() if hasattr(self, "turbo_input") else self._settings.turboc_root
        resolved = resolve_dosbox_executable_path("", turbo_root)
        if resolved is not None:
            self.dosbox_path_label.setText(str(resolved))
            return

        if turbo_root:
            self.dosbox_path_label.setText("DOSBox.exe not found under the Turbo C root.")
        else:
            self.dosbox_path_label.setText("Set the Turbo C root to auto-detect DOSBox.exe.")

    def _refresh_dosbox_path_from_settings(self) -> None:
        resolved = resolve_dosbox_executable_path(self._settings.dosbox_exe, self._settings.turboc_root)
        self._settings.dosbox_exe = str(resolved) if resolved is not None else ""
        self._update_dosbox_path_preview()

    def _prompt_for_missing_startup_paths(self) -> None:
        if self._startup_prompt_shown:
            return

        needs_turbo_root = not self._is_valid_directory(self._settings.turboc_root)
        needs_project_root = not self._is_valid_directory(self._settings.project_root)
        if not needs_turbo_root and not needs_project_root:
            return

        self._startup_prompt_shown = True
        self._apply_settings_to_form()
        self._position_settings_dialog()
        self._update_status("Select Turbo C root and project directory")
        if needs_turbo_root:
            self.turbo_input.setFocus()
        else:
            self.project_input.setFocus()
        self.settings_dialog.exec()

    def _build_editor_card(self) -> QFrame:
        card = QFrame(objectName="Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("Source Editor", objectName="SectionLabel"))
        header.addStretch(1)
        self.editor_file_label = QLabel(objectName="MutedLabel")
        self.editor_file_label.setWordWrap(False)
        self.editor_file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.editor_file_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.editor_file_label, 1)
        header.addSpacing(self._scaled(4))
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.new_file_btn = QPushButton("New File")
        self.open_file_btn = QPushButton("Open File")
        self.save_file_btn = QPushButton("Save File")
        self.save_as_btn = QPushButton("Save As")
        self.compile_btn = QPushButton("Compile")
        self.run_btn = QPushButton("Run")
        self.compile_btn.setObjectName("PrimaryButton")
        self.run_btn.setObjectName("PrimaryButton")
        self.new_file_btn.clicked.connect(self._on_new_file)
        self.open_file_btn.clicked.connect(self._on_open_file)
        self.save_file_btn.clicked.connect(self._on_save_file)
        self.save_as_btn.clicked.connect(self._on_save_as)
        self.compile_btn.clicked.connect(self._on_compile)
        self.run_btn.clicked.connect(self._on_run)
        toolbar.addWidget(self.new_file_btn)
        toolbar.addWidget(self.open_file_btn)
        toolbar.addWidget(self.save_file_btn)
        toolbar.addWidget(self.save_as_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self.compile_btn)
        toolbar.addWidget(self.run_btn)
        layout.addLayout(toolbar)

        self.code_editor = CodeEditor(objectName="CodeEditor")
        self.code_editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.code_editor.setPlaceholderText("Open a C source file from the workspace tree or File menu.")
        self.code_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code_editor.textChanged.connect(self._on_editor_text_changed)
        self._code_highlighter = CFamilySyntaxHighlighter(self.code_editor.document())
        self._code_highlighter.set_theme(self._theme_mode)
        self._code_highlighter.set_language(self._editor_language_for_path(self._current_editor_file))
        layout.addWidget(self.code_editor, 1)
        return card

    def _build_output_card(self) -> QFrame:
        card = QFrame(objectName="Card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Output / Diagnostics", objectName="SectionLabel"))
        self.status_label = QLabel("Status: idle", objectName="StatusLabel")
        layout.addWidget(self.status_label)
        self.log_output = QTextEdit(objectName="LogOutput")
        self.log_output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Operation log and diagnostics appear here.")
        self.log_output.setMinimumHeight(120)
        layout.addWidget(self.log_output, 1)
        return card

    def _build_footer(self) -> QFrame:
        footer = QFrame(objectName="FooterBar")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)

        self.settings_toggle_btn = QPushButton()
        self._configure_footer_icon_button(self.settings_toggle_btn, self._settings_icon_path, "Settings", "⚙")
        self.settings_toggle_btn.clicked.connect(self._toggle_settings_panel)

        self.theme_switch = ThemeSwitch()
        self.theme_switch.setObjectName("ThemeSwitch")
        self.theme_switch.setToolTip("Toggle light and dark theme")
        self.theme_switch.set_theme_mode(self._theme_mode)
        self.theme_switch.setChecked(self._theme_mode == "dark")
        self.theme_switch.toggled.connect(self._on_theme_switch_toggled)

        self.theme_mode_label = QLabel("Dark" if self._theme_mode == "dark" else "Light", objectName="MutedLabel")
        self.theme_mode_label.setMinimumWidth(self._scaled(40))

        self.notification_button = QPushButton()
        self._configure_footer_icon_button(self.notification_button, self._notification_icon_path, "Notifications", "🔔")
        self.notification_button.clicked.connect(self._toggle_notification_popup)
        self.zoom_button = QPushButton()
        self._configure_footer_icon_button(self.zoom_button, self._zoom_icon_path, "Zoom", "🔍")
        self.zoom_button.clicked.connect(self._toggle_zoom_popup)
        
        layout.addWidget(self.settings_toggle_btn)
        layout.addWidget(self.theme_switch)
        layout.addWidget(self.theme_mode_label)
        layout.addStretch(1)
        layout.addWidget(self.notification_button)
        layout.addWidget(self.zoom_button)

        self.zoom_popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.zoom_popup.setObjectName("ZoomPopup")
        self.zoom_popup.setFrameShape(QFrame.Shape.NoFrame)
        popup_layout = QHBoxLayout(self.zoom_popup)
        popup_layout.setContentsMargins(10, 8, 10, 8)
        popup_layout.setSpacing(6)

        self.zoom_popup_minus = QPushButton("-")
        self.zoom_popup_minus.setObjectName("ZoomPopupButton")
        self.zoom_popup_minus.clicked.connect(self._zoom_out)

        self.zoom_value_label = QLabel("0", objectName="ZoomValueLabel")
        self.zoom_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.zoom_popup_plus = QPushButton("+")
        self.zoom_popup_plus.setObjectName("ZoomPopupButton")
        self.zoom_popup_plus.clicked.connect(self._zoom_in)

        self.zoom_popup_reset = QPushButton("Reset")
        self.zoom_popup_reset.setObjectName("ZoomPopupButton")
        self.zoom_popup_reset.clicked.connect(self._reset_zoom)

        popup_layout.addWidget(self.zoom_popup_minus)
        popup_layout.addWidget(self.zoom_value_label)
        popup_layout.addWidget(self.zoom_popup_plus)
        popup_layout.addWidget(self.zoom_popup_reset)

        self.notification_popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.notification_popup.setObjectName("NotificationPopup")
        self.notification_popup.setFrameShape(QFrame.Shape.NoFrame)
        notification_layout = QVBoxLayout(self.notification_popup)
        notification_layout.setContentsMargins(10, 8, 10, 8)
        notification_layout.setSpacing(6)

        self.notification_popup_label = QLabel("NO NEW NOTIFICATIONS")
        self.notification_popup_label.setObjectName("NotificationPopupLabel")
        self.notification_popup_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.notification_popup_close = QPushButton("▼")
        self.notification_popup_close.setObjectName("NotificationPopupButton")
        self.notification_popup_close.setToolTip("Close notifications")
        self.notification_popup_close.clicked.connect(self._hide_notification_popup)
        self.notification_popup_close.setMinimumWidth(self._scaled(26))

        notification_layout.addWidget(self.notification_popup_label)
        notification_layout.addWidget(self.notification_popup_close, alignment=Qt.AlignmentFlag.AlignHCenter)
        return footer

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#Root {
                background: #1e1e1e;
                color: #d4d4d4;
                font-family: Segoe UI, Arial;
                font-size: 13px;
            }
            QFrame#TopBar {
                background: #252526;
                border: 1px solid #333333;
                border-radius: 8px;
            }
            QLabel#TopBarTitle {
                color: #c8c8c8;
                font-size: 12px;
                font-weight: 500;
            }
            QFrame#Card {
                background: #252526;
                border: 1px solid #333333;
                border-radius: 8px;
            }
            QLabel#SectionLabel {
                color: #c5c5c5;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#MutedLabel {
                color: #8f959e;
                font-size: 12px;
            }
            QLabel#StatusLabel {
                color: #4fc1ff;
                font-weight: 600;
            }
            QLineEdit, QPlainTextEdit, QTextEdit {
                background: #1f1f1f;
                color: #d4d4d4;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px 8px;
                selection-background-color: #264f78;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
                border: 1px solid #007acc;
            }
            QPlainTextEdit#CodeEditor {
                font-family: Consolas, Courier New, monospace;
                font-size: 13px;
                background: #1e1e1e;
            }
            QTextEdit#LogOutput {
                font-family: Consolas, Courier New, monospace;
                font-size: 12px;
                background: #181818;
            }
            QPushButton, QToolButton {
                background: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QToolButton#TopMenuButton {
                background: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 4px 10px;
                min-height: 20px;
            }
            QToolButton#TopMenuButton::menu-indicator {
                image: none;
                width: 0px;
            }
            QPushButton:hover, QToolButton:hover {
                background: #37373d;
            }
            QPushButton:pressed, QToolButton:pressed {
                background: #242428;
            }
            QPushButton#PrimaryButton {
                background: #0e639c;
                border: 1px solid #1177bb;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#PrimaryButton:hover {
                background: #1177bb;
            }
            QPushButton#PrimaryButton:pressed {
                background: #0d5a8c;
            }
            QPushButton#FooterIconButton {
                background: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 5px;
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                padding: 0px;
                font-size: 12px;
            }
            QPushButton#FooterIconButton:hover {
                background: #37373d;
            }
            QPushButton#FooterIconButton:pressed {
                background: #242428;
            }
            QFrame#ZoomPopup {
                background: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
            }
            QFrame#NotificationPopup {
                background: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
            }
            QLabel#ZoomValueLabel {
                color: #d4d4d4;
                font-size: 12px;
                font-weight: 600;
                min-width: 22px;
                padding: 0 4px;
            }
            QLabel#NotificationPopupLabel {
                color: #d4d4d4;
                font-size: 12px;
                font-weight: 600;
                min-width: 128px;
                padding: 2px 8px;
            }
            QPushButton#ZoomPopupButton {
                background: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 5px;
                padding: 4px 8px;
                min-height: 20px;
            }
            QPushButton#NotificationPopupButton {
                background: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 5px;
                padding: 2px 8px;
                min-height: 20px;
                min-width: 26px;
                font-size: 11px;
            }
            QPushButton#ZoomPopupButton:hover {
                background: #37373d;
            }
            QPushButton#ZoomPopupButton:pressed {
                background: #242428;
            }
            QPushButton#NotificationPopupButton:hover {
                background: #37373d;
            }
            QPushButton#NotificationPopupButton:pressed {
                background: #242428;
            }
            QCheckBox#ThemeSwitch {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QTreeView {
                background: #1f1f1f;
                color: #d4d4d4;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px;
            }
            QTreeView::item:selected {
                background: #094771;
                color: #ffffff;
            }
            QMenu {
                background: #252526;
                color: #d4d4d4;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #094771;
                color: #ffffff;
            }
            QMenu::item:disabled {
                color: #5a5a5a;
            }
            QMenu::separator {
                background: #3a3a3a;
                height: 1px;
                margin: 4px 0px;
            }
            QSplitter::handle {
                background: #2a2a2a;
            }
            QSplitter::handle:horizontal {
                width: 2px;
            }
            """
        )

        app = QApplication.instance()
        if app is not None:
            theme = self._theme_colors()
            palette = app.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor(theme["window"]))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(theme["text"]))
            palette.setColor(QPalette.ColorRole.Base, QColor(theme["base"]))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme["alternate_base"]))
            palette.setColor(QPalette.ColorRole.Text, QColor(theme["text"]))
            palette.setColor(QPalette.ColorRole.Button, QColor(theme["button"]))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme["button_text"]))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(theme["highlight"]))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme["highlight_text"]))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme["tooltip_base"]))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme["tooltip_text"]))
            app.setPalette(palette)

            font = app.font()
            font.setPointSize(self._scaled(11))
            app.setFont(font)

        if self._code_highlighter is not None:
            self._code_highlighter.set_theme(self._theme_mode)
        if hasattr(self, "_workspace_icon_provider"):
            self._workspace_icon_provider.set_theme_mode(self._theme_mode)

        self.setStyleSheet(
            self.styleSheet()
            + """
            QMainWindow, QWidget#Root {
                font-size: __ROOT_FONT__px;
            }
            QFrame#TopBar {
                border-radius: __CARD_RADIUS__px;
            }
            QLabel#TopBarTitle {
                font-size: __TOP_TITLE_FONT__px;
            }
            QFrame#Card {
                border-radius: __CARD_RADIUS__px;
            }
            QLabel#SectionLabel {
                font-size: __SECTION_FONT__px;
            }
            QLabel#MutedLabel {
                font-size: __MUTED_FONT__px;
            }
            QLineEdit, QPlainTextEdit, QTextEdit {
                border-radius: __INPUT_RADIUS__px;
                padding: __INPUT_PAD_Y__px __INPUT_PAD_X__px;
            }
            QPlainTextEdit#CodeEditor {
                font-size: __CODE_FONT__px;
            }
            QTextEdit#LogOutput {
                font-size: __LOG_FONT__px;
            }
            QPushButton, QToolButton {
                padding: __BTN_PAD_Y__px __BTN_PAD_X__px;
            }
            QPushButton#FooterIconButton {
                border-radius: __FOOTER_RADIUS__px;
                min-width: __FOOTER_SIZE_LARGE__px;
                max-width: __FOOTER_SIZE_LARGE__px;
                min-height: __FOOTER_SIZE_LARGE__px;
                max-height: __FOOTER_SIZE_LARGE__px;
                font-size: __FOOTER_FONT__px;
            }
            QTreeView {
                border-radius: __TREE_RADIUS__px;
                padding: __TREE_PAD__px;
            }
            QSplitter::handle:horizontal {
                width: __SPLIT_HANDLE_W__px;
            }
            """
            .replace("__ROOT_FONT__", str(self._scaled(12)))
            .replace("__TOP_TITLE_FONT__", str(self._scaled(11)))
            .replace("__CARD_RADIUS__", str(self._scaled(7)))
            .replace("__SECTION_FONT__", str(self._scaled(11)))
            .replace("__MUTED_FONT__", str(self._scaled(11)))
            .replace("__INPUT_RADIUS__", str(self._scaled(5)))
            .replace("__INPUT_PAD_Y__", str(self._scaled(5)))
            .replace("__INPUT_PAD_X__", str(self._scaled(7)))
            .replace("__CODE_FONT__", str(self._scaled(12)))
            .replace("__LOG_FONT__", str(self._scaled(11)))
            .replace("__BTN_PAD_Y__", str(self._scaled(5)))
            .replace("__BTN_PAD_X__", str(self._scaled(8)))
            .replace("__FOOTER_RADIUS__", str(self._scaled(4)))
            .replace("__FOOTER_SIZE__", str(self._scaled(24)))
            .replace("__FOOTER_SIZE_LARGE__", str(self._scaled(28)))
            .replace("__FOOTER_FONT__", str(self._scaled(12)))
            .replace("__TREE_RADIUS__", str(self._scaled(5)))
            .replace("__TREE_PAD__", str(self._scaled(3)))
            .replace("__SPLIT_HANDLE_W__", str(self._scaled(2)))
        )

        if self._theme_mode == "light":
            stylesheet = self.styleSheet()
            for old_str, new_str in self._light_theme_overrides().items():
                stylesheet = stylesheet.replace(old_str, new_str)
            self.setStyleSheet(stylesheet)

    def _apply_settings_to_form(self) -> None:
        self.turbo_input.setText(self._settings.turboc_root)
        self.project_input.setText(self._settings.project_root)
        self._refresh_dosbox_path_from_settings()
        self.fullscreen_output_checkbox.setChecked(self._settings.show_output_in_fullscreen)
        self.theme_switch.blockSignals(True)
        self.theme_switch.setChecked(self._theme_mode == "dark")
        self.theme_switch.blockSignals(False)
        self._update_theme_switch_label()
        self._apply_output_panel_visibility()
        self._update_zoom_popup()

    def _restore_window_geometry(self) -> None:
        encoded_geometry = self._settings.window_geometry.strip()
        if not encoded_geometry:
            return

        try:
            geometry = QByteArray.fromBase64(encoded_geometry.encode("ascii"))
        except (UnicodeEncodeError, ValueError):
            return

        if geometry:
            self.restoreGeometry(geometry)

    def _save_window_geometry(self) -> None:
        geometry = bytes(self.saveGeometry())
        self._settings.window_geometry = base64.b64encode(geometry).decode("ascii")
        if self.isFullScreen():
            self._settings.window_display_mode = "fullscreen"
        elif self.isMaximized():
            self._settings.window_display_mode = "maximized"
        else:
            self._settings.window_display_mode = "normal"
        self._storage.save(self._settings)

    def _set_workspace_root(self, path: Path, *, sync_project_input: bool = True) -> None:
        workspace = path if path.exists() else Path.cwd()
        self._workspace_root = workspace.resolve()
        if sync_project_input:
            self.project_input.setText(str(self._workspace_root))
        self.workspace_root_label.setText(str(self._workspace_root))
        root_index = self.workspace_model.index(str(self._workspace_root))
        self.workspace_tree.setRootIndex(root_index)
        self.workspace_tree.expand(root_index)
        self._refresh_action_states()

    def _toggle_settings_panel(self) -> None:
        if self.settings_dialog.isVisible():
            self.settings_dialog.close()
            return

        self._apply_settings_to_form()
        self._position_settings_dialog()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()
        self._update_status("Settings open")

    def _position_settings_dialog(self) -> None:
        self.settings_dialog.adjustSize()
        anchor = self.settings_toggle_btn.mapToGlobal(QPoint(0, self.settings_toggle_btn.height()))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is None:
            self.settings_dialog.move(anchor)
            return

        available = screen.availableGeometry()
        x = anchor.x()
        y = anchor.y() + self._scaled(8)

        if x + self.settings_dialog.width() > available.right():
            x = max(available.left(), available.right() - self.settings_dialog.width())
        if y + self.settings_dialog.height() > available.bottom():
            y = max(available.top(), anchor.y() - self.settings_dialog.height() - self._scaled(8))

        x = max(available.left(), x)
        y = max(available.top(), y)
        self.settings_dialog.move(x, y)

    def _on_settings_dialog_closed(self, _result: int) -> None:
        if self._is_valid_directory(self._settings.turboc_root) and self._is_valid_directory(self._settings.project_root):
            self._update_status("Ready")
        else:
            self._update_status("Settings incomplete")

    def _normalize_theme_mode(self, theme_mode: object) -> str:
        mode = str(theme_mode).lower()
        return mode if mode in {"light", "dark"} else "light"

    def _update_theme_switch_label(self) -> None:
        if hasattr(self, "theme_mode_label"):
            self.theme_mode_label.setText("Dark" if self._theme_mode == "dark" else "Light")
        if hasattr(self, "theme_switch"):
            self.theme_switch.set_theme_mode(self._theme_mode)
            self.theme_switch.updateGeometry()

    def _on_theme_switch_toggled(self, checked: bool) -> None:
        self._theme_mode = "dark" if checked else "light"
        self._settings.theme_mode = self._theme_mode
        self._update_theme_switch_label()
        self._apply_theme()
        self._storage.save(self._settings)

    def _scaled(self, value: int) -> int:
        return max(1, round(value * self._ui_scale))

    def _apply_zoom(self) -> None:
        self._ui_scale = self._zoom_base_scale + (self._zoom_step * self._zoom_level)
        app = QApplication.instance()
        if app is not None:
            font = app.font()
            font.setPointSize(self._scaled(11))
            app.setFont(font)
        self._apply_theme()
        self._update_footer_icon_sizes()
        self._update_zoom_popup()
        self._refresh_view_actions()
        self._update_theme_switch_label()
        self._update_editor_file_label()

    def _set_zoom_level(self, level: int) -> None:
        self._zoom_level = max(self._zoom_min_level, min(self._zoom_max_level, level))
        self._apply_zoom()
        self._settings.zoom_level = self._zoom_level
        self._storage.save(self._settings)

    def _light_theme_overrides(self) -> dict[str, str]:
        return {
            "QFrame#TopBar {\n                background: #252526;\n                border: 1px solid #333333;\n                border-radius: 8px;\n            }": "QFrame#TopBar {\n                background: #ffffff;\n                border: 1px solid #d0d7de;\n                border-radius: 8px;\n            }",
            "QToolButton#TopMenuButton {\n                background: #2d2d30;\n                color: #d4d4d4;\n                border: 1px solid #3c3c3c;\n                border-radius: 6px;\n                padding: 4px 10px;\n                min-height: 20px;\n            }": "QToolButton#TopMenuButton {\n                background: #f3f4f6;\n                color: #1f2328;\n                border: 1px solid #d0d7de;\n                border-radius: 6px;\n                padding: 4px 10px;\n                min-height: 20px;\n            }",
            "QToolButton#TopMenuButton:hover {\n                background: #37373d;\n            }": "QToolButton#TopMenuButton:hover {\n                background: #e5e7eb;\n            }",
            "QToolButton#TopMenuButton:pressed {\n                background: #242428;\n            }": "QToolButton#TopMenuButton:pressed {\n                background: #dbe3ea;\n            }",
            "QTreeView::item:selected {\n                background: #094771;\n                color: #ffffff;\n            }": "QTreeView::item:selected {\n                background: #dbeeff;\n                color: #1f2328;\n            }",
            "QMenu::item:selected {\n                background: #094771;\n                color: #ffffff;\n            }": "QMenu::item:selected {\n                background: #cfe9ff;\n                color: #1f2328;\n            }",
            "#1e1e1e": "#f5f7fb",
            "#252526": "#ffffff",
            "#333333": "#d0d7de",
            "#c8c8c8": "#4b5563",
            "#c5c5c5": "#374151",
            "#d4d4d4": "#1f2328",
            "#8f959e": "#667085",
            "#1f1f1f": "#ffffff",
            "#3a3a3a": "#c9d1d9",
            "#181818": "#fbfcfe",
            "#2d2d30": "#f3f4f6",
            "#3c3c3c": "#c9d1d9",
            "#37373d": "#e5e7eb",
            "#242428": "#d8dde3",
            "#4fc1ff": "#0e639c",
            "#094771": "#dbeeff",
            "#2a2a2a": "#d7dbe0",
            "#4b4b4b": "#cfd6df",
            "#5a5a5a": "#b6c1cc",
        }

    def _theme_colors(self) -> dict[str, str]:
        if self._theme_mode == "dark":
            return {
                "window": "#1e1e1e",
                "text": "#d4d4d4",
                "base": "#1f1f1f",
                "alternate_base": "#252526",
                "button": "#2d2d30",
                "button_text": "#d4d4d4",
                "error": "#ff6b6b",
                "warning": "#f1c40f",
                "highlight": "#094771",
                "highlight_text": "#ffffff",
                "tooltip_base": "#252526",
                "tooltip_text": "#d4d4d4",
            }
        return {
            "window": "#f5f7fb",
            "text": "#1f2328",
            "base": "#ffffff",
            "alternate_base": "#ffffff",
            "button": "#f3f4f6",
            "button_text": "#1f2328",
            "error": "#c62828",
            "warning": "#b58900",
            "highlight": "#0e639c",
            "highlight_text": "#ffffff",
            "tooltip_base": "#ffffff",
            "tooltip_text": "#1f2328",
        }

    def _zoom_in(self) -> None:
        self._set_zoom_level(self._zoom_level + 1)

    def _zoom_out(self) -> None:
        self._set_zoom_level(self._zoom_level - 1)

    def _reset_zoom(self) -> None:
        self._set_zoom_level(0)

    def _configure_footer_icon_button(self, button: QPushButton, icon_path: Path, tooltip: str, fallback_text: str) -> None:
        button.setObjectName("FooterIconButton")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        if icon_path.exists():
            button.setText("")
            button.setIcon(QIcon(str(icon_path)))
        else:
            button.setText(fallback_text)
        button.setIconSize(QSize(self._scaled(18), self._scaled(18)))

    def _update_footer_icon_sizes(self) -> None:
        icon_size = QSize(self._scaled(18), self._scaled(18))
        if hasattr(self, "settings_toggle_btn"):
            self.settings_toggle_btn.setIconSize(icon_size)
        if hasattr(self, "notification_button"):
            self.notification_button.setIconSize(icon_size)
        if hasattr(self, "zoom_button"):
            self.zoom_button.setIconSize(icon_size)

    def _toggle_zoom_popup(self) -> None:
        if self.zoom_popup.isVisible():
            self.zoom_popup.hide()
            return
        self._hide_notification_popup()
        self._show_zoom_popup()

    def _show_zoom_popup(self) -> None:
        self._update_zoom_popup()
        self.zoom_popup.adjustSize()
        popup_size = self.zoom_popup.sizeHint()
        button_origin = self.zoom_button.mapToGlobal(QPoint(0, 0))
        x = button_origin.x() + self.zoom_button.width() - popup_size.width()
        y = button_origin.y() - popup_size.height() - self._scaled(8)
        self.zoom_popup.move(max(8, x), max(8, y))
        self.zoom_popup.show()
        self.zoom_popup.raise_()
        self.zoom_popup.activateWindow()

    def _toggle_notification_popup(self) -> None:
        if self.notification_popup.isVisible():
            self.notification_popup.hide()
            return
        self.zoom_popup.hide()
        self._show_notification_popup()

    def _show_notification_popup(self) -> None:
        self.notification_popup.adjustSize()
        popup_size = self.notification_popup.sizeHint()
        button_origin = self.notification_button.mapToGlobal(QPoint(0, 0))
        x = button_origin.x() + self.notification_button.width() - popup_size.width()
        y = button_origin.y() - popup_size.height() - self._scaled(8)
        self.notification_popup.move(max(8, x), max(8, y))
        self.notification_popup.show()
        self.notification_popup.raise_()
        self.notification_popup.activateWindow()

    def _hide_notification_popup(self) -> None:
        self.notification_popup.hide()

    def _update_zoom_popup(self) -> None:
        if hasattr(self, "zoom_value_label"):
            self.zoom_value_label.setText(str(self._zoom_level))
        if hasattr(self, "zoom_button"):
            self.zoom_button.setToolTip(f"Zoom: {self._zoom_level}")

    def _toggle_full_screen(self) -> None:
        if self.isFullScreen():
            if self._fullscreen_restore_mode == "maximized":
                self.showMaximized()
            else:
                self.showNormal()
        else:
            self._fullscreen_restore_mode = "maximized" if self.isMaximized() else "normal"
            self.showFullScreen()
        self._refresh_view_actions()
        self._apply_output_panel_visibility()

    def _toggle_explorer_sidebar(self) -> None:
        self.sidebar_widget.setVisible(self.act_toggle_explorer_sidebar.isChecked())
        self._refresh_view_actions()

    def _toggle_output_panel(self) -> None:
        self._output_panel_visible = self.act_toggle_output_panel.isChecked()
        self._apply_output_panel_visibility()
        self._refresh_view_actions()

    def _refresh_source_display(self) -> None:
        source = self._current_source_file()
        if source is None:
            self.source_info_label.setText("Selected source: none")
            self.executable_info_label.setText("Executable: none")
        else:
            self.source_info_label.setText(f"Selected source: {source}")
            self.executable_info_label.setText(f"Executable: {source.with_suffix('.EXE').name}")
        self._update_editor_file_label()
        self._refresh_action_states()

    def _update_editor_file_label(self) -> None:
        prefix = "Editor file: "
        if self._current_editor_file is None:
            text = f"{prefix}none"
            self.editor_file_label.setText(text)
            self.editor_file_label.setToolTip(text)
            return

        full_path = str(self._current_editor_file)
        dirty_suffix = " *" if self._editor_dirty else ""
        ellipsis_delta = max(
            0,
            self.editor_file_label.fontMetrics().horizontalAdvance("...")
            - self.editor_file_label.fontMetrics().horizontalAdvance("…"),
        )
        available_width = max(
            1,
            self.editor_file_label.contentsRect().width()
            - self.editor_file_label.fontMetrics().horizontalAdvance(prefix)
            - self.editor_file_label.fontMetrics().horizontalAdvance(dirty_suffix),
        )
        available_width = max(1, available_width - ellipsis_delta)
        elided_path = self.editor_file_label.fontMetrics().elidedText(
            full_path,
            Qt.TextElideMode.ElideMiddle,
            available_width,
        ).replace("…", "...")
        text = f"{prefix}{elided_path}{dirty_suffix}"
        self.editor_file_label.setText(text)
        self.editor_file_label.setToolTip(f"{prefix}{full_path}{dirty_suffix}")

    def _refresh_action_states(self) -> None:
        has_source = self._current_source_file() is not None
        has_editor = self._current_editor_file is not None
        self.act_save.setEnabled(has_editor or self._editor_dirty)
        if hasattr(self, "save_file_btn"):
            self.save_file_btn.setEnabled(has_editor or self._editor_dirty)
        if hasattr(self, "save_as_btn"):
            self.save_as_btn.setEnabled(True)
        self.act_revert_file.setEnabled(has_editor)
        self.act_close_editor.setEnabled(has_editor or bool(self.code_editor.toPlainText()))
        self.act_compile.setEnabled(has_source)
        self.act_run.setEnabled(has_source)
        if hasattr(self, "compile_btn"):
            self.compile_btn.setEnabled(has_source)
        if hasattr(self, "run_btn"):
            self.run_btn.setEnabled(has_source)
        self.act_start_turboc.setEnabled(bool(
            self._is_valid_directory(self._settings.turboc_root)
            and self._is_valid_directory(self._settings.project_root)
            and resolve_dosbox_executable_path(self._settings.dosbox_exe, self._settings.turboc_root)
        ))
        self.act_stop_session.setEnabled(True)

    def _refresh_view_actions(self) -> None:
        self.act_toggle_full_screen.setChecked(self.isFullScreen())
        self.act_toggle_explorer_sidebar.setChecked(self.sidebar_widget.isVisible())
        self.act_toggle_output_panel.setChecked(self._output_panel_visible)

    def _apply_output_panel_visibility(self) -> None:
        should_show = self._output_panel_visible and (not self.isFullScreen() or self._settings.show_output_in_fullscreen)
        self.output_card.setVisible(should_show)

    def _current_source_file(self) -> Path | None:
        if self._selected_source_file is not None and self._selected_source_file.exists():
            return self._selected_source_file
        if self._current_editor_file is not None and self._is_source_file(self._current_editor_file):
            return self._current_editor_file
        return None

    def _confirm_discard_unsaved(self) -> bool:
        if not self._editor_dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "You have unsaved editor changes. Continue without saving?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_workspace_clicked(self, index) -> None:
        path = Path(self.workspace_model.filePath(index))
        if self._is_source_file(path):
            if not self._flush_pending_auto_save():
                return
            self._load_editor_file(path)
            self._refresh_source_display()

    def _on_workspace_double_clicked(self, index) -> None:
        path = Path(self.workspace_model.filePath(index))
        if path.is_file():
            if not self._flush_pending_auto_save():
                return
            self._load_editor_file(path)
            if self._is_source_file(path):
                self._selected_source_file = path.resolve()
            self._refresh_source_display()

    def _load_editor_file(self, file_path: Path) -> bool:
        self._auto_save_timer.stop()
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._show_error("Open failed", f"Unable to open file: {exc}")
            return False
        self._updating_editor_programmatically = True
        self.code_editor.setPlainText(content)
        self._updating_editor_programmatically = False
        self._current_editor_file = file_path.resolve()
        self._editor_dirty = False
        if self._is_source_file(file_path):
            self._selected_source_file = self._current_editor_file
        self._refresh_editor_highlighter()
        return True

    def _write_editor_file(self, file_path: Path, *, announce: bool = True) -> bool:
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(self.code_editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            self._show_error("Save failed", f"Unable to save file: {exc}")
            return False
        self._current_editor_file = file_path.resolve()
        self._editor_dirty = False
        if self._is_source_file(file_path):
            self._selected_source_file = self._current_editor_file
        self._refresh_editor_highlighter()
        self._refresh_source_display()
        return True

    def _on_editor_text_changed(self) -> None:
        if self._updating_editor_programmatically:
            return
        self._editor_dirty = True
        self._refresh_source_display()
        self._schedule_auto_save()

    def _schedule_auto_save(self) -> None:
        if self._updating_editor_programmatically:
            return
        content = self.code_editor.toPlainText()
        if self._current_editor_file is None and not content.strip():
            self._auto_save_timer.stop()
            self._editor_dirty = False
            self._refresh_source_display()
            return
        self._auto_save_timer.start()

    def _next_auto_save_path(self) -> Path:
        workspace_root = self._workspace_root if self._workspace_root.exists() else Path.cwd()
        candidate = workspace_root / "UNTITLED.C"
        if not candidate.exists():
            return candidate

        counter = 1
        while True:
            candidate = workspace_root / f"UNTITLED{counter}.C"
            if not candidate.exists():
                return candidate
            counter += 1

    def _flush_pending_auto_save(self) -> bool:
        if self._updating_editor_programmatically:
            return True

        self._auto_save_timer.stop()
        if not self._editor_dirty:
            return True

        content = self.code_editor.toPlainText()
        if self._current_editor_file is None:
            if not content.strip():
                self._editor_dirty = False
                self._refresh_source_display()
                return True
            self._current_editor_file = self._next_auto_save_path()

        return self._write_editor_file(self._current_editor_file, announce=False)

    def _on_new_file(self) -> None:
        if not self._flush_pending_auto_save():
            return
        self._updating_editor_programmatically = True
        self.code_editor.clear()
        self._updating_editor_programmatically = False
        self._current_editor_file = None
        self._selected_source_file = None
        self._editor_dirty = False
        self._refresh_editor_highlighter()
        self._refresh_source_display()

    def _on_open_file(self) -> None:
        if not self._flush_pending_auto_save():
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Open C file",
            str(self._workspace_root),
            "C files (*.c *.C);;All files (*.*)",
        )
        if selected:
            path = Path(selected)
            self._load_editor_file(path)
            if path.suffix.lower() == ".c":
                self._selected_source_file = path.resolve()
            self._refresh_source_display()

    def _on_open_workspace_folder(self) -> None:
        if not self._flush_pending_auto_save():
            return
        selected = QFileDialog.getExistingDirectory(self, "Select Workspace Folder", str(self._workspace_root))
        if selected:
            self._set_workspace_root(Path(selected))

    def _current_workspace_directory(self) -> Path:
        current_index = self.workspace_tree.currentIndex()
        if current_index.isValid():
            current_path = Path(self.workspace_model.filePath(current_index))
            if current_path.is_dir():
                return current_path
            if current_path.is_file():
                return current_path.parent
        return self._workspace_root if self._workspace_root.exists() else Path.cwd()

    def _is_source_file(self, file_path: Path | None) -> bool:
        """Check if file is a compilable source file (C or C++)"""
        if file_path is None:
            return False
        suffix = file_path.suffix.lower()
        return suffix in {".c", ".cpp", ".cxx", ".cc", ".c++"}

    def _editor_language_for_path(self, file_path: Path | None) -> str:
        if file_path is None:
            return "c"

        suffix = file_path.suffix.lower()
        if suffix in {".cpp", ".cxx", ".cc", ".hpp", ".hh", ".hxx", ".ipp", ".inl", ".tpp", ".h"}:
            return "cpp"
        if suffix == ".cs":
            return "csharp"
        return "c"

    def _refresh_editor_highlighter(self) -> None:
        if self._code_highlighter is None:
            return
        self._code_highlighter.set_language(self._editor_language_for_path(self._current_editor_file))

    def _workspace_path_from_index(self, index) -> Path | None:
        if not index.isValid():
            return None
        path = Path(self.workspace_model.filePath(index))
        if not path.exists():
            return None
        return path

    def _show_workspace_context_menu(self, position: QPoint) -> None:
        index = self.workspace_tree.indexAt(position)
        path = self._workspace_path_from_index(index)
        if path is None:
            return

        self.workspace_tree.setCurrentIndex(index)

        menu = QMenu(self)
        run_action = menu.addAction("Run code")
        run_action.setEnabled(self._is_source_file(path))
        menu.addSeparator()
        cut_action = menu.addAction("Cut")
        copy_action = menu.addAction("Copy")
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        reveal_action = menu.addAction("Reveal in File Explorer")
        copy_path_action = menu.addAction("Copy Path")
        copy_relative_path_action = menu.addAction("Copy Relative Path")

        selected_action = menu.exec(self.workspace_tree.viewport().mapToGlobal(position))
        if selected_action is None:
            return
        if selected_action == run_action:
            self._run_workspace_file(path)
        elif selected_action == cut_action:
            self._copy_workspace_reference(path, action_label="Cut")
        elif selected_action == copy_action:
            self._copy_workspace_reference(path, action_label="Copy")
        elif selected_action == rename_action:
            self._rename_workspace_item(path)
        elif selected_action == delete_action:
            self._delete_workspace_item(path)
        elif selected_action == reveal_action:
            self._reveal_workspace_item(path)
        elif selected_action == copy_path_action:
            self._copy_path_to_clipboard(path, relative=False)
        elif selected_action == copy_relative_path_action:
            self._copy_path_to_clipboard(path, relative=True)

    def _run_workspace_file(self, path: Path) -> None:
        if not self._is_source_file(path):
            self._show_error("Run code", "Run code is only available for C and C++ source files.")
            return

        if not self._flush_pending_auto_save():
            return

        self._selected_source_file = path.resolve()
        self._refresh_source_display()
        self._on_run()

    def _copy_workspace_reference(self, path: Path, *, action_label: str) -> None:
        clipboard = QApplication.clipboard()
        mime_data = QMimeData()
        resolved_path = path.resolve()
        mime_data.setUrls([QUrl.fromLocalFile(str(resolved_path))])
        mime_data.setText(str(resolved_path))
        clipboard.setMimeData(mime_data)
        self._update_status(f"{action_label}: {resolved_path.name}")
        self._append_log(f"{action_label}: {resolved_path}")

    def _copy_text_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _copy_path_to_clipboard(self, path: Path, *, relative: bool) -> None:
        resolved_path = path.resolve()
        if relative:
            try:
                text = os.path.relpath(str(resolved_path), str(self._workspace_root.resolve()))
            except ValueError:
                text = str(resolved_path)
        else:
            text = str(resolved_path)
        self._copy_text_to_clipboard(text)
        self._update_status(f"Copied path: {text}")

    def _rename_workspace_item(self, path: Path) -> None:
        if not self._flush_pending_auto_save():
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Rename",
            "New name:",
            text=path.name,
        )
        if not ok:
            return

        new_name = new_name.strip()
        if not new_name:
            self._show_error("Rename failed", "Name cannot be empty.")
            return

        new_path = path.with_name(new_name)
        if new_path.exists():
            self._show_error("Rename failed", f"A file or folder already exists at: {new_path}")
            return

        try:
            path.rename(new_path)
        except OSError as exc:
            self._show_error("Rename failed", f"Unable to rename item: {exc}")
            return

        if self._current_editor_file is not None and self._current_editor_file.resolve() == path.resolve():
            self._current_editor_file = new_path.resolve()
        if self._selected_source_file is not None and self._selected_source_file.resolve() == path.resolve():
            self._selected_source_file = new_path.resolve() if new_path.suffix.lower() == ".c" else None
        self._refresh_editor_highlighter()
        self.workspace_tree.setCurrentIndex(self.workspace_model.index(str(new_path)))
        self._refresh_source_display()
        self._update_status(f"Renamed: {path.name} -> {new_path.name}")

    def _delete_workspace_item(self, path: Path) -> None:
        if not self._flush_pending_auto_save():
            return

        reply = QMessageBox.question(
            self,
            "Delete",
            f"Move '{path.name}' to the recycle bin?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if not QFile.moveToTrash(str(path.resolve())):
            self._show_error("Delete failed", f"Unable to move to the recycle bin: {path}")
            return

        if self._current_editor_file is not None and self._current_editor_file.resolve() == path.resolve():
            self._auto_save_timer.stop()
            self._updating_editor_programmatically = True
            self.code_editor.clear()
            self._updating_editor_programmatically = False
            self._current_editor_file = None
            self._editor_dirty = False
        if self._selected_source_file is not None and self._selected_source_file.resolve() == path.resolve():
            self._selected_source_file = None

        parent_index = self.workspace_model.index(str(path.parent))
        if parent_index.isValid():
            self.workspace_tree.setCurrentIndex(parent_index)
        self._refresh_source_display()
        self._update_status(f"Moved to recycle bin: {path.name}")

    def _reveal_workspace_item(self, path: Path) -> None:
        resolved_path = path.resolve()
        try:
            if os.name == "nt":
                if resolved_path.is_file():
                    subprocess.Popen(["explorer.exe", "/select,", str(resolved_path)])
                else:
                    subprocess.Popen(["explorer.exe", str(resolved_path)])
                self._update_status(f"Revealed: {resolved_path.name}")
                self._append_log(f"Revealed: {resolved_path}")
                return
        except OSError:
            pass

        fallback_target = resolved_path if resolved_path.is_dir() else resolved_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(fallback_target)))
        self._update_status(f"Revealed: {resolved_path.name}")
        self._append_log(f"Revealed: {resolved_path}")

    def _on_create_workspace_folder(self) -> None:
        if not self._flush_pending_auto_save():
            return

        target_directory = self._current_workspace_directory()
        folder_name, ok = QInputDialog.getText(
            self,
            "Create Folder",
            "Folder name:",
            text="New Folder",
        )
        if not ok:
            return

        folder_name = folder_name.strip()
        if not folder_name:
            self._show_error("Create folder failed", "Folder name cannot be empty.")
            return

        new_folder_path = target_directory / folder_name
        try:
            new_folder_path.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            self._show_error("Create folder failed", f"Folder already exists: {new_folder_path}")
            return
        except OSError as exc:
            self._show_error("Create folder failed", f"Unable to create folder: {exc}")
            return

        parent_index = self.workspace_model.index(str(target_directory))
        self.workspace_tree.expand(parent_index)
        self.workspace_tree.setCurrentIndex(self.workspace_model.index(str(new_folder_path)))
        self._update_status(f"Created folder: {new_folder_path}")
        self._append_log(f"Created folder: {new_folder_path}")

    def _on_save_file(self) -> None:
        if self._current_editor_file is None:
            self._on_save_as()
        else:
            self._write_editor_file(self._current_editor_file)

    def _on_save_as(self) -> None:
        initial_name = self._current_editor_file.name if self._current_editor_file else "PROGRAM.C"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Save C file",
            str(self._workspace_root / initial_name),
            "C files (*.c *.C);;All files (*.*)",
        )
        if selected:
            self._write_editor_file(Path(selected))

    def _on_revert_file(self) -> None:
        if self._current_editor_file is not None:
            self._auto_save_timer.stop()
            self._load_editor_file(self._current_editor_file)

    def _on_close_editor(self) -> None:
        if not self._confirm_discard_unsaved():
            return
        self._updating_editor_programmatically = True
        self.code_editor.clear()
        self._updating_editor_programmatically = False
        self._current_editor_file = None
        self._selected_source_file = None
        self._editor_dirty = False
        self._refresh_editor_highlighter()
        self._refresh_source_display()

    def _collect_settings(self) -> AppSettings:
        turbo_root = self.turbo_input.text().strip()
        project_root = self.project_input.text().strip()
        resolved_dosbox = resolve_dosbox_executable_path("", turbo_root)
        return AppSettings(
            dosbox_exe=str(resolved_dosbox) if resolved_dosbox is not None else "",
            turboc_root=turbo_root,
            project_root=project_root,
            show_output_in_fullscreen=self.fullscreen_output_checkbox.isChecked(),
            zoom_level=self._zoom_level,
            theme_mode=self._theme_mode,
        )

    def _on_save_settings(self) -> None:
        settings = self._collect_settings()
        errors = settings.validate()
        if errors:
            self._show_error("Cannot save settings", "\n".join(errors))
            return
        self._storage.save(settings)
        self._settings = settings
        self._set_workspace_root(Path(settings.project_root))
        self._refresh_dosbox_path_from_settings()
        self._apply_output_panel_visibility()
        self._refresh_view_actions()
        if hasattr(self, "settings_dialog") and self.settings_dialog.isVisible():
            self.settings_dialog.close()

    def _ensure_valid_settings(self) -> bool:
        settings = self._collect_settings()
        errors = settings.validate()
        if errors:
            self._show_error("Invalid settings", "\n".join(errors))
            return False
        self._settings = settings
        self._refresh_dosbox_path_from_settings()
        self._apply_output_panel_visibility()
        self._refresh_view_actions()
        return True

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

    def _prepare_source_for_build(self) -> Path | None:
        if not self._flush_pending_auto_save():
            return None

        source = self._current_source_file()
        if source is None:
            self._show_error("Missing source file", "Select a C source file from the explorer before compiling or running.")
            return None
        return source

    def _source_argument_for_build(self, source: Path) -> str:
        project_root = Path(self._settings.project_root).resolve()
        try:
            return str(source.resolve().relative_to(project_root))
        except ValueError:
            return source.name

    def _on_compile(self) -> None:
        if not self._ensure_valid_settings():
            return
        self._compile_current_source()

    def _compile_current_source(self) -> tuple[bool, Path | None]:
        source = self._prepare_source_for_build()
        if source is None:
            return False, None

        source_argument = self._source_argument_for_build(source)

        result, diagnostics = self._turbo_service.compile(
            self._settings.dosbox_exe,
            self._settings.turboc_root,
            self._settings.project_root,
            str(source_argument),
        )
        parsed = parse_diagnostics(result.output)
        error_count = sum(1 for item in parsed if item.severity == Severity.ERROR)
        warning_count = sum(1 for item in parsed if item.severity == Severity.WARNING)

        if error_count:
            self._update_status(f"Compile failed: {error_count} error(s), {warning_count} warning(s)")
        elif warning_count:
            self._update_status(f"Compile succeeded with {warning_count} warning(s)")
        elif not result.ok:
            self._update_status(f"Compile failed (exit code {result.return_code if result.return_code is not None else 'unknown'})")
        else:
            self._update_status("Compile succeeded")

        self._append_log("Compile output:")
        self._append_log(diagnostics or result.output or "(no output)")

        compile_ok = result.ok and error_count == 0
        return compile_ok, source

    def _on_run(self) -> None:
        if not self._ensure_valid_settings():
            return
        compile_ok, source = self._compile_current_source()
        if not compile_ok or source is None:
            self._append_log("Run canceled because compile did not succeed.", color="#ff6b6b")
            return
        source_argument = self._source_argument_for_build(source)
        result = self._turbo_service.run_program(
            self._settings.dosbox_exe,
            self._settings.turboc_root,
            self._settings.project_root,
            source_argument,
        )
        self._update_status("Run succeeded" if result.ok else "Run failed")
        self._append_log("Run output:\n" + (result.output or "(no output)"))

    def _show_welcome(self) -> None:
        QMessageBox.information(
            self,
            "Welcome",
            "Select a workspace folder, open a .C file from the explorer, then compile or run it.",
        )

    def _open_support_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._codinx_support_url))

    def _show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("About")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setModal(True)
        dialog.setMinimumWidth(self._scaled(560))

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hero = QFrame(objectName="Card")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 16, 16, 16)
        hero_layout.setSpacing(14)

        logo_stack = QVBoxLayout()
        logo_stack.setSpacing(self._scaled(6))

        recent_logo = QLabel()
        recent_logo.setFixedSize(self._scaled(62), self._scaled(62))
        recent_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        recent_pixmap = self._scaled_asset_pixmap(self._recent_logo_path, self._scaled(56))
        if recent_pixmap is not None:
            recent_logo.setPixmap(recent_pixmap)
            recent_logo.setStyleSheet("QLabel { background: transparent; }")
        else:
            recent_logo.setText("TC")
            recent_logo.setStyleSheet(
                """
                QLabel {
                    border-radius: 16px;
                    background: #0e639c;
                    color: #ffffff;
                    font-size: 24px;
                    font-weight: 700;
                }
                """
            )

        legacy_logo = QLabel()
        legacy_logo.setFixedSize(self._scaled(62), self._scaled(62))
        legacy_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        legacy_pixmap = self._scaled_asset_pixmap(self._logo_path, self._scaled(56))
        if legacy_pixmap is not None:
            legacy_logo.setPixmap(legacy_pixmap)
            legacy_logo.setStyleSheet("QLabel { background: transparent; }")
        else:
            legacy_logo.setText("TC")
            legacy_logo.setStyleSheet(
                """
                QLabel {
                    border-radius: 16px;
                    background: #0e639c;
                    color: #ffffff;
                    font-size: 24px;
                    font-weight: 700;
                }
                """
            )

        logo_stack.addWidget(recent_logo, 0, Qt.AlignmentFlag.AlignHCenter)
        logo_stack.addWidget(legacy_logo, 0, Qt.AlignmentFlag.AlignHCenter)
        logo_stack.addStretch(1)
        hero_layout.addLayout(logo_stack)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)

        title_label = QLabel("Turbo C Editor By Nathan Lobo")
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 18px; font-weight: 700;")

        version_label = QLabel(f"Version {self._about_version}", objectName="StatusLabel")

        ownership_label = QLabel(
            "&copy; 2026 by Codinx. All rights reserved.<br>Codinx is owned by Nathan Francisco Lobo."
        )
        ownership_label.setWordWrap(True)
        ownership_label.setTextFormat(Qt.TextFormat.RichText)

        website_label = QLabel(
            f'<a href="{self._codinx_site_url}">{self._codinx_site_url}</a>'
        )
        website_label.setTextFormat(Qt.TextFormat.RichText)
        website_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        website_label.setOpenExternalLinks(True)

        text_column.addWidget(title_label)
        text_column.addWidget(version_label)
        text_column.addWidget(ownership_label)
        text_column.addWidget(website_label)
        text_column.addStretch(1)
        hero_layout.addLayout(text_column, 1)
        layout.addWidget(hero)

        social_card = QFrame(objectName="Card")
        social_layout = QVBoxLayout(social_card)
        social_layout.setContentsMargins(16, 14, 16, 14)
        social_layout.setSpacing(10)

        social_title = QLabel("Connect", objectName="SectionLabel")
        social_layout.addWidget(social_title)

        social_row = QHBoxLayout()
        social_row.setSpacing(8)
        social_buttons = [
            ("GitHub", "github", self._about_social_links["GitHub"]),
            ("Email", "email", self._about_social_links["Email"]),
            ("WhatsApp", "whatsapp", self._about_social_links["WhatsApp"]),
            ("Support", "support", self._about_social_links["Support"]),
        ]
        for label, icon_name, url in social_buttons:
            button = QToolButton()
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setText(label)
            button.setIcon(self._about_social_icon(icon_name))
            button.setIconSize(QSize(self._scaled(20), self._scaled(20)))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, target=url: QDesktopServices.openUrl(QUrl(target)))
            social_row.addWidget(button)
        social_row.addStretch(1)
        social_layout.addLayout(social_row)
        layout.addWidget(social_card)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(dialog.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        dialog.exec()

    def _scaled_asset_pixmap(self, asset_path: Path, size: int) -> QPixmap | None:
        if not asset_path.exists():
            return None

        pixmap = QPixmap(str(asset_path))
        if pixmap.isNull():
            return None

        return pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _about_social_icon(self, kind: str) -> QIcon:
        cached_icon = self._about_icon_cache.get(kind)
        if cached_icon is not None:
            return cached_icon

        if kind == "support":
            icon = QIcon(str(self._recent_logo_path))
            self._about_icon_cache[kind] = icon
            return icon

        icon_paths = {
            "github": self._about_github_icon_path,
            "email": self._about_email_icon_path,
            "whatsapp": self._about_whatsapp_icon_path,
        }
        icon_path = icon_paths.get(kind)
        if icon_path is not None and icon_path.exists():
            icon = QIcon(str(icon_path))
            self._about_icon_cache[kind] = icon
            return icon

        return QIcon()

    def _log_color_for_line(self, line: str) -> QColor:
        theme_colors = self._theme_colors()
        lower = line.lower()
        if line.startswith("[ERROR]") or lower.startswith("error:") or " error" in lower:
            return QColor(theme_colors["error"])
        if line.startswith("[WARNING]") or "warning" in lower:
            return QColor(theme_colors["warning"])
        return QColor(theme_colors["text"])

    def _append_log(self, text: str, color: str | None = None) -> None:
        if not text:
            return

        lines = text.splitlines() or [text]
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_output.setTextCursor(cursor)

        if color is not None:
            line_color = QColor(color)
            for line in lines:
                self.log_output.setTextColor(line_color)
                self.log_output.insertPlainText(line + "\n")
        else:
            for line in lines:
                self.log_output.setTextColor(self._log_color_for_line(line))
                self.log_output.insertPlainText(line + "\n")

        self.log_output.setTextColor(QColor(self._theme_colors()["text"]))
        self.log_output.ensureCursorVisible()

    def _update_status(self, status: str) -> None:
        self.status_label.setText(f"Status: {status}")

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def shutdown(self) -> None:
        self._dosbox_service.stop_session()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._flush_pending_auto_save():
            event.ignore()
            return
        self._save_window_geometry()
        self._dosbox_service.stop_session()
        super().closeEvent(event)
