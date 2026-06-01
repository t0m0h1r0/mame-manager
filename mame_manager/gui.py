from __future__ import annotations

from functools import partial
from pathlib import Path

try:
    from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl
    from PySide6.QtGui import QDesktopServices, QFont
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSizePolicy,
        QSpinBox,
        QSplitter,
        QStackedWidget,
        QVBoxLayout,
        QTabWidget,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local environment
    raise SystemExit("PySide6 is required. Install it with: python -m pip install PySide6") from exc

from .gui_model import (
    ACTION_TITLES,
    GUI_REMOTE_BACKUP_AFTER_REBUILD,
    GuiSettings,
    WorkflowAction,
    build_command,
    load_gui_settings,
    phase_index,
)


class PathRow(QWidget):
    def __init__(self, value: Path, mode: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.mode = mode
        self.line_edit = QLineEdit(str(value))
        self.button = QPushButton("選択")
        self.button.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.button)

    def value(self) -> Path:
        return Path(self.line_edit.text()).expanduser()

    def _browse(self) -> None:
        current = str(self.value())
        if self.mode == "dir":
            selected = QFileDialog.getExistingDirectory(self, "Select directory", current)
        else:
            selected, _ = QFileDialog.getOpenFileName(self, "Select file", current)
        if selected:
            self.line_edit.setText(selected)


