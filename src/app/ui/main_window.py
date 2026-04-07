from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QByteArray, QDir, QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeyEvent, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QFileDialog,
    QFileSystemModel,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QTreeView,
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
        self.setWindowTitle("Editor for Turbo C by Nathan Lobo")
        self.resize(1440, 900)

        self._storage = SettingsStorage()
        self._settings = self._storage.load()
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
        self._zoom_level = 0
        self._ui_scale = self._zoom_base_scale

        self._dosbox_service = DosBoxService()
        self._turbo_service = TurboCService(self._dosbox_service)
        self._logo_path = Path(__file__).resolve().parents[1] / "assets" / "icon.png"
        self._settings_icon_path = Path(__file__).resolve().parents[1] / "assets" / "settings.svg"
        self._notification_icon_path = Path(__file__).resolve().parents[1] / "assets" / "bell.svg"
        self._zoom_icon_path = Path(__file__).resolve().parents[1] / "assets" / "zoom.svg"

        self._build_actions()
        self._build_menus()
        self._build_ui()
        self._apply_theme()
        self._apply_settings_to_form()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._restore_window_geometry()
        self._set_workspace_root(self._workspace_root)
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
        for action in [self.act_welcome, self.act_feature_request, self.act_report_issue, self.act_check_updates, self.act_about]:
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
        sidebar_layout.addWidget(self._build_settings_card())

        self.main_panel_widget = QWidget(objectName="MainPanel")
        main_layout = QVBoxLayout(self.main_panel_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        main_layout.addWidget(self._build_run_bar())
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

        self.settings_panel.setVisible(False)

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

        self.logo_label = QLabel(objectName="LogoLabel")
        if self._logo_path.exists():
            pixmap = QPixmap(str(self._logo_path))
            self.logo_label.setPixmap(
                pixmap.scaled(
                    18,
                    18,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.setWindowIcon(QIcon(str(self._logo_path)))
        else:
            self.logo_label.setText("TC")
        top_layout.addWidget(self.logo_label)

        top_layout.addWidget(self._menu_button("File", self.file_menu))
        top_layout.addWidget(self._menu_button("Edit", self.edit_menu))
        top_layout.addWidget(self._menu_button("View", self.view_menu))
        top_layout.addWidget(self._menu_button("Run", self.run_menu))
        top_layout.addWidget(self._menu_button("Help", self.help_menu))
        top_layout.addStretch(1)

        self.top_bar_title = QLabel("Editor for Turbo C by Nathan Lobo", objectName="TopBarTitle")
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
        self.workspace_root_button = QPushButton("Open Folder")
        self.workspace_root_button.clicked.connect(self._on_open_workspace_folder)
        header.addWidget(self.workspace_root_button)
        layout.addLayout(header)

        self.workspace_root_label = QLabel(objectName="MutedLabel")
        self.workspace_root_label.setWordWrap(True)
        layout.addWidget(self.workspace_root_label)

        self.workspace_model = QFileSystemModel(self)
        self.workspace_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.workspace_model.setRootPath(str(self._workspace_root))

        self.workspace_tree = QTreeView()
        self.workspace_tree.setModel(self.workspace_model)
        self.workspace_tree.setHeaderHidden(True)
        self.workspace_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.workspace_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.workspace_tree.setAnimated(True)
        self.workspace_tree.setIndentation(18)
        self.workspace_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.workspace_tree.setColumnHidden(1, True)
        self.workspace_tree.setColumnHidden(2, True)
        self.workspace_tree.setColumnHidden(3, True)
        self.workspace_tree.clicked.connect(self._on_workspace_clicked)
        self.workspace_tree.doubleClicked.connect(self._on_workspace_double_clicked)
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
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.dosbox_input = QLineEdit()
        self.turbo_input = QLineEdit()
        self.project_input = QLineEdit()
        form.addRow("DOSBox executable", self.dosbox_input)
        form.addRow("Turbo C root", self.turbo_input)
        form.addRow("Project root", self.project_input)
        layout.addLayout(form)

        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(self.save_settings_btn)
        return self.settings_panel

    def _build_run_bar(self) -> QFrame:
        card = QFrame(objectName="Card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Actions", objectName="SectionLabel"))
        self.start_btn = QPushButton("Start Turbo C")
        self.compile_btn = QPushButton("Compile")
        self.run_btn = QPushButton("Run")
        self.stop_btn = QPushButton("Stop Session")
        self.compile_btn.setObjectName("PrimaryButton")
        self.run_btn.setObjectName("PrimaryButton")
        self.start_btn.clicked.connect(self._on_start)
        self.compile_btn.clicked.connect(self._on_compile)
        self.run_btn.clicked.connect(self._on_run)
        self.stop_btn.clicked.connect(self._on_stop)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.compile_btn)
        layout.addWidget(self.run_btn)
        layout.addWidget(self.stop_btn)
        layout.addStretch(1)
        return card

    def _build_editor_card(self) -> QFrame:
        card = QFrame(objectName="Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("Source Editor", objectName="SectionLabel"))
        header.addStretch(1)
        self.editor_file_label = QLabel(objectName="MutedLabel")
        self.editor_file_label.setWordWrap(True)
        header.addWidget(self.editor_file_label)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        self.new_file_btn = QPushButton("New File")
        self.open_file_btn = QPushButton("Open File")
        self.save_file_btn = QPushButton("Save File")
        self.save_as_btn = QPushButton("Save As")
        self.new_file_btn.clicked.connect(self._on_new_file)
        self.open_file_btn.clicked.connect(self._on_open_file)
        self.save_file_btn.clicked.connect(self._on_save_file)
        self.save_as_btn.clicked.connect(self._on_save_as)
        toolbar.addWidget(self.new_file_btn)
        toolbar.addWidget(self.open_file_btn)
        toolbar.addWidget(self.save_file_btn)
        toolbar.addWidget(self.save_as_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.code_editor = QPlainTextEdit(objectName="CodeEditor")
        self.code_editor.setPlaceholderText("Open a C source file from the workspace tree or File menu.")
        self.code_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code_editor.textChanged.connect(self._on_editor_text_changed)
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
        self.log_output = QPlainTextEdit(objectName="LogOutput")
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
        self.footer_hint = QLabel("Ready", objectName="MutedLabel")
        self.notification_button = QPushButton()
        self._configure_footer_icon_button(self.notification_button, self._notification_icon_path, "Notifications", "🔔")
        self.notification_button.clicked.connect(self._toggle_notification_popup)
        self.zoom_button = QPushButton()
        self._configure_footer_icon_button(self.zoom_button, self._zoom_icon_path, "Zoom", "🔍")
        self.zoom_button.clicked.connect(self._toggle_zoom_popup)
        layout.addWidget(self.settings_toggle_btn)
        layout.addWidget(self.footer_hint)
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
            QLabel#LogoLabel {
                color: #ffffff;
                font-weight: 700;
                min-width: 20px;
                min-height: 20px;
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
            QLineEdit, QPlainTextEdit {
                background: #1f1f1f;
                color: #d4d4d4;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px 8px;
                selection-background-color: #264f78;
            }
            QLineEdit:focus, QPlainTextEdit:focus {
                border: 1px solid #007acc;
            }
            QPlainTextEdit#CodeEditor {
                font-family: Cascadia Code, Consolas, Courier New;
                font-size: 13px;
                background: #1e1e1e;
            }
            QPlainTextEdit#LogOutput {
                font-family: Cascadia Code, Consolas, Courier New;
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
            QPushButton:hover, QToolButton:hover {
                background: #37373d;
            }
            QPushButton:pressed, QToolButton:pressed {
                background: #242428;
            }
            QToolButton#TopMenuButton {
                padding: 4px 8px;
                min-height: 20px;
            }
            QToolButton#TopMenuButton::menu-indicator {
                image: none;
                width: 0px;
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
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
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
            QTreeView {
                background: #1f1f1f;
                color: #d4d4d4;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px;
            }
            QTreeView::item:selected {
                background: #094771;
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
            font = app.font()
            font.setPointSize(self._scaled(11))
            app.setFont(font)

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
            QLabel#LogoLabel {
                min-width: __LOGO_SIZE__px;
                min-height: __LOGO_SIZE__px;
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
            QLineEdit, QPlainTextEdit {
                border-radius: __INPUT_RADIUS__px;
                padding: __INPUT_PAD_Y__px __INPUT_PAD_X__px;
            }
            QPlainTextEdit#CodeEditor {
                font-size: __CODE_FONT__px;
            }
            QPlainTextEdit#LogOutput {
                font-size: __LOG_FONT__px;
            }
            QPushButton, QToolButton {
                padding: __BTN_PAD_Y__px __BTN_PAD_X__px;
            }
            QToolButton#TopMenuButton {
                padding: __TOP_BTN_PAD_Y__px __TOP_BTN_PAD_X__px;
                min-height: __TOP_BTN_MIN_H__px;
            }
            QPushButton#FooterIconButton {
                border-radius: __FOOTER_RADIUS__px;
                min-width: __FOOTER_SIZE__px;
                max-width: __FOOTER_SIZE__px;
                min-height: __FOOTER_SIZE__px;
                max-height: __FOOTER_SIZE__px;
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
            .replace("__LOGO_SIZE__", str(self._scaled(18)))
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
            .replace("__TOP_BTN_PAD_Y__", str(self._scaled(3)))
            .replace("__TOP_BTN_PAD_X__", str(self._scaled(7)))
            .replace("__TOP_BTN_MIN_H__", str(self._scaled(18)))
            .replace("__FOOTER_RADIUS__", str(self._scaled(4)))
            .replace("__FOOTER_SIZE__", str(self._scaled(24)))
            .replace("__FOOTER_FONT__", str(self._scaled(12)))
            .replace("__TREE_RADIUS__", str(self._scaled(5)))
            .replace("__TREE_PAD__", str(self._scaled(3)))
            .replace("__SPLIT_HANDLE_W__", str(self._scaled(2)))
        )

    def _apply_settings_to_form(self) -> None:
        self.dosbox_input.setText(self._settings.dosbox_exe)
        self.turbo_input.setText(self._settings.turboc_root)
        self.project_input.setText(self._settings.project_root)

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

    def _set_workspace_root(self, path: Path) -> None:
        workspace = path if path.exists() else Path.cwd()
        self._workspace_root = workspace.resolve()
        self.project_input.setText(str(self._workspace_root))
        self.workspace_root_label.setText(str(self._workspace_root))
        root_index = self.workspace_model.index(str(self._workspace_root))
        self.workspace_tree.setRootIndex(root_index)
        self.workspace_tree.expand(root_index)
        self._refresh_action_states()

    def _toggle_settings_panel(self) -> None:
        self.settings_panel.setVisible(not self.settings_panel.isVisible())
        self.footer_hint.setText("Settings open" if self.settings_panel.isVisible() else "Ready")

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

    def _set_zoom_level(self, level: int) -> None:
        self._zoom_level = max(self._zoom_min_level, min(self._zoom_max_level, level))
        self._apply_zoom()

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
        button.setIconSize(QSize(self._scaled(16), self._scaled(16)))

    def _update_footer_icon_sizes(self) -> None:
        icon_size = QSize(self._scaled(16), self._scaled(16))
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

    def _toggle_explorer_sidebar(self) -> None:
        self.sidebar_widget.setVisible(self.act_toggle_explorer_sidebar.isChecked())
        self._refresh_view_actions()

    def _toggle_output_panel(self) -> None:
        self.output_card.setVisible(self.act_toggle_output_panel.isChecked())
        self._refresh_view_actions()

    def _refresh_source_display(self) -> None:
        source = self._current_source_file()
        if source is None:
            self.source_info_label.setText("Selected source: none")
            self.executable_info_label.setText("Executable: none")
        else:
            self.source_info_label.setText(f"Selected source: {source}")
            self.executable_info_label.setText(f"Executable: {source.with_suffix('.EXE').name}")
        editor_label = f"Editor file: {self._current_editor_file if self._current_editor_file else 'none'}"
        if self._editor_dirty:
            editor_label += " *"
        self.editor_file_label.setText(editor_label)
        self._refresh_action_states()

    def _refresh_action_states(self) -> None:
        has_source = self._current_source_file() is not None
        has_editor = self._current_editor_file is not None
        self.act_save.setEnabled(has_editor or self._editor_dirty)
        self.act_revert_file.setEnabled(has_editor)
        self.act_close_editor.setEnabled(has_editor or bool(self.code_editor.toPlainText()))
        self.act_compile.setEnabled(has_source)
        self.act_run.setEnabled(has_source)
        self.act_start_turboc.setEnabled(bool(self._settings.dosbox_exe and self._settings.turboc_root and self._settings.project_root))
        self.act_stop_session.setEnabled(True)

    def _refresh_view_actions(self) -> None:
        self.act_toggle_full_screen.setChecked(self.isFullScreen())
        self.act_toggle_explorer_sidebar.setChecked(self.sidebar_widget.isVisible())
        self.act_toggle_output_panel.setChecked(self.output_card.isVisible())

    def _current_source_file(self) -> Path | None:
        if self._selected_source_file is not None and self._selected_source_file.exists():
            return self._selected_source_file
        if self._current_editor_file is not None and self._current_editor_file.suffix.lower() == ".c":
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
        if path.is_file() and path.suffix.lower() == ".c":
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
            if path.suffix.lower() == ".c":
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
        if file_path.suffix.lower() == ".c":
            self._selected_source_file = self._current_editor_file
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
        if file_path.suffix.lower() == ".c":
            self._selected_source_file = self._current_editor_file
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
        self._refresh_source_display()

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
        self._set_workspace_root(Path(settings.project_root))

    def _ensure_valid_settings(self) -> bool:
        settings = self._collect_settings()
        errors = settings.validate()
        if errors:
            self._show_error("Invalid settings", "\n".join(errors))
            return False
        self._settings = settings
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

    def _on_compile(self) -> None:
        if not self._ensure_valid_settings():
            return
        self._compile_current_source()

    def _compile_current_source(self) -> tuple[bool, Path | None]:
        source = self._prepare_source_for_build()
        if source is None:
            return False, None

        project_root = Path(self._settings.project_root).resolve()
        try:
            source_argument = source.resolve().relative_to(project_root)
        except ValueError:
            source_argument = source.name

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

        self._append_log("Compile output:\n" + (diagnostics or result.output or "(no output)"))

        compile_ok = result.ok and error_count == 0
        return compile_ok, source

    def _on_run(self) -> None:
        if not self._ensure_valid_settings():
            return
        compile_ok, source = self._compile_current_source()
        if not compile_ok or source is None:
            self._append_log("Run canceled because compile did not succeed.")
            return
        result = self._turbo_service.run_program(
            self._settings.dosbox_exe,
            self._settings.turboc_root,
            self._settings.project_root,
            source.with_suffix(".EXE").name,
        )
        self._update_status("Run succeeded" if result.ok else "Run failed")
        self._append_log("Run output:\n" + (result.output or "(no output)"))

    def _show_welcome(self) -> None:
        QMessageBox.information(
            self,
            "Welcome",
            "Select a workspace folder, open a .C file from the explorer, then compile or run it.",
        )

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "About",
            "Editor for Turbo C by Nathan Lobo\nModern wrapper for Turbo C running in DOSBox.",
        )

    def _append_log(self, text: str) -> None:
        self.log_output.appendPlainText(text)

    def _update_status(self, status: str) -> None:
        self.status_label.setText(f"Status: {status}")
        self.footer_hint.setText(status if status else "Ready")

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