class MameManagerWindow(QMainWindow):
    ACTION_ORDER = (
        WorkflowAction.UPDATE_SCAN,
        WorkflowAction.LOCAL_REBUILD,
        WorkflowAction.SCAN_MISSING,
        WorkflowAction.REBUILD_PLAN,
        WorkflowAction.QB_DRY_RUN,
        WorkflowAction.QB_APPLY,
        WorkflowAction.QB_APPLY_RESUME,
        WorkflowAction.FINAL_SCAN,
        WorkflowAction.CHECK_BROKEN,
        WorkflowAction.REMOTE_BACKUP,
        WorkflowAction.RESTORE,
    )

    def __init__(self, settings: GuiSettings | None = None):
        super().__init__()
        self.base_settings = settings or load_gui_settings()
        self.process: QProcess | None = None
        self.active_spec = None
        self.action_buttons: list[QPushButton] = []
        self.setWindowTitle("MAME Manager")
        self.resize(1180, 780)
        self._build_ui()
        self._connect_setting_changes()
        self._update_command_preview()

    def _build_ui(self) -> None:
        self._init_setting_widgets()
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("MAME Manager")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 6)
        title_font.setBold(True)
        title.setFont(title_font)
        self.status_label = QLabel("待機中")
        self.stop_button = QPushButton("実行中止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_process)
        self.save_button = QPushButton("設定保存")
        self.save_button.clicked.connect(self.save_config)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_label)
        header.addWidget(self.stop_button)
        header.addWidget(self.save_button)
        root_layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.nav = QListWidget()
        self.nav.addItems(["ワークフロー", "レポート", "qBittorrent", "設定"])
        self.nav.setFixedWidth(150)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._workflow_page())
        self.stack.addWidget(self._reports_page())
        self.stack.addWidget(self._qbittorrent_page())
        self.stack.addWidget(self._settings_page())
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.setCentralWidget(root)

    def _init_setting_widgets(self) -> None:
        self.mame_bin = PathRow(self.base_settings.mame_bin, "file")
        self.images = PathRow(self.base_settings.images, "dir")
        self.new = PathRow(self.base_settings.new, "dir")
        self.work = PathRow(self.base_settings.work, "dir")
        self.scan_jobs = QSpinBox()
        self.scan_jobs.setRange(1, 256)
        self.scan_jobs.setValue(self.base_settings.scan_jobs)
        self.compress_jobs = QSpinBox()
        self.compress_jobs.setRange(1, 256)
        self.compress_jobs.setValue(self.base_settings.compress_jobs)
        self.merge_mode = QComboBox()
        self.merge_mode.addItems(["merged", "split", "non-merged"])
        self.merge_mode.setCurrentText(self.base_settings.merge_mode)
        self.remote_backup = QCheckBox("rebuild後にリモートバックアップも実行する")
        self.remote_backup.setChecked(self.base_settings.remote_backup_after_rebuild)
        self.backup_url = QLineEdit(self.base_settings.backup_url or "")
        self.backup_url.setCursorPosition(0)

        self.qb_url = QLineEdit(self.base_settings.qbittorrent_url or "")
        self.qb_url.setCursorPosition(0)
        self.qb_user = QLineEdit(self.base_settings.qbittorrent_user)
        self.qb_password = QLineEdit(self.base_settings.qbittorrent_password or "")
        self.qb_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.qb_hash = QLineEdit(self.base_settings.qbittorrent_hash or "")
        self.qb_name = QLineEdit(self.base_settings.qbittorrent_name or "")
        self.qb_timeout = QSpinBox()
        self.qb_timeout.setRange(1, 600)
        self.qb_timeout.setValue(self.base_settings.qbittorrent_timeout)

        self.config_file = PathRow(self.base_settings.config_file, "file")
        self.rsync_pass = PathRow(self.base_settings.rsync_pass, "file")
        self.sevenz_bin = QLineEdit(self.base_settings.sevenz_bin)
        self.rsync_bin = QLineEdit(self.base_settings.rsync_bin)
        self.chdman_bin = QLineEdit(self.base_settings.chdman_bin)
        self.rebuild_mode = QComboBox()
        self.rebuild_mode.addItems(["auto", "full", "skip"])
        self.rebuild_mode.setCurrentText(self.base_settings.rebuild_mode)
        self.no_chdman = QCheckBox("chdmanを使わない")
        self.no_chdman.setChecked(self.base_settings.no_chdman)
        self.yes = QCheckBox("確認プロンプトを省略する")
        self.yes.setChecked(self.base_settings.yes)
        self.force_large_sync = QCheckBox("大きな同期も許可する")
        self.force_large_sync.setChecked(self.base_settings.force_large_sync)
        self.large_sync_threshold = QSpinBox()
        self.large_sync_threshold.setRange(1, 1_000_000)
        self.large_sync_threshold.setValue(self.base_settings.large_sync_threshold)

    def _workflow_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        layout.addWidget(self._workflow_summary_group())

        progress_group = QGroupBox("進行状況")
        progress_layout = QVBoxLayout(progress_group)
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 10)
        self.overall_progress.setValue(0)
        self.overall_progress.setMinimumHeight(22)
        self.phase_progress = QProgressBar()
        self.phase_progress.setRange(0, 1)
        self.phase_progress.setValue(0)
        self.phase_progress.setMinimumHeight(22)
        progress_layout.addWidget(QLabel("全体"))
        progress_layout.addWidget(self.overall_progress)
        progress_layout.addWidget(QLabel("現在の処理"))
        progress_layout.addWidget(self.phase_progress)
        layout.addWidget(progress_group)

        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.addTab(self._simple_workflow_tab(), "Simple")
        self.workflow_tabs.addTab(self._detail_workflow_tab(), "Detail")
        layout.addWidget(self.workflow_tabs)

        log_group = QGroupBox("ログ")
        log_layout = QVBoxLayout(log_group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Menlo"))
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_group, 1)
        return page

    def _simple_workflow_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        cards.addWidget(self._simple_action_button("1. 不足を確認", WorkflowAction.UPDATE_SCAN), 0, 0)
        cards.addWidget(self._simple_action_button("2. rebuildする", WorkflowAction.LOCAL_REBUILD), 0, 1)
        cards.addWidget(self._simple_action_button("3. qBittorrentで確認", WorkflowAction.QB_DRY_RUN), 1, 0, 1, 2)
        cards.setColumnStretch(0, 1)
        cards.setColumnStretch(1, 1)
        cards.setRowStretch(0, 1)
        cards.setRowStretch(1, 1)
        layout.addLayout(cards)
        return page

    def _simple_action_button(self, text: str, action: WorkflowAction) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(92)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        button.setStyleSheet("font-size: 16px; font-weight: 600;")
        button.clicked.connect(partial(self.run_action, action))
        self.action_buttons.append(button)
        return button

    def _detail_workflow_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        flow = QHBoxLayout()
        flow.setSpacing(8)
        flow.addWidget(
            self._flow_step(
                "1. 調べる",
                [
                    (WorkflowAction.UPDATE_SCAN, "XML更新してスキャン"),
                    (WorkflowAction.SCAN_MISSING, "スキャンだけ"),
                ],
            ),
            1,
        )
        flow.addWidget(self._flow_arrow())
        flow.addWidget(
            self._flow_step(
                "2. rebuild",
                [
                    (WorkflowAction.LOCAL_REBUILD, "実行"),
                    (WorkflowAction.REBUILD_PLAN, "計画だけ"),
                ],
            ),
            1,
        )
        flow.addWidget(self._flow_arrow())
        flow.addWidget(
            self._flow_step(
                "3. qBittorrent",
                [
                    (WorkflowAction.QB_DRY_RUN, "dry-run"),
                    (WorkflowAction.QB_APPLY, "適用"),
                    (WorkflowAction.QB_APPLY_RESUME, "適用して開始"),
                ],
            ),
            1,
        )
        flow.addWidget(self._flow_arrow())
        flow.addWidget(
            self._flow_step(
                "4. 仕上げ",
                [
                    (WorkflowAction.FINAL_SCAN, "最終スキャン"),
                    (WorkflowAction.CHECK_BROKEN, "破損チェック"),
                    (WorkflowAction.REMOTE_BACKUP, "バックアップ"),
                    (WorkflowAction.RESTORE, "復元..."),
                ],
            ),
            1,
        )
        layout.addLayout(flow)

        command_group = QGroupBox("CLIコマンド")
        command_layout = QVBoxLayout(command_group)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("表示する操作"))
        self.preview_action = QComboBox()
        for action in self.ACTION_ORDER:
            self.preview_action.addItem(ACTION_TITLES[action], action.value)
        self.preview_action.currentIndexChanged.connect(self._update_command_preview)
        selector_row.addWidget(self.preview_action, 1)
        command_layout.addLayout(selector_row)
        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumHeight(86)
        self.command_preview.setFont(QFont("Menlo"))
        command_layout.addWidget(self.command_preview)
        layout.addWidget(command_group)
        layout.addStretch(1)
        return page

    def _flow_step(self, title: str, actions: list[tuple[WorkflowAction, str]]) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        for action, text in actions:
            button = QPushButton(text)
            button.setMinimumHeight(30)
            button.clicked.connect(partial(self.run_action, action))
            layout.addWidget(button)
            self.action_buttons.append(button)
        layout.addStretch(1)
        return group

    def _flow_arrow(self) -> QLabel:
        label = QLabel("→")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = label.font()
        font.setPointSize(font.pointSize() + 8)
        label.setFont(font)
        return label

    def _workflow_summary_group(self) -> QGroupBox:
        group = QGroupBox("現在の設定")
        layout = QGridLayout(group)
        self.summary_mame = QLabel()
        self.summary_images = QLabel()
        self.summary_downloads = QLabel()
        self.summary_backup = QLabel()
        for label in [self.summary_mame, self.summary_images, self.summary_downloads, self.summary_backup]:
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        settings_button = QPushButton("設定を開く")
        settings_button.clicked.connect(lambda: self.nav.setCurrentRow(3))
        layout.addWidget(QLabel("MAME"), 0, 0)
        layout.addWidget(self.summary_mame, 0, 1)
        layout.addWidget(QLabel("images"), 1, 0)
        layout.addWidget(self.summary_images, 1, 1)
        layout.addWidget(QLabel("Downloads"), 0, 2)
        layout.addWidget(self.summary_downloads, 0, 3)
        layout.addWidget(QLabel("backup"), 1, 2)
        layout.addWidget(self.summary_backup, 1, 3)
        layout.addWidget(settings_button, 0, 4, 2, 1)
        layout.addWidget(self.remote_backup, 2, 0, 1, 5)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        return group

    def _workflow_card(
        self,
        title: str,
        actions: list[tuple[WorkflowAction, str, bool]],
        extra_widget: QWidget | None = None,
        extra_button: tuple[str, object] | None = None,
    ) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        for action, text, primary in actions:
            button = QPushButton(text)
            button.setMinimumHeight(48 if primary else 28)
            if primary:
                button.setStyleSheet("font-weight: 600;")
            button.clicked.connect(partial(self.run_action, action))
            layout.addWidget(button)
            self.action_buttons.append(button)
        if extra_widget is not None:
            layout.addWidget(extra_widget)
        if extra_button is not None:
            text, callback = extra_button
            button = QPushButton(text)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch(1)
        return group

    def _common_settings_group(self) -> QGroupBox:
        group = QGroupBox("共通設定")
        layout = QGridLayout(group)
        layout.addWidget(QLabel("MAME"), 0, 0)
        layout.addWidget(self.mame_bin, 0, 1)
        layout.addWidget(QLabel("images"), 1, 0)
        layout.addWidget(self.images, 1, 1)
        layout.addWidget(QLabel("Downloads"), 2, 0)
        layout.addWidget(self.new, 2, 1)
        layout.addWidget(QLabel("work"), 3, 0)
        layout.addWidget(self.work, 3, 1)

        right = QFrame()
        right_layout = QFormLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addRow("scan jobs", self.scan_jobs)
        right_layout.addRow("compress jobs", self.compress_jobs)
        right_layout.addRow("merge mode", self.merge_mode)
        right_layout.addRow("backup URL", self.backup_url)
        layout.addWidget(right, 0, 2, 4, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        return group

    def _reports_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        refresh = QPushButton("更新")
        refresh.clicked.connect(self.refresh_reports)
        open_dir = QPushButton("reportsを開く")
        open_dir.clicked.connect(self.open_reports_dir)
        buttons.addWidget(refresh)
        buttons.addWidget(open_dir)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        body = QSplitter(Qt.Orientation.Horizontal)
        self.report_list = QListWidget()
        self.report_list.currentTextChanged.connect(self.load_report)
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setFont(QFont("Menlo"))
        body.addWidget(self.report_list)
        body.addWidget(self.report_view)
        body.setStretchFactor(1, 1)
        layout.addWidget(body, 1)
        return page

    def _qbittorrent_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("qBittorrent")
        form = QFormLayout(group)
        form.addRow("URL", self.qb_url)
        form.addRow("user", self.qb_user)
        form.addRow("password", self.qb_password)
        form.addRow("torrent hash", self.qb_hash)
        form.addRow("torrent name", self.qb_name)
        form.addRow("timeout", self.qb_timeout)
        layout.addWidget(group)

        buttons = QHBoxLayout()
        open_webui = QPushButton("WebUIを開く")
        open_webui.clicked.connect(self.open_qbittorrent_webui)
        buttons.addWidget(open_webui)
        self._add_inline_action_button(buttons, WorkflowAction.QB_DRY_RUN)
        self._add_inline_action_button(buttons, WorkflowAction.QB_APPLY)
        self._add_inline_action_button(buttons, WorkflowAction.QB_APPLY_RESUME)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        note = QLabel("torrent未登録の場合はWebUIで追加してからdry-runを再実行します。")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._common_settings_group())
        group = QGroupBox("詳細設定")
        form = QFormLayout(group)
        form.addRow("config.env", self.config_file)
        form.addRow("rsync pass", self.rsync_pass)
        form.addRow("7z", self.sevenz_bin)
        form.addRow("rsync", self.rsync_bin)
        form.addRow("chdman", self.chdman_bin)
        form.addRow("rebuild mode", self.rebuild_mode)
        form.addRow(self.no_chdman)
        form.addRow(self.yes)
        form.addRow(self.force_large_sync)
        form.addRow("large sync threshold", self.large_sync_threshold)
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _add_action_button(self, layout: QGridLayout, row: int, column: int, action: WorkflowAction) -> None:
        button = QPushButton(ACTION_TITLES[action])
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(partial(self.run_action, action))
        layout.addWidget(button, row, column)
        self.action_buttons.append(button)

    def _add_inline_action_button(self, layout: QHBoxLayout, action: WorkflowAction) -> None:
        button = QPushButton(ACTION_TITLES[action])
        button.clicked.connect(partial(self.run_action, action))
        layout.addWidget(button)
        self.action_buttons.append(button)

    def _connect_setting_changes(self) -> None:
        line_edits = [
            self.mame_bin.line_edit,
            self.images.line_edit,
            self.new.line_edit,
            self.work.line_edit,
            self.backup_url,
            self.qb_url,
            self.qb_user,
            self.qb_password,
            self.qb_hash,
            self.qb_name,
            self.config_file.line_edit,
            self.rsync_pass.line_edit,
            self.sevenz_bin,
            self.rsync_bin,
            self.chdman_bin,
        ]
        for line_edit in line_edits:
            line_edit.textChanged.connect(self._update_command_preview)
        for spin_box in [
            self.scan_jobs,
            self.compress_jobs,
            self.qb_timeout,
            self.large_sync_threshold,
        ]:
            spin_box.valueChanged.connect(self._update_command_preview)
        for combo in [self.merge_mode, self.rebuild_mode]:
            combo.currentTextChanged.connect(self._update_command_preview)
        for checkbox in [self.remote_backup, self.no_chdman, self.yes, self.force_large_sync]:
            checkbox.toggled.connect(self._update_command_preview)

    def _collect_settings(self) -> GuiSettings:
        return GuiSettings(
            config_file=self.config_file.value(),
            mame_bin=self.mame_bin.value(),
            images=self.images.value(),
            new=self.new.value(),
            work=self.work.value(),
            rsync_pass=self.rsync_pass.value(),
            backup_url=self._optional_text(self.backup_url),
            scan_jobs=self.scan_jobs.value(),
            compress_jobs=self.compress_jobs.value(),
            merge_mode=self.merge_mode.currentText(),
            rebuild_mode=self.rebuild_mode.currentText(),
            sevenz_bin=self.sevenz_bin.text().strip() or "7z",
            rsync_bin=self.rsync_bin.text().strip() or "rsync",
            chdman_bin=self.chdman_bin.text().strip() or "chdman",
            no_chdman=self.no_chdman.isChecked(),
            yes=self.yes.isChecked(),
            force_large_sync=self.force_large_sync.isChecked(),
            large_sync_threshold=self.large_sync_threshold.value(),
            remote_backup_after_rebuild=self.remote_backup.isChecked(),
            qbittorrent_url=self._optional_text(self.qb_url),
            qbittorrent_user=self.qb_user.text().strip() or "admin",
            qbittorrent_password=self._optional_text(self.qb_password),
            qbittorrent_hash=self._optional_text(self.qb_hash),
            qbittorrent_name=self._optional_text(self.qb_name),
            qbittorrent_priority=self.base_settings.qbittorrent_priority,
            qbittorrent_skip_priority=self.base_settings.qbittorrent_skip_priority,
            qbittorrent_timeout=self.qb_timeout.value(),
            python_executable=self.base_settings.python_executable,
        )

    def _optional_text(self, line_edit: QLineEdit) -> str | None:
        value = line_edit.text().strip()
        return value or None

    def _current_preview_action(self) -> WorkflowAction:
        return WorkflowAction(self.preview_action.currentData())

    def _update_command_preview(self) -> None:
        self._refresh_settings_summary()
        if not hasattr(self, "command_preview"):
            return
        try:
            spec = build_command(self._collect_settings(), self._current_preview_action())
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.command_preview.setPlainText(str(exc))
            return
        self.command_preview.setPlainText(spec.display())

    def _refresh_settings_summary(self) -> None:
        if not hasattr(self, "summary_mame"):
            return
        settings = self._collect_settings()
        self.summary_mame.setText(str(settings.mame_bin))
        self.summary_images.setText(str(settings.images))
        self.summary_downloads.setText(str(settings.new))
        self.summary_backup.setText(settings.backup_url or "未設定")

    def run_action(self, action: WorkflowAction) -> None:
        if self.process is not None:
            QMessageBox.warning(self, "実行中", "現在の処理が終わるまで待ってください。")
            return
        spec = build_command(self._collect_settings(), action)
        if spec.confirm and QMessageBox.question(self, "確認", spec.confirm) != QMessageBox.StandardButton.Yes:
            return
        for path in spec.required_dirs:
            path.mkdir(parents=True, exist_ok=True)
        self.active_spec = spec
        self.log_view.appendPlainText(f"$ {spec.display()}")
        self.status_label.setText(spec.title)
        self.overall_progress.setRange(0, spec.workflow_total)
        self.overall_progress.setValue(max(spec.workflow_index - 1, 0))
        self.phase_progress.setRange(0, max(len(spec.phases), 1))
        self.phase_progress.setValue(0)
        self._set_running(True)

        process = QProcess(self)
        process.setProgram(spec.program)
        process.setArguments(list(spec.arguments))
        process.setWorkingDirectory(str(Path.cwd()))
        environment = QProcessEnvironment.systemEnvironment()
        for key, value in spec.environment.items():
            environment.insert(key, value)
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._process_finished)
        self.process = process
        process.start()
        if not process.waitForStarted(3000):
            self.log_view.appendPlainText("ERROR: process failed to start")
            self.process = None
            self._set_running(False)

    def stop_process(self) -> None:
        if self.process is None:
            return
        self.log_view.appendPlainText("stopping process...")
        self.process.terminate()
        self.stop_button.setEnabled(False)

    def _read_stdout(self) -> None:
        if self.process is not None:
            self._append_output(bytes(self.process.readAllStandardOutput()).decode(errors="replace"))

    def _read_stderr(self) -> None:
        if self.process is not None:
            self._append_output(bytes(self.process.readAllStandardError()).decode(errors="replace"))

    def _append_output(self, text: str) -> None:
        if not text:
            return
        self.log_view.appendPlainText(text.rstrip())
        if self.active_spec is None:
            return
        for line in text.splitlines():
            index = phase_index(line, self.active_spec.phases)
            if index is not None:
                self.phase_progress.setValue(index)

    def _process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self.active_spec is not None and exit_code == 0:
            self.phase_progress.setValue(self.phase_progress.maximum())
            self.overall_progress.setValue(self.active_spec.workflow_index)
        status = "完了" if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit else "停止"
        self.log_view.appendPlainText(f"{status}: exit code {exit_code}")
        self.status_label.setText(status)
        self.process = None
        self.active_spec = None
        self._set_running(False)
        self.refresh_reports()

    def _set_running(self, running: bool) -> None:
        for button in self.action_buttons:
            button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.save_button.setEnabled(not running)

    def refresh_reports(self) -> None:
        settings = self._collect_settings()
        current = self.report_list.currentItem().text() if self.report_list.currentItem() else None
        self.report_list.clear()
        reports_dir = settings.reports_dir
        if not reports_dir.exists():
            self.report_view.setPlainText(f"{reports_dir} does not exist")
            return
        for path in sorted(reports_dir.iterdir()):
            if path.is_file():
                self.report_list.addItem(path.name)
        if current:
            matches = self.report_list.findItems(current, Qt.MatchFlag.MatchExactly)
            if matches:
                self.report_list.setCurrentItem(matches[0])

    def load_report(self, name: str) -> None:
        if not name:
            return
        path = self._collect_settings().reports_dir / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            text = f"ERROR: {exc}"
        self.report_view.setPlainText(text)

    def open_reports_dir(self) -> None:
        reports_dir = self._collect_settings().reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(reports_dir)))

    def open_qbittorrent_webui(self) -> None:
        url = self.qb_url.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def save_config(self) -> None:
        settings = self._collect_settings()
        path = settings.config_file
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"BACKUP_URL={settings.backup_url or ''}",
            f"QBITTORRENT_URL={settings.qbittorrent_url or ''}",
            f"QBITTORRENT_USER={settings.qbittorrent_user}",
            f"QBITTORRENT_PASSWORD={settings.qbittorrent_password or ''}",
            f"SCAN_JOBS={settings.scan_jobs}",
            f"COMPRESS_JOBS={settings.compress_jobs}",
            f"{GUI_REMOTE_BACKUP_AFTER_REBUILD}={'1' if settings.remote_backup_after_rebuild else '0'}",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.status_label.setText("設定保存済み")


def main() -> int:
    app = QApplication([])
    window = MameManagerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
