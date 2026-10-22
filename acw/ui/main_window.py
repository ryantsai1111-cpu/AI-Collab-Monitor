"""Native desktop workspace. All backend interaction passes through WorkspaceCore.

Qt workers isolate backend handshakes and requests from the GUI thread. This module
never spawns a shell, reads credentials, or creates an agent session on startup.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from ..presentation import project_label, task_label, compact
from .. import approvals, playbooks
from ..orchestrator import Orchestrator
from ..monitor import AgentRail, MonitorDashboard, collect_snapshot
from ..theme import SPACE, build_style, console_palette, desktop_palette, metal_palette

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, QByteArray
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTabBar,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .widgets import Worker, button, identifier, label, plain
from .dialogs import DetailDialog, HandoffDialog, PlaybookDialog, ScreenshotReviewDialog
from .artifacts import ArtifactPanel
from .navigator import SessionNavigator
from .agent_panel import AgentPanel, ROLE_LABELS, ROLE_NAMES


# Same folder as run.py: the monitor lives inside the repository, not on the Desktop.
LEGACY_MONITOR_ROOT = str(Path(__file__).resolve().parents[2] / "AI-Collab-Monitor")
AGENTS = ("claude", "dot", "codex", "local")
STATUSES = ("NEW", "PLANNING", "REVIEWING", "READY", "IMPLEMENTING", "VERIFYING",
            "WAITING_USER", "BLOCKED", "DONE", "FAILED", "CANCELLED")




STATUS_LABELS = dict(zip(STATUSES, ("新任務", "規劃中", "主審中", "可實作", "實作中", "驗證中",
                                  "等待使用者", "受阻", "已完成", "失敗", "已取消")))




































































































































































































































































# Shown inline in a conversation. Everything else stays in the timeline, raw events and logs.
TRANSCRIPT_EVENTS = ("tool_start", "tool_result", "tool", "command", "command_output", "file", "file_edit", "diff",
                     "test", "error", "handoff", "stop", "recovery", "approval", "approval_request", "tool_approval")


class MainWindow(QMainWindow):
    def __init__(self, core):
        super().__init__()
        self.core = core
        core.enable_agent_independence()
        self.agents = list(core.agent_ids)
        self.role_names = {agent: core.agent_name(agent) for agent in self.agents}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(8)
        self.workers = set()
        self.focused_agent = None
        self.last_event = "No events yet"
        self._loading = False
        self._closed = False
        self._close_pending = False
        self._legacy_busy = False
        self._legacy_clock = 0
        self._git_busy = False
        self._git_clock = 0
        self._context_views = {}
        self._agent_views = {}
        self._loaded_agent_keys = {}
        self._agent_operations = {}
        self._opening_agents = set()
        self._loaded_context_key = None
        self._layout_updating = False
        self._grid_sizes = [400] * len(self.agents)
        self._preferred_agent = core.get_setting('ui.active_agent', 'claude')
        if self._preferred_agent not in self.agents: self._preferred_agent = self.agents[0]
        self.setWindowTitle("ACW · Monitor 工作台")
        self.setObjectName("ai_collaboration_workspace")
        self.resize(1530, 920)
        self.setMinimumSize(640, 420)
        self.theme_name = core.get_setting('ui.theme', 'desktop')
        self.apply_theme(self.theme_name)
        root = QWidget()
        root.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(SPACE['md'], SPACE['md'], SPACE['md'], SPACE['sm'])
        layout.setSpacing(SPACE['md'])
        heading = QHBoxLayout()
        self.sidebar_toggle = button("☰", self.toggle_sidebar, "sidebar_toggle")
        self.sidebar_toggle.setAccessibleName("切換專案與對話側欄")
        self.sidebar_toggle.setToolTip("專案與對話 · Ctrl+B")
        self.sidebar_toggle.setCheckable(True)
        self.sidebar_toggle.setChecked(True)
        heading.addWidget(self.sidebar_toggle)
        self.console_mark = label("ACW / CONTROL ROOM")
        self.console_mark.setObjectName("console_mark")
        self.console_mark.setWordWrap(False)
        heading.addWidget(self.console_mark)
        self.context_title = label("AI 協作工作區")
        self.context_title.setObjectName("brand")
        self.context_title.setWordWrap(False)
        self.context_title.setMinimumWidth(0)
        self.context_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        heading.addWidget(self.context_title, 1)
        self.layout_mode = QComboBox()
        self.layout_mode.setObjectName("layout_mode")
        for title, value in (("自動布局", "Auto"), ("並排", "Three panes"), ("專注", "Focus")):
            self.layout_mode.addItem(title, value)
        saved_layout = core.get_setting('ui.layout_mode', 'Focus')
        self.layout_mode.setCurrentIndex(max(0, self.layout_mode.findData(saved_layout)))
        self.layout_mode.setAccessibleName("版面")
        self.layout_mode.setToolTip("專注：主要對話＋Agent 側欄；並排：多個完整對話；窄視窗保留可讀字級")
        self.layout_mode.currentIndexChanged.connect(self.update_workspace_layout)
        heading.addWidget(label("版面", True))
        heading.addWidget(self.layout_mode)
        self.auto_button = button("自動協作…", self.start_auto_collab, "auto_collab")
        self.auto_button.setToolTip("選擇任意兩個 Agent 派工與驗收，同一 provider 也可以")
        self.workspace_views = QWidget()
        self.workspace_views.setObjectName('workspace_views')
        self.workspace_views.setAccessibleName('工作台與協作總覽')
        view_row = QHBoxLayout(self.workspace_views)
        view_row.setContentsMargins(0, 0, 0, 0)
        view_row.setSpacing(SPACE['xs'])
        self.workspace_view_group = QButtonGroup(self)
        self.workspace_view_buttons = []
        for index, title in enumerate(('工作台', '協作總覽')):
            control = QToolButton()
            control.setText(title)
            control.setCheckable(True)
            control.setChecked(index == 0)
            control.setProperty('workspace_view', True)
            control.setAccessibleName(title)
            self.workspace_view_group.addButton(control, index)
            self.workspace_view_buttons.append(control)
            view_row.addWidget(control)
        self.workspace_view_group.idClicked.connect(self.select_workspace_view)
        self.monitor_button = button("協作總覽", self.toggle_monitor, "monitor_toggle")
        self.monitor_button.hide()
        self.monitor_button.setToolTip("協作總覽：進度、規則與待核准項目")
        heading.addWidget(self.workspace_views)
        self.details_toggle = button("Work details", self.toggle_details, "details_toggle")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setToolTip("工具、命令、變更、測試、時間線與交接 · Ctrl+Shift+D")
        workspace_menu = QToolButton()
        workspace_menu.setObjectName("workspace_actions")
        workspace_menu.setText("⋯")
        workspace_menu.setAccessibleName("工作區操作")
        workspace_menu.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(workspace_menu)
        for text, callback in (("工作紀錄…", self.show_records), ("任務筆記…", self.notes), ("比較回覆…", self.compare),
                               ("差異／測試／附件…", self.inspect_artifacts), ("匯出…", self.export),
                               ("角色腳本…", self.edit_playbook), ("設定…", self.settings),
                               ("診斷…", self.diagnostics), ("停止全部 Agent…", self.stop_task)):
            menu.addAction(text, callback)
        workspace_menu.setMenu(menu)
        heading.addWidget(workspace_menu)
        layout.addLayout(heading)
        self.orchestrator = None
        self.run_bar = QFrame()
        self.run_bar.setObjectName("run_bar")
        run_row = QHBoxLayout(self.run_bar)
        run_row.setContentsMargins(SPACE['md'], SPACE['sm'], SPACE['sm'], SPACE['sm'])
        self.run_status = label("")
        self.run_status.setObjectName("run_status")
        self.run_status.setWordWrap(False)
        self.run_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        run_row.addWidget(self.run_status, 1)
        self.run_stop = button("Stop", self.stop_auto_collab, "stop")
        run_row.addWidget(self.run_stop)
        self.run_close = button("Close", self.run_bar.hide)
        run_row.addWidget(self.run_close)
        self.run_bar.hide()
        layout.addWidget(self.run_bar)
        self.run_timer = QTimer(self)
        self.run_timer.timeout.connect(self.tick_auto_collab)
        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(230)
        self.sidebar.setMaximumWidth(310)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(SPACE['md'], SPACE['md'], SPACE['md'], SPACE['md'])
        side.setSpacing(SPACE['sm'])
        self.sidebar_agent_title = label(self.role_names[self._preferred_agent])
        self.sidebar_agent_title.setObjectName('sidebar_agent_title')
        agent_heading = QHBoxLayout()
        agent_heading.addWidget(self.sidebar_agent_title, 1)
        self.playbook_button = button('角色腳本', self.edit_playbook)
        agent_heading.addWidget(self.playbook_button)
        side.addLayout(agent_heading)
        self.sidebar_agent_meta = label('', True)
        side.addWidget(self.sidebar_agent_meta)
        side.addWidget(label('目前綁定', True))
        self.records_dialog = QDialog(self)
        self.records_dialog.setWindowTitle('工作紀錄')
        self.records_dialog.resize(420, 520)
        records_layout = QVBoxLayout(self.records_dialog)
        records_page = QWidget()
        self.records_page = records_page
        records_layout.addWidget(records_page)
        self.records_dialog.finished.connect(lambda _: (self.update_context_title(), self.refresh_work_details()))
        records = QVBoxLayout(records_page)
        records.setContentsMargins(0, 0, 0, 0)
        records.setSpacing(SPACE['sm'])
        records.addWidget(label('本機紀錄管理', True))
        records.addWidget(label('此處管理舊任務與紀錄，不會切換任何 Agent 的 Project 或 Session。', True))
        records.addWidget(label("紀錄的專案與任務", True))
        project_row = QHBoxLayout()
        self.project_combo = QComboBox()
        self.project_combo.setObjectName("global_project")
        self.project_combo.setAccessibleName("目前專案")
        self.project_combo.setMinimumContentsLength(10)
        self.project_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.project_combo.currentIndexChanged.connect(self.project_changed)
        project_row.addWidget(self.project_combo, 1)
        create_project = button("+", lambda: self.new_project(global_scope=True), "new_project")
        create_project.setAccessibleName("新增專案")
        create_project.setToolTip("新增專案")
        project_row.addWidget(create_project)
        records.addLayout(project_row)
        task_row = QHBoxLayout()
        self.task_combo = QComboBox()
        self.task_combo.setObjectName("global_task")
        self.task_combo.setAccessibleName("目前任務")
        self.task_combo.setMinimumContentsLength(10)
        self.task_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.task_combo.currentIndexChanged.connect(self.task_changed)
        task_row.addWidget(self.task_combo, 1)
        create_task = button("+", self.new_task, "new_task")
        create_task.setAccessibleName("新增任務")
        create_task.setToolTip("新增任務")
        task_row.addWidget(create_task)
        records.addLayout(task_row)
        self.task_status = QComboBox()
        self.task_status.addItem("尚未選擇任務", None)
        for value in STATUSES:
            self.task_status.addItem(STATUS_LABELS[value], value)
        self.task_status.setObjectName("task_status")
        self.task_status.setAccessibleName("任務狀態")
        self.task_status.currentIndexChanged.connect(lambda _: self.status_changed(self.task_status.currentData()))
        records.addWidget(label("紀錄狀態（與 Agent 執行狀態分開）", True))
        records.addWidget(self.task_status)
        records.addStretch()
        records.addWidget(button('任務筆記…', self.notes))
        records.addWidget(button('匯出紀錄…', self.export))
        self.mode = QComboBox()
        for title, value in (("Monitor 工作台", "Workspace"), ("協作總覽（唯讀）", "Monitor"), ("時間線", "Timeline"), ("歷史", "History")):
            self.mode.addItem(title, value)
        self.mode.setObjectName("view_mode")
        self.mode.setAccessibleName("工作區檢視")
        self.mode.currentIndexChanged.connect(lambda _: self.change_mode(self.mode.currentData()))
        side.addWidget(self.mode)
        self.mode.hide()
        views_menu = menu.addMenu('檢視')
        self.view_actions = {}
        for index in range(self.mode.count()):
            action = views_menu.addAction(self.mode.itemText(index), lambda checked=False, index=index: self.mode.setCurrentIndex(index))
            action.setCheckable(True)
            self.view_actions[self.mode.itemData(index)] = action
        views_menu.aboutToShow.connect(lambda: [action.setChecked(value == self.mode.currentData())
                                               for value, action in self.view_actions.items()])
        self.session_tabs = QTabWidget()
        self.session_tabs.setObjectName("sidebar_sessions")
        self.session_tabs.setDocumentMode(True)
        self.session_tabs.tabBar().hide()
        self.session_tabs.setAccessibleName("各角色對話")
        side.addWidget(self.session_tabs, 1)
        side.addWidget(label('可接續的對話', True))
        self.navigator = SessionNavigator(self)
        side.addWidget(self.navigator, 2)
        side.addWidget(button("Settings…", self.settings, "settings"))
        self.workspace_splitter.addWidget(self.sidebar)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(SPACE['sm'])
        roles = QHBoxLayout()
        self.role_tabs = QTabBar()
        self.role_tabs.setObjectName("role_tabs")
        self.role_tabs.setExpanding(False)
        self.role_tabs.setUsesScrollButtons(True)
        self.role_tabs.setElideMode(Qt.ElideNone)
        self.role_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.role_tabs.setDrawBase(False)
        self.role_tabs.setAccessibleName("對話角色")
        for agent in self.agents:
            self.role_tabs.addTab(self.role_names[agent] + " · " + ROLE_LABELS[self.core.provider(agent)])
        self.role_tabs.currentChanged.connect(self.select_role)
        roles.addWidget(self.role_tabs, 1)
        self.unfocus_button = button("並排檢視", lambda: self.focus_agent(None), "unfocus")
        self.unfocus_button.hide()
        content_layout.addLayout(roles)
        workspace_actions = QHBoxLayout()
        self.workspace_hint = label("MONITOR / LIVE WORKSPACE")
        self.workspace_hint.setObjectName('console_section')
        self.workspace_hint.setWordWrap(False)
        self.workspace_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        workspace_actions.addWidget(self.workspace_hint, 1)
        workspace_actions.addWidget(self.auto_button)
        workspace_actions.addWidget(self.details_toggle)
        content_layout.addLayout(workspace_actions)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.splitter = QSplitter(Qt.Horizontal)
        self.panels = {agent: AgentPanel(agent, self) for agent in self.agents}
        for agent, panel in self.panels.items():
            self.splitter.addWidget(panel)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(panel.session_controls)
            self.session_tabs.addTab(scroll, self.role_names[agent])
        self.session_tabs.currentChanged.connect(self.sidebar_role_changed)
        self.splitter.setChildrenCollapsible(False)
        self.chat_workspace = QWidget()
        chat_layout = QHBoxLayout(self.chat_workspace)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(SPACE['md'])
        chat_layout.addWidget(self.splitter, 1)
        self.agent_rail = AgentRail()
        self.agent_rail.box.insertWidget(self.agent_rail.box.indexOf(self.agent_rail.add_button) + 1, self.unfocus_button)
        menu.addAction('新增 Agent…', self.add_agent_dialog)
        self.agent_rail.open_role.connect(self.open_monitor_role)
        self.agent_rail.add_agent.connect(self.add_agent_dialog)
        chat_layout.addWidget(self.agent_rail)
        self.stack.addWidget(self.chat_workspace)
        self.timeline = QTreeWidget()
        self.timeline.setHeaderLabels(["Time", "Agent", "Event", "Status", "Summary"])
        self.timeline.setAlternatingRowColors(True)
        self.timeline.itemDoubleClicked.connect(lambda item: self.show_detail("Event detail", item.data(0, Qt.UserRole)))
        self.stack.addWidget(self.timeline)
        self.history_page = self.build_history()
        self.stack.addWidget(self.history_page)
        self.monitor_dashboard = MonitorDashboard(names=self.role_names)
        self.monitor_dashboard.open_role.connect(self.open_monitor_role)
        self.monitor_dashboard.open_transcripts.connect(self.show_monitor_transcripts)
        self.stack.addWidget(self.monitor_dashboard)
        self.monitor_dashboard.apply_theme(self.theme_name)
        self.agent_rail.setProperty('theme', self.theme_name)
        self._monitor_clock = 0.0
        content_layout.addWidget(self.stack, 1)
        self.details_panel = QFrame()
        self.details_panel.setObjectName("work_details")
        self.details_panel.setMinimumHeight(140)
        self.details_panel.setMaximumHeight(300)
        detail_layout = QVBoxLayout(self.details_panel)
        detail_layout.setContentsMargins(SPACE['md'], SPACE['sm'], SPACE['md'], SPACE['sm'])
        self.details_tabs = QTabWidget()
        self.details_tabs.setObjectName("details_tabs")
        self.detail_trees = {}
        for title in ("Tools", "Commands", "Changes", "Tests", "Timeline", "Handoffs"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, SPACE['sm'], 0, 0)
            tree = QTreeWidget()
            tree.setObjectName("details_" + title.lower())
            tree.setHeaderLabels(["來源", "事件／狀態", "摘要"])
            tree.setAlternatingRowColors(True)
            tree.setColumnWidth(0, 90)
            tree.setColumnWidth(1, 175)
            tree.itemDoubleClicked.connect(lambda item: self.show_detail("Recorded detail", item.data(0, Qt.UserRole)))
            page_layout.addWidget(tree, 1)
            self.detail_trees[title] = tree
            if title in ("Changes", "Tests"):
                page_layout.addWidget(button("Open Diff / Tests / Artifacts…", self.inspect_artifacts))
            if title == "Timeline":
                page_layout.addWidget(button("Open full timeline", lambda: self.mode.setCurrentIndex(self.mode.findData("Timeline"))))
            if title == "Handoffs":
                handoff_row = QHBoxLayout()
                self.handoff_mode = QComboBox()
                self.handoff_mode.setObjectName("handoff_mode")
                self.handoff_mode.addItem("預覽後傳送", "assisted")
                self.handoff_mode.addItem("手動直接傳送", "manual")
                saved = str(core.get_setting("handoff.mode", "assisted"))
                self.handoff_mode.setCurrentIndex(max(0, self.handoff_mode.findData(saved)))
                self.handoff_mode.setToolTip("Assisted previews each handoff. Manual sends on your explicit Forward click. Automatic is OFF.")
                self.handoff_mode.currentIndexChanged.connect(lambda _: core.set_setting("handoff.mode", self.handoff_mode.currentData()))
                handoff_row.addWidget(self.handoff_mode)
                self.flow_button = QToolButton()
                self.flow_button.setObjectName("collaboration_flow")
                self.flow_button.setText("交接流程 ▾")
                self.flow_button.setToolTip("Claude → G8毛 → Codex · each step is an explicit user action")
                self.flow_button.setPopupMode(QToolButton.InstantPopup)
                flow_menu = QMenu(self.flow_button)
                flow_menu.aboutToShow.connect(lambda: self.populate_flow_menu(flow_menu))
                self.flow_button.setMenu(flow_menu)
                handoff_row.addWidget(self.flow_button)
                handoff_row.addWidget(label("自動協作關閉", True))
                handoff_row.addStretch()
                page_layout.addLayout(handoff_row)
            self.details_tabs.addTab(page, {"Tools": "工具", "Commands": "命令", "Changes": "變更", "Tests": "測試", "Timeline": "時間線", "Handoffs": "交接"}[title])
        detail_layout.addWidget(self.details_tabs)
        self.details_panel.hide()
        self.details_dialog = None
        content_layout.addWidget(self.details_panel)
        self.workspace_splitter.addWidget(content)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([260, 1230])
        self.workspace_splitter.splitterMoved.connect(lambda *_: self.update_workspace_layout())
        layout.addWidget(self.workspace_splitter, 1)
        self.footer = label("本機工作區 · 自動協作關閉 · 僅在手動要求時連線", True)
        self.footer.setMaximumHeight(36)
        layout.addWidget(self.footer)
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setObjectName("workspace_viewport")
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.NoFrame)
        self.workspace_scroll.setWidget(root)
        self.setCentralWidget(self.workspace_scroll)
        for text, shortcut, callback in (
            ("Fullscreen", "F11", lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen()),
            ("Return to auto layout", "Escape", lambda: self.focus_agent(None)),
            ("Toggle sidebar", "Ctrl+B", self.toggle_sidebar),
            ("Toggle work details", "Ctrl+Shift+D", self.toggle_details),
            ("Settings", "Ctrl+,", self.settings),
            ("新對話", "Ctrl+N", lambda: self.panels[self._preferred_agent].new_session()),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        for index, agent in enumerate(self.agents[:9], 1):
            action = QAction("Focus " + self.role_names[agent], self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
            action.triggered.connect(lambda checked=False, agent=agent: self.focus_agent(agent))
            self.addAction(action)
        self.reload_context()
        geometry = core.get_setting("ui.geometry", "")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(str(geometry).encode()))
        self.ensure_visible()
        if core.get_setting("ui.always_on_top", False):
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_events)
        self.timer.start(100)
        # Work Details rebuilds six trees from 500 events; coalesce bursts of event batches.
        self._details_dirty = False
        self._details_timer = QTimer(self)
        self._details_timer.setSingleShot(True)
        self._details_timer.setInterval(500)
        self._details_timer.timeout.connect(self.flush_work_details)
        # Follow conversations that the desktop apps keep writing to while they are shown here.
        self._sync_stamp, self._sync_floor, self._syncing = {}, {}, set()
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.sync_local_conversations)
        self.sync_timer.start(3000)
        QTimer.singleShot(0, self, self.update_workspace_layout)
        self.refresh_monitor()

    def apply_theme(self, name):
        self.theme_name = name if name in ('desktop', 'hacker', 'metal') else 'desktop'
        self.setProperty('theme', self.theme_name)
        palettes = {'desktop': desktop_palette, 'hacker': console_palette, 'metal': metal_palette}
        QApplication.instance().setPalette(palettes[self.theme_name]())
        self.setStyleSheet(build_style(self.theme_name))
        if hasattr(self, 'monitor_dashboard'):
            self.monitor_dashboard.apply_theme(self.theme_name)
            for panel in self.panels.values():
                panel.update_state_style()
            self.navigator.fill()
            self.refresh_monitor()

    def edit_playbook(self):
        PlaybookDialog(self.core, self._preferred_agent, self).exec()

    def add_agent_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('新增獨立 Agent')
        form = QFormLayout(dialog)
        provider = QComboBox()
        provider.setObjectName('new_agent_provider')
        for key in ('claude', 'codex', 'local'):
            provider.addItem(ROLE_NAMES[key], key)
        name = QLineEdit()
        name.setObjectName('new_agent_name')
        name.setMaxLength(80)
        name.setPlaceholderText('例如：Claude 審查、Local 研究')
        project = QComboBox()
        project.addItem('稍後選擇專案', None)
        for row in self.core.list_projects():
            project.addItem(row['name'], row['id'])
        project.setCurrentIndex(max(0, project.findData(identifier(self.view_project() or {}))))
        form.addRow('後端', provider)
        form.addRow('名稱', name)
        form.addRow('專案', project)
        form.addRow(label('建立後可獨立選擇 session。Hermes 的 provider／模型可在設定中個別調整；連線由你啟動。', True))
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        form.addRow(actions)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.add_agent_instance(provider.currentData(), name.text().strip() or
                                        provider.currentText() + ' ' + str(len(self.agents) + 1),
                                        project_id=project.currentData())
            except Exception as exc:
                self.show_error(str(exc))

    def add_agent_instance(self, provider, name, *, project_id=None):
        record = self.core.create_agent_instance(provider, name, project_id=project_id)
        agent = record['id']
        self.save_context_state()
        self.agents.append(agent)
        self.role_names[agent] = record['name']
        panel = AgentPanel(agent, self)
        self.panels[agent] = panel
        self.splitter.addWidget(panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel.session_controls)
        self.session_tabs.addTab(scroll, record['name'])
        self.role_tabs.addTab(record['name'])
        self.history_agent.addItem(record['name'], agent)
        self._grid_sizes.append(400)
        self.reload_context()
        self.focus_role(agent)
        self.refresh_monitor()
        return agent

    def show_instance_sessions(self, agent):
        if agent in AGENTS:
            return self.show_desktop_sessions(agent)
        # Discovery operates on the selected instance and imports into its own registry.
        self.show_sessions(agent)
        self.panels[agent].discover_sessions()

    def context_key(self):
        task = self.core.current_task or {}
        return (identifier(self.core.current_project or {}), identifier(task),
                tuple(task.get(agent + "_session") or "" for agent in self.agents))

    def agent_context_key(self, agent):
        if agent=='dot': return ('dot-conversation',getattr(self.core.adapters.get('dot'),'target',''))
        task = self.core.agent_task(agent) or {}
        return (agent, identifier(self.core.agent_project(agent) or {}), identifier(task), task.get(agent + '_session') or '')

    def view_task(self):
        if hasattr(self, 'records_dialog') and self.records_dialog.isVisible():
            return self.core.current_task
        return self.core.agent_task(self._preferred_agent)

    def view_project(self):
        if hasattr(self, 'records_dialog') and self.records_dialog.isVisible():
            return self.core.current_project
        return self.core.agent_project(self._preferred_agent)

    def update_context_title(self):
        if not hasattr(self, 'context_title'): return
        if hasattr(self, 'sidebar_agent_title'):
            agent = self._preferred_agent
            state = self.panels[agent].state.text() if hasattr(self, 'panels') else ''
            self.sidebar_agent_title.setText(self.role_names[agent])
            self.sidebar_agent_meta.setText((playbooks.load(self.core, agent)['role'] or ROLE_LABELS[self.core.provider(agent)]) + '\n' + state)
        project, task = self.view_project() or {}, self.view_task() or {}
        prefix = '本機紀錄' if hasattr(self, 'records_dialog') and self.records_dialog.isVisible() else self.role_names[self._preferred_agent]
        sid = (task.get(self._preferred_agent + '_session') or '') if prefix != '本機紀錄' else ''
        saved = self.core.store.get('sessions', {'agent': self._preferred_agent, 'id': sid}) if sid else None
        title = (saved or {}).get('title') or task.get('title') or '新對話'
        full_title = prefix + ' · ' + (project.get('name') or '選擇 Project') + ' › ' + title
        self.context_title.setText(compact(full_title, 90))
        self.context_title.setToolTip(full_title)

    def save_context_state(self):
        for agent, key in self._loaded_agent_keys.items():
            self._agent_views[key] = self.panels[agent].capture_view_state()
        if self._loaded_context_key is not None:
            self._context_views[self._loaded_context_key] = {
                "panels": {agent: panel.capture_view_state() for agent, panel in self.panels.items()},
                "role": self._preferred_agent,
                "session_tab": self.session_tabs.currentIndex(),
                "details_tab": self.details_tabs.currentIndex(),
                "detail_selections": {name: tree.currentItem().data(0, Qt.UserRole) if tree.currentItem() else None
                                      for name, tree in self.detail_trees.items()},
            }

    def toggle_sidebar(self, checked=False):
        visible = self.sidebar.isHidden()
        self.sidebar.setVisible(visible)
        self.sidebar_toggle.setChecked(visible)
        if not visible:
            self.sidebar_toggle.setFocus()
        QTimer.singleShot(0, self, self.update_workspace_layout)

    def show_records(self):
        self.records_dialog.show()
        self.records_dialog.raise_()
        self.update_context_title()
        self.refresh_work_details()

    def show_sessions(self, agent):
        self.sidebar.show()
        self.sidebar_toggle.setChecked(True)
        self.focus_role(agent)
        self.panels[agent].session.setFocus()
        QTimer.singleShot(0, self, self.update_workspace_layout)

    def sidebar_role_changed(self, index):
        if index >= 0 and hasattr(self, "role_tabs"):
            self.role_tabs.setCurrentIndex(index)

    def select_role(self, index):
        if index < 0 or not hasattr(self, "panels"):
            return
        self._preferred_agent = self.agents[index]
        if not self._loading: self.core.set_setting('ui.active_agent', self._preferred_agent)
        self.role_tabs.blockSignals(True)
        self.role_tabs.setCurrentIndex(index)
        self.role_tabs.blockSignals(False)
        self.session_tabs.blockSignals(True)
        self.session_tabs.setCurrentIndex(index)
        self.session_tabs.blockSignals(False)
        if hasattr(self, 'navigator'):
            self.navigator.set_agent(self._preferred_agent)
        self.update_context_title()
        self.refresh_work_details()
        if self.focused_agent is not None:
            self.update_workspace_layout()
        if hasattr(self, 'monitor_dashboard'):
            self.refresh_monitor()

    def update_role_tabs(self):
        if not hasattr(self, "panels"):
            return
        self.update_context_title()
        for index, agent in enumerate(self.agents):
            panel = self.panels[agent]
            pending = len(panel.pending_approval_events)
            panel.update_state_style()
            self.role_tabs.setTabText(index, self.role_names[agent] + " · " + ("待核准" if pending else ROLE_LABELS[self.core.provider(agent)]))
            self.role_tabs.setTabToolTip(index, f"{self.role_names[agent]} · {ROLE_LABELS[self.core.provider(agent)]} · {panel.state.text()}")

    def update_workspace_layout(self, *_):
        if not hasattr(self, "panels") or self._layout_updating or self._closed or self._close_pending:
            return
        self._layout_updating = True
        try:
            if self.height() < 700 and not self.details_panel.isHidden():
                self.show_details_dialog()
            if hasattr(self, "workspace_scroll"):
                self.workspace_scroll.widget().setMaximumHeight(max(450, self.workspace_scroll.viewport().height()))
            available = self.chat_workspace.width()
            narrow = available < len(self.agents) * 300 + (len(self.agents) - 1) * self.splitter.handleWidth()
            focused = self.layout_mode.currentData() == "Focus" or narrow
            was_focused = self.focused_agent is not None
            if focused and not was_focused and all(not panel.isHidden() for panel in self.panels.values()):
                self._grid_sizes = self.splitter.sizes()
            self.focused_agent = self._preferred_agent if focused else None
            rail_visible = focused and available >= 760 and self.mode.currentData() == 'Workspace'
            self.agent_rail.setVisible(rail_visible)
            self.role_tabs.setVisible(not rail_visible and self.mode.currentData() == 'Workspace')
            self.console_mark.setText('ACW' if self.width() < 1050 else 'ACW / CONTROL ROOM')
            self.workspace_hint.setText('MONITOR / 專注對話' if focused else 'MONITOR / 並排對話')
            for agent, panel in self.panels.items():
                panel.setVisible(not focused or agent == self._preferred_agent)
            if not focused and was_focused:
                self.splitter.setSizes(self._grid_sizes)
            self.unfocus_button.setVisible(focused and not narrow)
            self.role_tabs.setToolTip("窄視窗 · 一次顯示一個可讀的對話" if narrow else "選擇角色，或按兩下角色標題以專注")
            self.update_role_tabs()
            if self.core.get_setting('ui.layout_mode', 'Focus') != self.layout_mode.currentData():
                self.core.set_setting('ui.layout_mode', self.layout_mode.currentData())
        finally:
            self._layout_updating = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self, self.update_workspace_layout)

    def toggle_details(self, checked=False):
        if self.details_dialog is not None and self.details_dialog.isVisible():
            self.details_dialog.reject()
            return
        visible = self.details_panel.isHidden()
        if visible:
            self.refresh_work_details()
            if self.height() < 700:
                self.show_details_dialog()
            else:
                self.details_panel.show()
                self.details_toggle.setChecked(True)
        else:
            self.details_panel.hide()
            self.details_toggle.setChecked(False)
            self.details_toggle.setFocus()
        QTimer.singleShot(0, self, self.update_workspace_layout)

    def show_details_dialog(self):
        """Short screens keep the chat readable while inspecting local records."""
        if self.details_dialog is None:
            self.details_dialog = QDialog(self)
            self.details_dialog.setWindowTitle("工作詳情 · 本機紀錄")
            dialog_layout = QVBoxLayout(self.details_dialog)
            dialog_layout.setContentsMargins(SPACE['md'], SPACE['md'], SPACE['md'], SPACE['md'])
            self.details_dialog.finished.connect(self.return_details_tabs)
        self.details_panel.hide()
        self.details_panel.layout().removeWidget(self.details_tabs)
        self.details_dialog.layout().addWidget(self.details_tabs)
        self.details_dialog.resize(max(600, min(900, self.width() - 40)), max(300, min(480, self.height() - 60)))
        self.details_toggle.setChecked(True)
        self.details_dialog.show()
        self.details_dialog.raise_()

    def return_details_tabs(self, result=0):
        self.details_dialog.layout().removeWidget(self.details_tabs)
        self.details_panel.layout().addWidget(self.details_tabs)
        self.details_panel.hide()
        self.details_toggle.setChecked(False)
        self.details_toggle.setFocus()

    def flush_work_details(self):
        if self._details_dirty and self.details_toggle.isChecked():
            self.refresh_work_details()

    def refresh_work_details(self):
        self._details_dirty = False
        groups = {name: [] for name in self.detail_trees}
        task = self.view_task() or {}
        for event in reversed(self.core.events(task_id=task.get('id'), limit=500) if task else []):
            kind = event.get("type", "unknown")
            groups["Timeline"].append(event)
            if kind in ("tool_start", "tool_result", "approval", "approval_request", "tool_approval"):
                groups["Tools"].append(event)
            if kind in ("command", "command_output"):
                groups["Commands"].append(event)
            if kind in ("file", "file_edit", "diff", "patch"):
                groups["Changes"].append(event)
            if kind in ("test", "test_result"):
                groups["Tests"].append(event)
        handoffs = getattr(self.core, "handoffs", None)
        groups["Handoffs"] = handoffs(task.get('id')) if callable(handoffs) and task else []
        for name, rows in groups.items():
            tree = self.detail_trees[name]
            selected = tree.currentItem().data(0, Qt.UserRole) if tree.currentItem() else None
            selected_id = identifier(selected or {})
            scroll = tree.verticalScrollBar().value()
            tree.clear()
            if not rows:
                row = QTreeWidgetItem(["", "尚無" + {"Tools":"工具","Commands":"命令","Changes":"變更","Tests":"測試","Timeline":"時間線","Handoffs":"交接"}[name] + "紀錄", "尚無結果"])
                row.setFlags(row.flags() & ~Qt.ItemIsSelectable)
                tree.addTopLevelItem(row)
            for event in rows:
                payload = event.get("payload") or {}
                status = event.get("status") or payload.get("status") or "狀態待確認"
                kind = event.get("type") or "handoff"
                source = event.get("agent") or event.get("source_agent") or "workspace"
                target = event.get("target_agent")
                summary = event.get("summary") or payload.get("command") or payload.get("tool") or event.get("annotation") or ""
                item = QTreeWidgetItem([self.role_names.get(source, source) + (" → " + self.role_names.get(target, target) if target else ""),
                                        kind.replace("_", " ") + " · " + str(status), compact(summary, 140)])
                item.setData(0, Qt.UserRole, event)
                item.setToolTip(2, plain(event))
                tree.addTopLevelItem(item)
                if selected_id and identifier(event) == selected_id:
                    tree.setCurrentItem(item)
            tree.verticalScrollBar().setValue(scroll)

    def ensure_visible(self):
        screens = QApplication.screens()
        screen = max(screens, key=lambda s: (
            s.availableGeometry().intersected(self.frameGeometry()).width()
            * s.availableGeometry().intersected(self.frameGeometry()).height()))
        available = screen.availableGeometry()
        self.resize(min(self.width(), available.width() - 16),
                    min(self.height(), available.height() - 32))
        x = max(available.left(), min(self.x(), available.right() - self.width() - 16))
        y = max(available.top(), min(self.y(), available.bottom() - self.height() - 32))
        self.move(x, y)

    def run(self, operation, callback=None, agent=None, on_error=None):
        worker = Worker(operation)
        self.workers.add(worker)
        if agent:
            self._agent_operations[agent] = self._agent_operations.get(agent, 0) + 1
            self.panels[agent].update_controls()
        def failed(message):
            if agent:
                state = getattr(self.core.adapters.get(agent), 'state', 'Disconnected') if self.core.missing_session(agent) else 'Error'
                self.panels[agent].set_state(state)
                self.panels[agent].notice.setText(message)
                self.panels[agent].notice.setToolTip(message)
            if on_error:
                on_error(message)
            self.show_error(message, modal=False)
        if callback:
            def delivered(result):
                try:callback(result)
                except Exception as exc:
                    from ..security import sanitize
                    message=str(sanitize(str(exc)))
                    adapter=getattr(self.core,'adapters',{}).get(agent) if agent else None
                    if adapter is not None:
                        adapter.last_error=message
                        self.core.ingest_event(agent,'error',content=message,source='UI result callback')
                        adapter.set_state('Error')
                    failed(message)
            worker.signals.result.connect(delivered)
        worker.signals.error.connect(failed)
        def finished():
            self.workers.discard(worker)
            if agent:
                self._agent_operations[agent] -= 1
                self.panels[agent].update_controls()
        worker.signals.finished.connect(finished)
        self.pool.start(worker)
        return worker

    def show_error(self, message, modal=True):
        self.footer.setText("Error · " + str(message))
        self.footer.setToolTip(str(message))
        if modal:
            box = QMessageBox(QMessageBox.Warning, "Workspace", "", QMessageBox.Ok, self)
            box.setTextFormat(Qt.PlainText)
            box.setText(str(message))
            box.exec()

    def show_detail(self, title, content):
        DetailDialog(title, content, self).exec()

    def resolve_cached_approval(self, event):
        """Apply a real terminal event even when its task is not being viewed."""
        event = {**(event.get("payload") or {}), **event}
        agent, task_id = event.get("agent"), event.get("task_id")
        request_id = event.get("request_id") or event.get("approval_id")
        if not request_id or agent not in self.panels:
            return
        for key, view in self._context_views.items():
            if task_id and key[1] != task_id:
                continue
            if not task_id and key != self._loaded_context_key:
                continue
            view.get("panels", {}).get(agent, {}).get("pending", {}).pop(request_id, None)
        for key, view in self._agent_views.items():
            if key[0] == agent and (not task_id or key[2] == task_id):
                view.get('pending', {}).pop(request_id, None)
        current_task_id = identifier(self.core.agent_task(agent) or {})
        if not task_id or task_id == current_task_id:
            self.panels[agent].resolve_pending_approval(request_id)

    def reconcile_pending_approvals(self, view, agent, task_id):
        """Restore only cached live requests still current in the local ledger."""
        pending = view.get("pending", {})
        if not pending or not task_id:
            return
        kinds = ("approval", "approval_request", "tool_approval", "approval_response", "approval_cancelled")
        store = getattr(self.core, "store", None)
        if store is not None and callable(getattr(store, "query", None)):
            rows = store.query(
                "SELECT * FROM events WHERE task_id=? AND agent=? AND type IN (?,?,?,?,?) ORDER BY timestamp,rowid",
                (task_id, agent, *kinds))
        else:
            rows = reversed(self.core.events(task_id=task_id, agent=agent, limit=100000))
        latest = {}
        for row in rows:
            event = {**(row.get("payload") or {}), **row}
            request_id = event.get("request_id") or event.get("approval_id")
            if request_id and event.get("type") in kinds:
                latest[request_id] = event
        for request_id, cached in list(pending.items()):
            event = latest.get(request_id)
            if event and (event.get("type") in ("approval_response", "approval_cancelled")
                          or (identifier(cached) and identifier(event) != identifier(cached))):
                pending.pop(request_id, None)

    def rebuild_panel(self, agent, view=None):
        panel = self.panels[agent]
        if view is None:
            view = self._agent_views.get(self.agent_context_key(agent), {})
        panel._restoring_view = True
        panel.clear_conversation()
        shown = TRANSCRIPT_EVENTS
        transcript_messages=self.core.dot_conversation_messages(limit=panel.dot_visible_limit) if agent=="dot" else self.core.messages(agent=agent)
        history = [(str((message.get("metadata") or {}).get("native_timestamp") or message.get("timestamp") or ""), 0, message) for message in transcript_messages
                   if message.get("role") in ("user", "assistant")]
        history += [(str(event.get("timestamp") or ""), 1, event) for event in reversed(self.core.events(agent=agent, limit=400))
                    if agent != "dot" and event.get("type") in shown]
        # Stable sort: equal timestamps keep messages before events, as before.
        ordered = history if agent == "dot" else sorted(history, key=lambda entry: entry[:2])
        if agent != "dot" and len(ordered) > panel.visible_limit:
            hidden = len(ordered) - panel.visible_limit
            ordered = ordered[hidden:]
            panel.set_hidden_count(hidden)
        for _, is_event, row in ordered:
            if is_event:
                pending_id = row.get("request_id") or (row.get("payload") or {}).get("request_id")
                panel.add_event(row, historical=pending_id not in view.get("pending", {}))
            else:
                panel.add_message(row)

    def reload_context(self):
        self.save_context_state()
        key = self.context_key()
        saved_view = self._context_views.get(key, {})
        self._loading = True
        try:
            project = self.core.current_project or {}
            task = self.core.current_task or {}
            self.project_combo.clear()
            self.project_combo.addItem("選擇專案…", None)
            projects = self.core.list_projects()
            for item in projects:
                self.project_combo.addItem(project_label(item, projects), identifier(item))
                self.project_combo.setItemData(self.project_combo.count()-1, plain(item), Qt.ToolTipRole)
            self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(identifier(project))))
            self.task_combo.clear()
            self.task_combo.addItem("選擇任務…", None)
            for item in self.core.list_tasks():
                if not project or item.get("project_id") == identifier(project):
                    self.task_combo.addItem(task_label(item, projects), identifier(item))
                    self.task_combo.setItemData(self.task_combo.count()-1, plain(item), Qt.ToolTipRole)
            self.task_combo.setCurrentIndex(max(0, self.task_combo.findData(identifier(task))))
            self.task_status.setCurrentIndex(max(0, self.task_status.findData(task.get("status"))))
            self.task_status.setEnabled(bool(task))
            self.update_context_title()
            for agent, panel in self.panels.items():
                agent_project = self.core.agent_project(agent) or {}
                agent_task = self.core.agent_task(agent) or {}
                agent_key = self.agent_context_key(agent)
                view = self._agent_views.get(agent_key, {})
                self.reconcile_pending_approvals(view, agent, identifier(agent_task))
                self.rebuild_panel(agent, view)
                panel.cwd_label.setText(("中繼資料：" if agent == "dot" else "工作目錄：") + (agent_project.get("name", "尚未選擇") if agent == "dot" else agent_project.get(self.core.provider(agent) + '_cwd') or agent_project.get("repo_path") or "尚未選擇"))
                panel.cwd_label.setToolTip(panel.cwd_label.text())
                panel.branch_label.setText("分支：" + (agent_task.get("branch") or agent_project.get("active_branch") or "—"))
                self.refresh_agent(agent)
                panel.restore_view_state(view)
                self._loaded_agent_keys[agent] = agent_key
            self._loaded_context_key = key
            self.select_role(self.agents.index(self._preferred_agent))
            self.update_context_title()
            self.details_tabs.setCurrentIndex(saved_view.get("details_tab", 0))
            self.refresh_work_details()
            for name, selected in saved_view.get("detail_selections", {}).items():
                tree = self.detail_trees.get(name)
                if tree is not None and selected:
                    for index in range(tree.topLevelItemCount()):
                        item = tree.topLevelItem(index)
                        if identifier(item.data(0, Qt.UserRole) or {}) == identifier(selected):
                            tree.setCurrentItem(item)
                            break
            self.update_workspace_layout()
            if self.mode.currentData() == "Timeline":
                self.refresh_timeline()
            if self.mode.currentData() == "History":
                self.refresh_history()
        except Exception as exc:
            self.show_error(str(exc), False)
        finally:
            self._loading = False

    def refresh_agent(self, agent):
        panel = self.panels[agent]
        try:
            cap = self.core.capabilities(agent)
            panel.update_capabilities(cap)
            diag = self.core.diagnostics(agent)
            panel.set_state(diag.get("state", "Disconnected"))
            panel.refresh_projects()
            project = self.core.agent_project(agent) or {}
            task = self.core.agent_task(agent) or {}
            sessions = self.core.sessions(agent)
            if agent != "dot" and agent in self.core._agent_selections:
                directory = project.get(self.core.provider(agent) + '_cwd') or project.get('repo_path')
                sessions = [row for row in sessions if row.get('project_id') == project.get('id')
                            or (directory and row.get('cwd') and Path(row['cwd']).resolve() == Path(directory).resolve())]
            panel.refresh_sessions(sessions, task.get(f"{agent}_session"))
            if diag.get("last_error"):
                note = diag["last_error"]
                if panel.provider == 'codex':
                    note += ' · ' + panel.codex_permission_note()
                panel.notice.setText(note)
                panel.notice.setToolTip(note)
        except Exception as exc:
            self.show_error(str(exc), False)

    def poll_events(self):
        if self.mode.currentData() in ('Workspace', 'Monitor') and time.monotonic() - self._monitor_clock >= 1:
            self.refresh_monitor()
        self._legacy_clock += 1
        self._git_clock += 1
        # run.sh (hermes-delegation skill) hands Hermes steps over as request files; answer them about once a second.
        self._requests_clock = getattr(self, "_requests_clock", 0) + 1
        if self._requests_clock >= 10 and not getattr(self, "_requests_busy", False) and not self._close_pending:
            self._requests_clock = 0
            self._requests_busy = True
            self.run(self.core.poll_requests, lambda _: setattr(self, "_requests_busy", False),
                     on_error=lambda _: setattr(self, "_requests_busy", False))
        if self.mode.currentData() == "Monitor" and self._legacy_clock >= 10 and not self._legacy_busy and not self._close_pending:
            self._legacy_clock = 0
            self._legacy_busy = True
            def loaded_legacy(entries):
                self._legacy_busy = False
                for entry in entries:
                    panel = self.panels.get(entry.get("agent"))
                    if panel:
                        message = dict(entry, id="legacy-" + entry["agent"], role="system")
                        panel.add_message(message)
                        panel.cards[message["id"]].heading.setText("LEGACY MONITOR · READ ONLY")
            legacy_root = self.core.get_setting("legacy.root", LEGACY_MONITOR_ROOT)
            self.run(lambda: self.core.poll_legacy(legacy_root), loaded_legacy,
                     on_error=lambda _: setattr(self, "_legacy_busy", False))
        if self._git_clock >= 100 and not self._git_busy and self.view_project() and not self._close_pending:
            self._git_clock = 0
            self._git_busy = True
            git_project_id = identifier(self.view_project())
            def loaded_git(snapshot):
                self._git_busy = False
                for agent in self.agents:
                    if self.core.provider(agent) == "dot": continue
                    if (self.core.agent_project(agent) or {}).get('id') == git_project_id:
                        self.panels[agent].branch_label.setText(self.branch_text(snapshot))
            self.run(lambda: self.core.git_snapshot(git_project_id), loaded_git, on_error=lambda _: setattr(self, "_git_busy", False))
        try:
            events = self.core.drain_events()
        except Exception as exc:
            self.footer.setText("Event reader error · " + str(exc))
            return
        if not events:
            return
        latest_delta = {event.get("message_id"): index for index, event in enumerate(events) if event.get("type") == "message_delta"}
        current_task_id = identifier(self.core.current_task or {})
        dot_changed=False
        for index, event in enumerate(events):
            agent, kind = event.get("agent"), event.get("type")
            panel = self.panels.get(agent)
            self.last_event = f"{event.get('timestamp', '')} · {agent or 'workspace'} · {kind}"
            if panel and kind in ("state", "connection_state"):
                panel.set_state(event.get("state") or event.get("status", "Disconnected"))
            if panel and kind in ("capabilities", "connected", "session", "session_started", "session_changed"):
                self.refresh_agent(agent)
            if panel and kind in ("approval_response", "approval_cancelled"):
                self.resolve_cached_approval(event)
            displayed_task_id = identifier(self.core.agent_task(agent) or {}) if panel else current_task_id
            if panel and kind == 'session_missing' and event.get('task_id') == displayed_task_id:
                panel.send_error = event.get('content', '')
                panel.update_controls()
            if agent=='dot' and kind in ('message_snapshot','prompt_sent','history_page'):
                target=getattr(self.core.adapters.get('dot'),'target','')
                if target and (event.get('session_id')==target or kind=='history_page'):
                    dot_changed=True
                continue
            if event.get("task_id") and event.get("task_id") != displayed_task_id:
                continue
            if kind == "message_delta" and latest_delta.get(event.get("message_id")) != index:
                continue
            if panel and kind in ("message_start", "message_delta", "message_end", "message_snapshot", "message", "assistant", "user", "prompt_sent"):
                mid = event.get("message_id") or event.get("id")
                content = event.get("full_content", event.get("content", ""))
                role = event.get("role", "user" if kind in ("user", "prompt_sent") else "assistant")
                if kind == "message_delta" and "full_content" not in event:
                    # Core's cumulative sanitized stream is authoritative. Never
                    # concatenate raw backend fragments across secret boundaries.
                    continue
                panel.add_message(dict(event, id=mid, role=role, content=content))
            elif panel and kind in TRANSCRIPT_EVENTS:
                panel.add_event(event)
            if self.mode.currentData() == "Timeline":
                self.add_timeline_event(event)
        if dot_changed:
            panel=self.panels['dot'];view=panel.capture_view_state();panel.clear_conversation()
            for message in self.core.dot_conversation_messages(limit=panel.dot_visible_limit): panel.add_message(message)
            panel.restore_view_state(view);self.refresh_agent('dot')
        if self.details_toggle.isChecked() and any(event.get("type") != "message_delta" for event in events):
            if self._details_timer.isActive():
                self._details_dirty = True
            else:
                self.refresh_work_details()
                self._details_timer.start()
        error_panel=next((panel for panel in self.panels.values() if panel.connection_state=='Error'),None)
        self.footer.setText('Error · '+error_panel.agent+' · '+error_panel.notice.text() if error_panel else self.last_event)

    def show_desktop_sessions(self, agent="claude"):
        self.sidebar.show()
        self.sidebar_toggle.setChecked(True)
        self.focus_role(agent)
        self.navigator.ensure_loaded()
        self.navigator.search.setFocus()
        QTimer.singleShot(0, self, self.update_workspace_layout)

    def _agent_ready(self, agent):
        if self.core.adapters[agent].state != "Connected":
            self.core.connect(agent)

    def _opening_done(self, agent):
        self._opening_agents.discard(agent)
        self._opening = bool(self._opening_agents)
        for panel in self.panels.values(): panel.update_controls()

    def _opening_begin(self, agent):
        # Serialize only the selected Agent; independent Agents can open concurrently.
        if agent in self._opening_agents or not self.confirm_agent_context_change(agent):
            return False
        self._opening_agents.add(agent)
        self._opening = True
        self.panels[agent].update_controls()
        return True

    def sync_local_conversations(self):
        """Show what Claude Desktop or Codex appended to an open conversation, without reopening it."""
        from ..desktop_sessions import history_stamp
        if self._close_pending or self._closed:
            return
        for agent in self.agents:
            if agent in self._opening_agents: continue
            if self.core.provider(agent) not in ("claude", "codex"): continue
            panel = self.panels[agent]
            task = self.core.agent_task(agent) or {}
            session_id = str(task.get(agent + "_session") or "").lower()
            if not session_id or agent in self._syncing:
                continue
            key = (agent, session_id)
            if panel.connection_state in ("Busy", "Connecting"):
                # This role is producing the new content itself; it is already on screen through the live stream.
                self._sync_floor[key] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".999Z"
                continue
            stamp = history_stamp(self.core.provider(agent), session_id)
            if stamp is None or stamp == self._sync_stamp.get(key):
                continue
            first = key not in self._sync_stamp
            self._sync_stamp[key] = stamp
            if first and key not in self._sync_floor:
                # Whatever is already stored was imported when the conversation was opened.
                stored = [str(row.get("timestamp") or "") for row in self.core.messages(task["id"], agent)]
                stored += [str(row.get("timestamp") or "") for row in self.core.events(task["id"], agent, limit=1)]
                self._sync_floor[key] = max(stored, default="")
                continue
            self._syncing.add(agent)
            def done(result, agent=agent, key=key, panel=panel):
                self._syncing.discard(agent)
                if self._closed:
                    return
                self._sync_floor[key] = max(self._sync_floor.get(key, ""), result["latest"])
                current = self.core.agent_task(agent) or {}
                if result["task_id"] != current.get("id") or not result["items"]:
                    return
                for kind, row in result["items"]:
                    if kind == "message":
                        panel.add_message(row)
                    else:
                        panel.add_event(row, historical=True)
                if hasattr(self, "navigator") and self.navigator.sessions.get(agent) is not None:
                    self.footer.setText(f"{self.role_names[agent]} 對話已同步 · 新增 {len(result['items'])} 筆")
            floor = self._sync_floor.get(key, "")
            self.run(lambda agent=agent, floor=floor: self.core.sync_local_history(agent, floor), done,
                     on_error=lambda _, agent=agent: self._syncing.discard(agent))

    def open_desktop_session(self, record, resume=True):
        agent = record.get("agent", "claude")
        if not self._opening_begin(agent):
            return
        def opened(result):
            self.reload_context()
            self.focus_role(agent)
            if not resume:
                self._opening_done(agent)
            self.footer.setText(f"已載入「{record.get('title', '')}」· {result['imported']} 則訊息、{result['tools']} 筆工具紀錄")
            # A conversation opens at its latest message, like the desktop apps.
            QTimer.singleShot(150, self.panels[agent], self.panels[agent].jump_to_latest)
            if resume:
                self.panels[agent].set_state("Connecting")
                def continue_session():
                    self._agent_ready(agent)
                    return self.core.resume_session(agent, result["session_id"])
                self.run(continue_session, lambda _: (self._opening_done(agent), self.reload_context(), self.refresh_agent(agent)),
                         agent, on_error=lambda _: self._opening_done(agent))
        self.run(lambda: self.core.open_desktop_session(record, independent=True), opened, agent, on_error=lambda _: self._opening_done(agent))

    def new_desktop_conversation(self, directory, agent="claude"):
        if not self._opening_begin(agent):
            return
        title = "新對話 " + datetime.now().strftime("%m-%d %H:%M")
        def opened(_):
            self.reload_context()
            self.focus_role(agent)
            self.panels[agent].set_state("Connecting")
            def start():
                self._agent_ready(agent)
                return self.core.create_session(agent)
            self.run(start, lambda _: (self._opening_done(agent), self.reload_context(), self.refresh_agent(agent)),
                     agent, on_error=lambda _: self._opening_done(agent))
        self.run(lambda: self.core.open_desktop_project(directory, title, agent=agent), opened, agent, on_error=lambda _: self._opening_done(agent))

    def focus_role(self, agent):
        self.select_role(self.agents.index(agent))

    def start_auto_collab(self):
        if self.orchestrator and self.orchestrator.active:
            self.show_error("已有一個自動協作正在執行。")
            return
        if self.mode.currentData() == "Monitor":
            self.show_error("監看模式下不能啟動自動協作。")
            return
        from ..adapters.dot import DISCLOSURE
        dialog = QDialog(self)
        dialog.setObjectName("auto_collab_dialog")
        dialog.setWindowTitle("自動協作")
        dialog.resize(680, 560)
        form = QVBoxLayout(dialog)
        lead = QComboBox()
        lead.setObjectName('auto_lead')
        for agent in self.agents:
            if self.core.provider(agent) != 'dot':
                lead.addItem(self.role_names[agent], agent)
        lead.setCurrentIndex(max(0, lead.findData(self._preferred_agent)))
        form.addWidget(label('本次分工（每次啟動可重新選擇）', True))
        form.addWidget(lead)
        implementer = QComboBox()
        implementer.setObjectName('auto_implementer')
        for agent in self.agents:
            if self.core.provider(agent) != 'dot':
                implementer.addItem(self.role_names[agent], agent)
        implementer.setCurrentIndex(implementer.findData('codex' if lead.currentData() == 'claude' else 'claude'))
        form.addWidget(label('實作 Agent（可以與主導者使用相同後端）', True))
        form.addWidget(implementer)
        preview = label('', True)
        preview.setObjectName('auto_flow_preview')
        form.addWidget(preview)
        binding_preview = label('', True)
        binding_preview.setObjectName('auto_bindings_preview')
        form.addWidget(binding_preview)
        workflow = QComboBox()
        workflow.setObjectName('auto_workflow')
        workflow.addItem('直接派工與驗收', 'direct')
        workflow.addItem('加入 G8毛：審查計畫、實作與轉交', 'relay')
        form.addWidget(workflow)
        task = QPlainTextEdit()
        task.setObjectName("auto_task")
        task.setPlaceholderText("要完成的任務…")
        form.addWidget(task, 1)
        row = QHBoxLayout()
        row.addWidget(label("回合上限"))
        rounds = QSpinBox()
        rounds.setObjectName("auto_rounds")
        rounds.setRange(1, 10)
        rounds.setValue(3)
        row.addWidget(rounds)
        row.addSpacing(16)
        row.addWidget(label("Hermes"))
        local_role = QComboBox()
        local_role.setObjectName("auto_local_role")
        local_role.addItem("不加入", None)
        local_role.addItem("第二意見（實作後多審一次，不會擋流程）", "reviewer")
        local_role.addItem("擔任實作者（取代本次實作角色）", "implementer")
        row.addWidget(local_role, 1)
        form.addLayout(row)
        limits = QHBoxLayout()
        limits.addWidget(label('有效時間上限（分鐘）'))
        minutes = QSpinBox()
        minutes.setObjectName('auto_minutes')
        minutes.setRange(1, 1440)
        minutes.setValue(60)
        limits.addWidget(minutes)
        limits.addWidget(label('步數上限'))
        steps = QSpinBox()
        steps.setObjectName('auto_steps')
        steps.setRange(1, 100)
        steps.setValue(24)
        limits.addWidget(steps)
        form.addLayout(limits)
        form.addWidget(label("支援 Workspace 核准的角色會暫停等待你回覆；Hermes 使用自身工具權限設定，不透過 Workspace 核准。任何錯誤、逾時或回覆格式不符都會暫停。", True))
        disclosure = label("G8毛 授權（僅限這一次執行）\n" + DISCLOSURE +
                             "\nDuring this run the workspace sends to and reads from the selected Dot automatically, "
                             "reading about every 10 seconds, up to 400 requests. This is automated use of an unofficial "
                             "interface with your ChatGPT login and may lead to rate limiting or account restrictions.", True)
        form.addWidget(disclosure)
        consent = QCheckBox("我了解上述風險，授權這一次執行自動對 G8毛 傳送與讀取")
        consent.setObjectName("auto_consent")
        form.addWidget(consent)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        start = buttons.button(QDialogButtonBox.Ok)
        start.setText("開始")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        def ready():
            relay = workflow.currentData() == 'relay'
            owner = self.role_names[lead.currentData()]
            worker_id = 'local' if local_role.currentData() == 'implementer' else implementer.currentData()
            worker = self.role_names[worker_id]
            implementer.setEnabled(local_role.currentData() != 'implementer')
            stages = [owner + ' 派工']
            if relay:
                stages.append('G8毛 複核')
            stages.append(worker + ' 實作')
            if local_role.currentData() == 'reviewer':
                stages.append('Hermes 第二意見')
            if relay:
                stages.append('G8毛 複核')
            stages.append(owner + ' 驗收')
            preview.setText(' → '.join(stages) + '。不通過會再交回實作者，直到通過或達到上限。')
            participants = list(dict.fromkeys([lead.currentData(), worker_id] + (['local'] if local_role.currentData() == 'reviewer' else []) + (['dot'] if relay else [])))
            bindings = []
            for agent in participants:
                project = self.core.agent_project(agent) or {}
                context = self.core.agent_task(agent) or {}
                sid = context.get(agent + '_session') or ''
                saved = self.core.store.get('sessions', {'agent': agent, 'id': sid}) if sid else None
                bindings.append(self.role_names[agent] + ' · ' + (project.get('name') or '未選 Project') + ' / ' + ((saved or {}).get('title') or context.get('title') or '尚未開啟對話'))
            binding_preview.setText('沿用各 Agent 目前的綁定：\n' + '\n'.join(bindings))
            disclosure.setVisible(relay)
            consent.setVisible(relay)
            distinct = worker_id != lead.currentData() and not (local_role.currentData() == 'reviewer' and 'local' in (lead.currentData(), worker_id))
            start.setEnabled(distinct and (not relay or consent.isChecked()) and bool(task.toPlainText().strip()))
        workflow.currentIndexChanged.connect(ready)
        lead.currentIndexChanged.connect(ready)
        implementer.currentIndexChanged.connect(ready)
        local_role.currentIndexChanged.connect(ready)
        consent.toggled.connect(ready)
        task.textChanged.connect(ready)
        ready()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.run_auto_collab(task.toPlainText(), rounds.value(), consented=consent.isChecked(),
                                 local_role=local_role.currentData(), workflow=workflow.currentData(),
                                 max_steps=steps.value(), max_active_seconds=minutes.value() * 60,
                                 lead=lead.currentData(), implementer=implementer.currentData())

    def run_auto_collab(self, task, rounds, consented=False, local_role=None, workflow='direct',
                        max_steps=24, max_active_seconds=3600, lead='claude', implementer=None):
        """Start one bounded run. `consented` is the user's run-scoped G8毛 authorisation from the dialog."""
        if self.mode.currentData() == 'Monitor':
            self.show_error('請先返回對話，再啟動自動協作。')
            return
        if workflow == 'relay' and not consented:
            return
        if self.orchestrator and self.orchestrator.active:
            self.show_error('已有自動協作正在進行');return
        if workflow == 'relay':
            self.panels['dot'].stop_dot_follow()
        dot = self.core.adapters["dot"]
        run=None
        def dispatch(operation, done, failed):
            self.run(operation, done, on_error=failed)
        try:
            run = Orchestrator(self.core, task, dispatch, max_rounds=rounds, local_role=local_role,
                               workflow=workflow, max_steps=max_steps, max_active_seconds=max_active_seconds, lead=lead, implementer=implementer,
                               has_pending_approval=lambda: any(self.panels[agent].pending_approval_events for agent in run.agents))
            if 'dot' in run.agents and getattr(dot, "state", "") == "Connected" and hasattr(dot, "grant_run"):
                dot.grant_run(400,owner=run.run_id)
            self.orchestrator = run
            run.start()
        except Exception as exc:
            self.orchestrator = None
            if run is not None and 'dot' in run.agents and hasattr(dot, "revoke_run"):
                dot.revoke_run(owner=run.run_id)
            self.show_error(str(exc))
            return
        self.set_auto_collab_lock(True)
        self.run_bar.show()
        self.run_timer.start(500)
        self.tick_auto_collab()
        self.refresh_monitor()

    def set_auto_collab_lock(self, locked):
        # A run must keep talking to the same task; switching context mid-run would misroute messages.
        self.auto_button.setEnabled(not locked)
        for panel in self.panels.values(): panel.update_controls()
        self.run_stop.setVisible(locked)
        self.run_close.setVisible(not locked)

    def tick_auto_collab(self):
        run = self.orchestrator
        if not run:
            return
        if run.active:
            run.tick()
        self.run_status.setText(run.status())
        self.run_status.setToolTip(run.status())
        if not run.active:
            self.run_timer.stop()
            dot = self.core.adapters.get("dot")
            if 'dot' in run.agents and hasattr(dot, "revoke_run"):
                dot.revoke_run(owner=run.run_id)
            self.set_auto_collab_lock(False)
            self.reload_context()
        if self.mode.currentData() in ('Workspace', 'Monitor'):
            self.refresh_monitor()

    def stop_auto_collab(self):
        if self.orchestrator and self.orchestrator.active:
            self.orchestrator.stop()
        self.tick_auto_collab()

    def require_project(self, reason, *, agent=None):
        box = QMessageBox(QMessageBox.Question, "需要專案", "", QMessageBox.Yes | QMessageBox.No, self)
        box.setTextFormat(Qt.PlainText)
        box.setText(reason + "\n專案就是這個角色工作時所在的資料夾。\n\n要現在建立專案嗎？建立後請再按一次「連線」。")
        box.button(QMessageBox.Yes).setText("建立專案…")
        box.button(QMessageBox.No).setText("稍後")
        if box.exec() == QMessageBox.Yes:
            self.new_project(agent=agent)

    def require_task(self):
        if not self.core.current_project:
            self.require_project("傳送訊息前需要先有專案與任務。")
            return
        box = QMessageBox(QMessageBox.Question, "需要任務", "", QMessageBox.Yes | QMessageBox.No, self)
        box.setTextFormat(Qt.PlainText)
        box.setText("傳送訊息前需要先建立或選擇一個任務；草稿會保留。\n\n要現在建立任務嗎？")
        box.button(QMessageBox.Yes).setText("建立任務…")
        box.button(QMessageBox.No).setText("稍後")
        if box.exec() == QMessageBox.Yes:
            self.new_task()

    def new_project(self, *, agent=None, global_scope=False):
        agent = None if global_scope else agent or self._preferred_agent
        dialog = QDialog(self)
        dialog.setWindowTitle("建立專案")
        dialog.resize(640, 320)
        layout = QFormLayout(dialog)
        name, repo, branch, notes = QLineEdit(), QLineEdit(), QLineEdit(), QPlainTextEdit()
        name.setObjectName("project_name")
        repo.setObjectName("project_repo")
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(repo)
        row_layout.addWidget(button("瀏覽…", lambda: repo.setText(QFileDialog.getExistingDirectory(dialog, "選擇專案資料夾") or repo.text())))
        layout.addRow("名稱", name)
        layout.addRow("專案資料夾", row)
        layout.addRow("預設分支（選填）", branch)
        layout.addRow("備註", notes)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addRow(actions)
        if dialog.exec() == QDialog.Accepted:
            if not name.text().strip() or not repo.text().strip():
                self.show_error("請填寫專案名稱與資料夾。")
                return
            if not (self.confirm_agent_context_change(agent) if agent else self.confirm_context_change()):
                return
            project_name, project_repo = name.text().strip(), repo.text().strip()
            project_branch, project_notes = branch.text().strip(), notes.toPlainText()
            def create():
                project = self.core.create_project(project_name, project_repo, default_branch=project_branch, notes=project_notes)
                if agent: self.core.select_agent_project(agent, identifier(project))
                else: self.core.select_project(identifier(project))
            self.run(create, lambda _: self.reload_context(), agent)

    def new_task(self):
        if not self.core.current_project:
            self.new_project(global_scope=True)
            return
        title, ok = QInputDialog.getText(self, "建立任務", "任務名稱")
        if ok and title.strip():
            if not self.confirm_context_change():
                return
            def create():
                task = self.core.create_task(title.strip())
                self.core.select_task(identifier(task))
            self.run(create, lambda _: self.reload_context())

    def confirm_context_change(self):
        # Navigation saves drafts locally in memory. It never sends or discards them.
        self.save_context_state()
        return True

    def confirm_agent_context_change(self, agent):
        if self.orchestrator and self.orchestrator.active and agent in self.orchestrator.agents:
            self.show_error("請先停止自動協作，再切換角色的專案或任務。")
            return False
        panel = self.panels[agent]
        if panel.connection_state in ('Busy', 'Connecting') or self._agent_operations.get(agent) or agent in self._opening_agents:
            self.show_error("請等待或停止此角色的作業，再切換它的專案或任務。")
            return False
        self.save_context_state()
        return True

    def project_changed(self):
        if self._loading:
            return
        pid = self.project_combo.currentData()
        if pid and pid != identifier(self.core.current_project or {}):
            if self.confirm_context_change():
                self.run(lambda: self.core.select_project(pid, sync=True), lambda _: self.reload_context())
            else:
                self.reload_context()

    def task_changed(self):
        if self._loading:
            return
        tid = self.task_combo.currentData()
        if tid and tid != identifier(self.core.current_task or {}):
            if self.confirm_context_change():
                self.run(lambda: self.core.select_task(tid), lambda _: self.reload_context())
            else:
                self.reload_context()

    def sync_project(self):
        project = self.core.current_project
        if not project:
            self.show_error("Select a project first.")
            return
        if any(panel.connection_state == "Busy" for panel in self.panels.values()):
            self.show_error("Wait for or stop active turns before syncing project directories.")
            return
        self.run(lambda: self.core.select_project(identifier(project), sync=True), lambda _: self.reload_context())

    def status_changed(self, value):
        task = self.core.current_task
        if not self._loading and task:
            self.core.update_task(identifier(task), status=value)

    def notes(self):
        task = self.view_task()
        if not task:
            self.show_error("Select a task first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Task notes — local only")
        dialog.resize(650, 400)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Notes stay in this task. They are never automatically sent to an agent.", True))
        editor = QPlainTextEdit(task.get("notes", ""))
        layout.addWidget(editor)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() == QDialog.Accepted:
            self.core.update_task(identifier(task), notes=editor.toPlainText())

    def focus_agent(self, agent):
        if agent is None or (agent == self.focused_agent and self.layout_mode.currentData() == "Focus"):
            self.layout_mode.setCurrentIndex(self.layout_mode.findData("Auto"))
        else:
            self.focus_role(agent)
            self.layout_mode.setCurrentIndex(self.layout_mode.findData("Focus"))
        self.update_workspace_layout()

    def select_workspace_view(self, index):
        if index not in (0, 1):
            return
        if index == 1 and self.mode.currentData() == 'Monitor' and self.stack.currentIndex() == 0:
            self.toggle_monitor()
        else:
            self.mode.setCurrentIndex(self.mode.findData('Monitor' if index else 'Workspace'))

    def change_mode(self, mode):
        for panel in self.panels.values():
            panel.set_monitor(mode == "Monitor")
            for mid, card in panel.cards.items():
                if mid.startswith("legacy-"):
                    card.setVisible(mode == "Monitor")
        self.stack.setCurrentIndex(1 if mode == "Timeline" else 2 if mode == "History" else 3 if mode == 'Monitor' else 0)
        self.workspace_view_group.setExclusive(False)
        for control, value in zip(self.workspace_view_buttons, ('Workspace', 'Monitor')):
            control.setChecked(mode == value)
        self.workspace_view_group.setExclusive(True)
        self.navigator.selection_changed()
        if mode == "Timeline":
            self.refresh_timeline()
        elif mode == "History":
            self.refresh_history()
        elif mode == "Monitor":
            self._legacy_clock = 10
            self.refresh_monitor()
            self.footer.setText("Monitor · Read-only workspace and legacy logs · Existing sessions are untouched")
        else:
            self.footer.setText('MONITOR WORKSPACE · 各 Agent 獨立 session · Ctrl+Enter 傳送 · Ctrl+B 側欄')
        self.update_workspace_layout()

    def toggle_monitor(self):
        if self.mode.currentData() == 'Monitor' and self.stack.currentIndex() == 0:
            self.stack.setCurrentWidget(self.monitor_dashboard)
            self.monitor_button.setText('返回工作台')
            self.refresh_monitor()
            return
        self.mode.setCurrentIndex(self.mode.findData('Workspace' if self.mode.currentData() == 'Monitor' else 'Monitor'))

    def show_monitor_transcripts(self):
        self.stack.setCurrentIndex(0)
        self.monitor_button.setText('返回總覽')

    def open_monitor_role(self, agent):
        self.mode.setCurrentIndex(self.mode.findData('Workspace'))
        self.records_dialog.hide()
        self.focus_role(agent)
        self.layout_mode.setCurrentIndex(self.layout_mode.findData('Focus'))
        self.update_workspace_layout()
        self.refresh_monitor()

    def refresh_monitor(self):
        self._monitor_clock = time.monotonic()
        self.agent_rail.setProperty('theme', self.theme_name)
        snapshot = collect_snapshot(self.core, self.panels, self.orchestrator)
        self.monitor_dashboard.refresh(snapshot)
        self.agent_rail.refresh(snapshot, self._preferred_agent)

    def forward(self, message, target):
        try:
            if self.handoff_mode.currentData() == "manual":
                if self.panels[target].connection_state != "Connected":
                    self.show_error(f"{self.role_names[target]} 尚未連線。未傳送交接。")
                    return
                preview = self.core.prepare_handoff(identifier(message), target)
                if target == 'dot' and not self.panels['dot'].dot_consent('send'): return
                self.run(lambda: self.core.send_handoff(preview), agent=target)
                return
            dialog = HandoffDialog(self, message, target)
            if dialog.exec() == QDialog.Accepted:
                if target == 'dot' and not self.panels['dot'].dot_consent('send'): return
                self.run(lambda: self.core.send_handoff(dialog.preview), agent=target)
        except Exception as exc:
            self.show_error(str(exc))

    def populate_flow_menu(self, menu):
        menu.clear()
        for number, source, target in ((1, "claude", "dot"), (2, "dot", "codex")):
            source_task=self.core.agent_task(source) or {}
            messages = [message for message in (self.core.messages(task_id=source_task["id"],agent=source) if source_task else [])
                        if message.get("role") == "assistant" and message.get("status", "complete") == "complete"]
            state = self.panels[target].connection_state
            blocked = target == "dot" and (not self.panels[target].capabilities.get("supports_sessions") or (self.core.agent_task("dot") or {}).get("dot_session") != getattr(self.core.adapters.get("dot"),"target",None))
            reason = " · 受阻" if blocked else " · 請先連線目標角色" if state != "Connected" else " · 尚無來源回覆" if not messages else ""
            action = menu.addAction(f"第 {number} 步：最新 {self.role_names[source]} 回覆 → {self.role_names[target]}{reason}")
            action.setEnabled(bool(messages) and state == "Connected" and not blocked)
            if messages:
                action.triggered.connect(lambda checked=False, message=messages[-1], target=target: self.forward(message, target))
        menu.addSeparator()
        explanation = menu.addAction("每一步都需你手動操作 · 自動協作關閉")
        explanation.setEnabled(False)

    def stop_task(self):
        if QMessageBox.question(self, "停止全部 Agent", "要求停止所有正在執行的 Agent，以及目前的自動協作？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.stop_auto_collab()
            self.run(lambda: self.core.stop_task(confirmed=True))

    def approval_mode(self, agent):
        mode = (self.core.get_setting("agent." + agent, {}) or {}).get("approval_mode", "ask")
        return mode if mode in approvals.MODES else "ask"

    def set_approval_mode(self, agent, mode):
        if mode == "all" and self.approval_mode(agent) != "all":
            box = QMessageBox(QMessageBox.Warning, "自動核准全部", "", QMessageBox.Yes | QMessageBox.No, self)
            box.setTextFormat(Qt.PlainText)
            box.setText(self.role_names[agent] + " 之後執行指令、修改專案內的檔案都不會再問你。\n\n"
                        "仍然會問的：刪除資料夾、git push、強制覆寫、修改系統設定、下載後直接執行、修改專案資料夾以外的檔案。\n\n"
                        "這份清單擋得住常見的危險操作，但不保證擋得住全部。要開啟嗎？")
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return
        self.core.set_setting("agent." + agent, dict(self.core.get_setting("agent." + agent, {}) or {}, approval_mode=mode))
        self.footer.setText(self.role_names[agent] + " 核准方式：" + approvals.MODE_LABELS[mode])
        self.panels[agent].update_controls()

    def auto_approve(self, agent, event, request_id):
        """Answer a request without asking when the user's chosen mode or an "always allow" rule covers it."""
        if self.orchestrator and self.orchestrator.active:
            return False  # A collaboration run never inherits automatic tool approval.
        if self.mode.currentData() == "Monitor" or not self.core.capabilities(agent).get("supports_approval"):
            return False
        cwd = getattr(self.core.adapters.get(agent), "cwd", "") or (self.core.agent_project(agent) or {}).get("repo_path", "")
        if not approvals.decide(self.approval_mode(agent), event.get("details"), cwd, self.panels[agent].approval_rules):
            return False
        self.run(lambda: self.core.approve(agent, request_id, True), agent=agent)
        return True

    def allow_always(self, event, key):
        event = {**(event.get("payload") or {}), **event}
        self.panels[event["agent"]].approval_rules.add(key)
        self.approve(event, True, confirm=False)

    def approve(self, event, approved, confirm=True):
        event = {**(event.get("payload") or {}), **event}
        request_id = event.get("request_id") or event.get("approval_id")
        if not request_id:
            self.show_error("核准要求缺少後端識別碼。未傳送回覆。")
            return
        if approved and confirm:
            box = QMessageBox(QMessageBox.Question, "Backend tool approval", "", QMessageBox.Yes | QMessageBox.No, self)
            box.setTextFormat(Qt.PlainText)
            box.setText("Approve this specific backend request?")
            box.setDetailedText(plain(event))
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return
        self.run(lambda: self.core.approve(event["agent"], request_id, approved), agent=event["agent"])

    def open_raw(self, message):
        try:
            self.show_detail("Raw event — secret and hidden-reasoning filtering applied", self.core.read_raw(message.get("raw_ref")))
        except Exception as exc:
            self.show_detail("Stored message metadata", dict(message, raw_error=str(exc)))

    def show_agent_events(self, agent):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{agent.title()} raw events — safety filtering applied")
        dialog.resize(1050, 680)
        layout = QVBoxLayout(dialog)
        split = QSplitter()
        index = QTreeWidget()
        index.setHeaderLabels(["Time", "Event"])
        raw = QPlainTextEdit()
        raw.setReadOnly(True)
        raw.setFont(QFont("Consolas", 10))
        split.addWidget(index)
        split.addWidget(raw)
        split.setSizes([360, 690])
        layout.addWidget(split)
        for event in self.core.events(agent=agent, limit=1000):
            item = QTreeWidgetItem([str(event.get("timestamp", "")), str(event.get("type", ""))])
            item.setData(0, Qt.UserRole, event)
            index.addTopLevelItem(item)
        def selected(item):
            if not item:
                return
            event = item.data(0, Qt.UserRole)
            try:
                raw.setPlainText(plain(self.core.read_raw(event.get("raw_ref"))))
            except Exception as exc:
                raw.setPlainText(plain(dict(event, raw_error=str(exc))))
        index.currentItemChanged.connect(lambda current, previous: selected(current))
        if index.topLevelItemCount():
            index.setCurrentItem(index.topLevelItem(0))
        layout.addWidget(button("Close", dialog.accept))
        dialog.exec()

    def open_logs(self, agent):
        try:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.core.logs_path(agent)))):
                raise RuntimeError("The operating system could not open the log directory.")
        except Exception as exc:
            self.show_error(str(exc))

    def open_project(self, agent=None):
        project = (self.core.agent_project(agent) if agent in self.agents else self.view_project()) or {}
        path = project.get("repo_path") or project.get("repo")
        if path:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                self.show_error("The operating system could not open the project directory.")
        else:
            self.show_error("No project directory selected.")

    def refresh_timeline(self):
        self.timeline.clear()
        task = self.view_task() or {}
        for event in reversed(self.core.events(task_id=task.get('id'), limit=2000) if task else []):
            self.add_timeline_event(event)
        for col, width in enumerate((175, 75, 140, 90)):
            self.timeline.setColumnWidth(col, width)

    def add_timeline_event(self, event):
        item = QTreeWidgetItem([str(event.get(key, "")) for key in ("timestamp", "agent", "type", "status", "summary")])
        item.setData(0, Qt.UserRole, event)
        self.timeline.addTopLevelItem(item)
        while self.timeline.topLevelItemCount() > 2000:
            self.timeline.takeTopLevelItem(0)

    def build_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search conversations, commands, files, tasks, projects, errors…")
        self.search.setObjectName("history_search")
        self.search.returnPressed.connect(self.refresh_history)
        filters.addWidget(self.search, 2)
        self.history_agent = QComboBox()
        self.history_agent.addItem("All agents", None)
        for agent in self.agents:
            self.history_agent.addItem(self.role_names[agent], agent)
        self.history_agent.currentIndexChanged.connect(self.refresh_history)
        filters.addWidget(self.history_agent)
        self.history_status = QComboBox()
        self.history_status.addItems(["All statuses", *STATUSES])
        self.history_status.currentIndexChanged.connect(self.refresh_history)
        filters.addWidget(self.history_status)
        self.history_project = QCheckBox("目前專案")
        self.history_project.toggled.connect(self.refresh_history)
        filters.addWidget(self.history_project)
        filters.addWidget(button("Search", self.refresh_history))
        layout.addLayout(filters)
        extra = QHBoxLayout()
        self.history_branch = QLineEdit()
        self.history_branch.setPlaceholderText("Exact branch…")
        self.history_date = QLineEdit()
        self.history_date.setPlaceholderText("Date YYYY-MM-DD")
        self.history_errors = QCheckBox("Errors only")
        extra.addWidget(self.history_branch)
        extra.addWidget(self.history_date)
        extra.addWidget(self.history_errors)
        layout.addLayout(extra)
        self.history_table = QTreeWidget()
        self.history_table.setHeaderLabels(["Task / result", "Project", "Status / kind", "Agent", "Date", "Branch / content"])
        self.history_table.setAlternatingRowColors(True)
        self.history_table.itemDoubleClicked.connect(self.open_history_item)
        layout.addWidget(self.history_table, 1)
        layout.addWidget(label("雙擊任務查看本機紀錄；不會切換或恢復任何 Agent。雙擊搜尋結果可查看內容。", True))
        return page

    def show_history(self, agent=None):
        if agent:
            self.focus_role(agent)
            self.history_agent.setCurrentIndex(self.history_agent.findData(agent))
        self.mode.setCurrentIndex(self.mode.findData("History"))

    def refresh_history(self):
        if not hasattr(self, "history_table"):
            return
        self.history_table.clear()
        query = self.search.text().strip()
        filters = {}
        if self.history_agent.currentIndex():
            filters["agent"] = self.history_agent.currentData()
        if self.history_status.currentIndex():
            filters["status"] = self.history_status.currentText()
        if self.history_project.isChecked() and self.view_project():
            filters["project_id"] = identifier(self.view_project())
        if self.history_branch.text().strip():
            filters["branch"] = self.history_branch.text().strip()
        if self.history_date.text().strip():
            filters["date_from"] = self.history_date.text().strip()
            filters["date_to"] = self.history_date.text().strip()
        if self.history_errors.isChecked():
            filters["error"] = True
        try:
            project_rows = self.core.list_projects()
            projects = {identifier(project): project_label(project, project_rows) for project in project_rows}
            if query:
                rows = self.core.search(query, **filters)
                for result in rows:
                    row = result.get("record", result)
                    task = self.core.get_task(row['task_id']) if row.get('task_id') and hasattr(self.core, 'get_task') else None
                    title = compact(row.get('title') or (task or {}).get('title') or row.get('summary') or row.get('content')) or '未命名結果'
                    item = QTreeWidgetItem([title, projects.get(row.get("project_id") or (task or {}).get('project_id'), "未知專案"), str(row.get("type") or row.get("role", "")), str(row.get("agent", "")), str(row.get("timestamp", "")), str(row.get("content") or row.get("summary", ""))[:400]])
                    item.setData(0, Qt.UserRole, ("result", row))
                    self.history_table.addTopLevelItem(item)
            else:
                for task in self.core.list_tasks(**filters):
                    item = QTreeWidgetItem([compact(task.get("title")) or '未命名任務', projects.get(task.get("project_id"), "未知專案"), str(task.get("status", "")), str(task.get("current_owner", "")), str(task.get("updated_at") or task.get("created_at", "")), str(task.get("branch", ""))])
                    item.setData(0, Qt.UserRole, ("task", task))
                    self.history_table.addTopLevelItem(item)
            for col, width in enumerate((250, 170, 110, 100, 180)):
                self.history_table.setColumnWidth(col, width)
        except Exception as exc:
            self.show_error(str(exc), False)

    def open_history_item(self, item):
        kind, row = item.data(0, Qt.UserRole)
        if kind == "task" and self.confirm_context_change():
            self.run(lambda: self.core.select_task(identifier(row)), lambda _: (self.show_records(), self.reload_context(), self.mode.setCurrentIndex(self.mode.findData("Workspace"))))
        elif kind == "result":
            self.show_detail("Search result", row)

    def compare(self):
        task = self.view_task() or {}
        messages = [message for message in (self.core.messages(task['id']) if task else []) if message.get("role") == "assistant"]
        if len(messages) < 2:
            self.show_error("Two assistant responses are required for comparison.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Compare responses — no automatic verdict")
        dialog.resize(1120, 680)
        layout = QHBoxLayout(dialog)
        for side in range(2):
            column = QVBoxLayout()
            selector = QComboBox()
            body = QPlainTextEdit()
            body.setReadOnly(True)
            for message in messages:
                selector.addItem(f"{message.get('agent', '').title()} · {message.get('timestamp', '')} · {str(message.get('content', ''))[:45]}", message)
            selector.currentIndexChanged.connect(lambda _, combo=selector, editor=body: editor.setPlainText(plain(combo.currentData().get("content", ""))))
            selector.setCurrentIndex(max(0, len(messages) - 2 + side))
            body.setPlainText(plain(selector.currentData().get("content", "")))
            column.addWidget(selector)
            column.addWidget(body, 1)
            layout.addLayout(column, 1)
        dialog.exec()

    def inspect_artifacts(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Project changes and tests — read only")
        dialog.resize(1120, 720)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        unified = QPlainTextEdit("Reading repository status…")
        unified.setReadOnly(True)
        unified.setFont(QFont("Consolas", 10))
        tabs.addTab(unified, "Unified diff")
        split = QSplitter()
        before, after = QPlainTextEdit(), QPlainTextEdit()
        for editor in (before, after):
            editor.setReadOnly(True)
            editor.setFont(QFont("Consolas", 10))
            split.addWidget(editor)
        tabs.addTab(split, "Side by side")
        files = QTreeWidget()
        files.setHeaderLabels(["Status", "Changed file"])
        tabs.addTab(files, "Changed files")
        test_table = QTreeWidget()
        test_table.setHeaderLabels(["Command", "Framework", "Passed", "Failed", "Skipped", "Duration", "Exit"])
        tabs.addTab(test_table, "Tests")
        git_info = QPlainTextEdit()
        git_info.setReadOnly(True)
        tabs.addTab(git_info, "Branch / log")
        artifacts = ArtifactPanel(self)
        tabs.addTab(artifacts, "Artifacts")
        actions = QHBoxLayout()
        actions.addWidget(button("Copy diff", lambda: QApplication.clipboard().setText(unified.toPlainText())))
        patch_state = {"diff": ""}
        save_button = button("Save patch…", lambda: self.save_patch(patch_state["diff"], dialog))
        save_button.setEnabled(False)
        actions.addWidget(save_button)
        actions.addWidget(button("Open selected file", lambda: self.open_changed_file(files)))
        actions.addStretch()
        actions.addWidget(button("Close", dialog.accept))
        layout.addLayout(actions)
        def loaded(snapshot):
            diff = snapshot.get("diff", "")
            patch_state["diff"] = diff
            diff_result = snapshot.get("diff_result") or {}
            error = diff_result.get("stderr") or snapshot.get("diff_error") or snapshot.get("error", "")
            code = diff_result.get("exit_code", snapshot.get("diff_exit_code"))
            save_button.setEnabled(bool(diff) and code in (0, None))
            if error or code not in (0, None):
                unified.setPlainText(f"Diff inspection exit: {code}\n{error}\n\n{diff}")
            else:
                notice = diff_result.get("notice", "")
                unified.setPlainText(diff or notice or "No tracked changes.")
            left, right = [], []
            for line in diff.splitlines():
                if line.startswith("-") and not line.startswith("---"):
                    left.append(line)
                    right.append("")
                elif line.startswith("+") and not line.startswith("+++"):
                    left.append("")
                    right.append(line)
                else:
                    left.append(line)
                    right.append(line)
            before.setPlainText("\n".join(left))
            after.setPlainText("\n".join(right))
            git_info.setPlainText(plain({key: value for key, value in snapshot.items() if key != "diff"}))
            status = snapshot.get("status", "")
            if isinstance(status, str):
                for line in status.splitlines():
                    name, change = "", ""
                    if line.startswith("1 "):
                        parts = line.split(" ", 8)
                        change, name = parts[1], parts[8] if len(parts) > 8 else ""
                    elif line.startswith("2 "):
                        parts = line.split(" ", 9)
                        change, name = parts[1], parts[9].split("\t")[0] if len(parts) > 9 else ""
                    elif line.startswith("? "):
                        change, name = "??", line[2:]
                    elif line and not line.startswith("#"):
                        change, name = line[:2], line[3:]
                    if name:
                        item = QTreeWidgetItem([change, name])
                        item.setData(0, Qt.UserRole, name)
                        files.addTopLevelItem(item)
            for panel in self.panels.values():
                if panel.agent != "dot" and (self.core.agent_project(panel.agent) or {}).get('id') == snapshot.get('project_id', self.core.current_project_id):
                    panel.branch_label.setText(self.branch_text(snapshot))
        project = self.view_project() or {}
        if project: self.run(lambda: self.core.git_snapshot(project['id']), loaded)
        else: unified.setPlainText('請先選擇目前 Agent 的 Project')
        task = self.view_task() or {}
        for event in (self.core.events(task_id=task['id'], limit=3000) if task else []):
            event = {**(event.get("payload") or {}), **event}
            if event.get("type") in ("test", "test_result") or event.get("test"):
                data = event.get("test") if isinstance(event.get("test"), dict) else event
                if "duration" not in data and data.get("duration_ms") is not None:
                    data = dict(data, duration=f"{data['duration_ms']} ms")
                item = QTreeWidgetItem([str(data.get(key, "Unknown")) for key in ("command", "framework", "passed", "failed", "skipped", "duration", "exit_code")])
                item.setData(0, Qt.UserRole, event)
                test_table.addTopLevelItem(item)
        test_table.itemDoubleClicked.connect(lambda item: self.show_detail("Test evidence", item.data(0, Qt.UserRole)))
        dialog.exec()

    def save_patch(self, diff_text, parent=None):
        if not diff_text:
            self.show_error("There is no loaded patch to save.")
            return
        target, _ = QFileDialog.getSaveFileName(parent or self, "Save patch", "changes.patch", "Patch (*.patch)")
        if target:
            self.run(lambda: self.core.save_patch(diff_text, target),
                     lambda path: self.footer.setText("Patch exported · " + str(path)))

    @staticmethod
    def branch_text(snapshot):
        if not snapshot.get("is_git", True):
            return "Git: not a repository"
        return f"分支：{snapshot.get('branch') or '—'}  ·  未提交變更：{snapshot.get('dirty', '—')}  ·  ↑{snapshot.get('ahead', '—')} ↓{snapshot.get('behind', '—')}"

    def open_changed_file(self, files):
        item = files.currentItem()
        if not item:
            return
        try:
            path = self.core.project_file(item.data(0, Qt.UserRole), identifier(self.view_project() or {}))
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise RuntimeError("The operating system could not open the selected file; no file handler may be installed.")
        except Exception as exc:
            self.show_error(str(exc))

    def export(self):
        task = self.view_task()
        if not task:
            self.show_error("Select a task to export.")
            return
        filters = "Markdown (*.md);;JSON (*.json);;ZIP (*.zip);;HTML (*.html)"
        target, selected = QFileDialog.getSaveFileName(self, "Export task", f"{identifier(task)}.md", filters)
        if target:
            format_name = {".md": "markdown", ".json": "json", ".zip": "zip", ".html": "html"}.get(Path(target).suffix.lower())
            if format_name is None:
                format_name = selected.split()[0].lower() if selected.split() else "markdown"
            include_screenshots = False
            if format_name == "zip":
                screenshots = [artifact for artifact in self.core.artifacts(identifier(task)) if artifact.get("type") == "screenshot"]
                if screenshots and not self.confirm_screenshot_export(screenshots):
                    return
                include_screenshots = bool(screenshots)
            self.run(lambda: self.core.export_task(identifier(task), format_name, target, include_screenshots=include_screenshots), lambda _: self.footer.setText(f"Task exported · {target}"))

    def confirm_screenshot_import(self, path, parent=None):
        box = QMessageBox(QMessageBox.Warning, "Import screenshot pixels", "", QMessageBox.Yes | QMessageBox.No, parent or self)
        box.setTextFormat(Qt.PlainText)
        box.setText("Store this explicitly selected screenshot as a task artifact?\n\n" + Path(path).name + "\n\nImage pixels are NOT automatically redacted and may contain secrets or private information. Only import an image you intend to retain. Export requires a separate image review.")
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def confirm_screenshot_export(self, artifacts):
        if not artifacts:
            return True
        return ScreenshotReviewDialog(self, artifacts, require_confirmation=True).exec() == QDialog.Accepted

    def diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Workspace diagnostics")
        dialog.resize(890, 650)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(plain(self.core.diagnostics()))
        text.setReadOnly(True)
        layout.addWidget(text)
        layout.addWidget(label("Credentials and hidden reasoning are excluded. Connected requires a backend handshake.", True))
        def export_diagnostics():
            target, _ = QFileDialog.getSaveFileName(dialog, "Export portable diagnostics", "workspace-diagnostics.zip", "ZIP (*.zip)")
            if target:
                self.run(lambda: self.core.export_diagnostics(target), lambda _: self.footer.setText("Diagnostics exported · " + target))
        layout.addWidget(button("Export diagnostics…", export_diagnostics))
        layout.addWidget(button("Close", dialog.accept))
        dialog.exec()

    @staticmethod
    def hermes_field_values(fields):
        return {key: widget.value() if isinstance(widget, QSpinBox) else widget.text().strip()
                for key, widget in fields.items()}

    def test_hermes_cli(self, fields, output, trigger, dialog_state):
        from ..adapters.hermes import HermesAdapter
        values = self.hermes_field_values(fields)
        trigger.setEnabled(False)
        output.setText('檢查中…（只讀取 CLI help，不傳送訊息）')
        def probe():
            from ..security import redact_text
            try:
                candidate = HermesAdapter(lambda *args, **kwargs: None, harness='hermes', **values)
                result = candidate.probe()
                return result['detail'] + ('\n執行檔：' + result['executable'] if result.get('executable') else '')
            except Exception as exc:
                return redact_text(str(exc))
        def completed(message):
            if dialog_state['closed']: return
            output.setText(message)
            trigger.setEnabled(True)
        self.run(probe, completed)

    def settings(self, agent=None):
        from ..adapters.hermes import hermes_settings
        requested_agent = agent
        dialog = QDialog(self)
        dialog.setWindowTitle("設定")
        dialog.resize(800, 660)
        dialog_state = {'closed': False}
        dialog.finished.connect(lambda _: dialog_state.update(closed=True))
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        agent_page = QWidget()
        agent_layout = QVBoxLayout(agent_page)
        agent_layout.addWidget(label("後端設定於下次連線生效。模型與思考強度選項來自實際連線的後端。", True))
        fields = {}
        local_fields = {}
        codex_fields = {}
        local_pages = []
        for agent in self.agents:
            form = QFormLayout()
            form.addRow(label(self.role_names[agent] + " · " + ROLE_LABELS[self.core.provider(agent)]))
            diag = self.core.diagnostics(agent)
            saved = self.core.get_setting("agent." + agent, {}) or {}
            local_settings = hermes_settings(saved) if self.core.provider(agent) == 'local' else None
            enabled = QCheckBox("啟用")
            enabled.setObjectName(f"default_enabled_{agent}")
            enabled.setChecked(saved.get("enabled", True))
            executable = QLineEdit(local_settings.get('executable', '') if local_settings is not None
                                   else saved.get("executable", diag.get("executable", "")))
            if self.core.provider(agent) == 'local':
                executable.setPlaceholderText('留空時自動偵測 Hermes CLI')
            executable.setObjectName(f"executable_{agent}")
            timeout = QSpinBox()
            timeout.setObjectName(f"timeout_{agent}")
            timeout.setRange(5, 3600)
            timeout.setValue(int(saved.get("timeout", 120)))
            model, effort, project = QComboBox(), QComboBox(), QComboBox()
            model.setObjectName(f"default_model_{agent}")
            effort.setObjectName(f"default_effort_{agent}")
            project.setObjectName(f"default_project_{agent}")
            model.addItem("由 ChatGPT 管理" if agent == "dot" else "後端預設 · " + self.panels[agent].capability_status("supports_model_selection"), None)
            cap = self.core.capabilities(agent)
            for choice in cap.get("models", []) if cap.get("supports_model_selection") else []:
                if isinstance(choice, str):
                    model.addItem(choice, choice)
                else:
                    value = choice.get("id") or choice.get("model") or choice.get("value")
                    model.addItem(choice.get("displayName") or choice.get("display_name") or choice.get("name") or str(value), value)
            model.setEnabled(model.count() > 1)
            model.setCurrentIndex(max(0, model.findData(saved.get("default_model"))))
            def set_efforts(index=0, agent=agent, model=model, effort=effort, saved=saved):
                effort.clear()
                effort.addItem("由 ChatGPT 管理" if agent == "dot" else "後端預設 · " + self.panels[agent].capability_status("supports_effort"), None)
                if self.core.capabilities(agent).get("supports_effort"):
                    for choice in self.core.list_efforts(agent, model.currentData()):
                        value = choice if isinstance(choice, str) else choice.get("reasoningEffort") or choice.get("effort") or choice.get("value")
                        if value:
                            effort.addItem(str(value), value)
                effort.setEnabled(effort.count() > 1)
                effort.setCurrentIndex(max(0, effort.findData(saved.get("default_effort"))))
            model.currentIndexChanged.connect(set_efforts)
            set_efforts()
            project.addItem("沿用此 Agent 選擇的 Project", None)
            for item in self.core.list_projects():
                project.addItem(project_label(item, self.core.list_projects()), identifier(item))
            project.setCurrentIndex(max(0, project.findData(saved.get("default_project"))))
            form.addRow("", enabled)
            form.addRow("後端", label(diag.get("backend", "Unknown"), True))
            form.addRow("執行檔", executable)
            if self.core.provider(agent) == 'local':
                provider = QLineEdit(local_settings.get('provider', ''))
                provider.setObjectName('hermes_provider')
                provider.setProperty('agent_id', agent)
                provider.setPlaceholderText('留空時沿用 Hermes 設定')
                local_model = QLineEdit(local_settings.get('model', ''))
                local_model.setObjectName('hermes_model')
                local_model.setPlaceholderText('留空時沿用 Hermes 設定')
                run_budget = QSpinBox()
                run_budget.setObjectName('hermes_run_budget')
                run_budget.setRange(1, 86400)
                run_budget.setValue(int(local_settings.get('run_budget', 600)))
                max_turns = QSpinBox()
                max_turns.setObjectName('hermes_max_turns')
                max_turns.setRange(1, 1000)
                max_turns.setValue(int(local_settings.get('max_turns', 60)))
                form.addRow('Provider（選填）', provider)
                form.addRow('模型名稱（選填）', local_model)
                form.addRow('執行預算（秒）', run_budget)
                form.addRow('回合上限', max_turns)
                form.addRow(label('直接使用 Hermes CLI。Provider 與模型留空時沿用 Hermes 既有設定；API key 由 Hermes 的環境變數管理。Workspace 不修改 Hermes config、不使用 --yolo；工具權限由 Hermes 管理。', True))
                local_fields[agent] = dict(executable=executable, provider=provider, model=local_model,
                                           run_budget=run_budget, max_turns=max_turns)
                probe_result = label('檢查只執行 CLI help，不儲存設定、不建立 session、不呼叫模型。', True)
                probe_result.setObjectName('hermes_probe_result')
                probe_button = button('檢查 Hermes CLI', lambda: None, 'hermes_probe')
                probe_button.setProperty('agent_id', agent)
                probe_button.clicked.connect(lambda checked=False, values=local_fields[agent], output=probe_result, trigger=probe_button:
                                             self.test_hermes_cli(values, output, trigger, dialog_state))
                form.addRow(probe_button)
                form.addRow(probe_result)
            if self.core.provider(agent) == 'codex':
                sandbox, approval_policy = QComboBox(), QComboBox()
                sandbox.setObjectName('codex_sandbox_' + agent)
                approval_policy.setObjectName('codex_approval_policy_' + agent)
                for text, value in (('沿用 Codex 設定', None), ('唯讀', 'read-only'),
                                    ('可寫入專案', 'workspace-write'), ('完整存取', 'danger-full-access')):
                    sandbox.addItem(text, value)
                for text, value in (('沿用 Codex 設定', None), ('需要時詢問', 'on-request'),
                                    ('失敗時詢問（此版本不支援）', 'on-failure'), ('不詢問', 'never')):
                    approval_policy.addItem(text, value)
                unsupported = approval_policy.model().item(approval_policy.findData('on-failure'))
                unsupported.setEnabled(False)
                unsupported.setToolTip('本機 app-server schema 不支援 on-failure。')
                sandbox.setCurrentIndex(max(0, sandbox.findData(saved.get('sandbox'))))
                approval_policy.setCurrentIndex(max(0, approval_policy.findData(saved.get('approval_policy'))))
                form.addRow('沙箱', sandbox)
                form.addRow('核准', approval_policy)
                form.addRow(label('下次建立或恢復對話生效；目前 thread 的實際權限顯示於面板標頭下方。', True))
                codex_fields[agent] = (sandbox, approval_policy)
            if self.core.provider(agent) != 'local':
                form.addRow("逾時（秒）", timeout)
                form.addRow("預設模型", model)
                form.addRow("預設強度", effort)
            form.addRow("預設專案", project)
            form.addRow("串流", label(self.panels[agent].capability_status("supports_streaming"), True))
            form.addRow("原始日誌", label("安全過濾後的稽核紀錄固定啟用", True))
            if self.core.provider(agent) == 'local':
                local_page = QWidget()
                local_layout = QVBoxLayout(local_page)
                local_layout.addLayout(form)
                local_layout.addStretch()
                local_scroll = QScrollArea()
                local_scroll.setWidgetResizable(True)
                local_scroll.setWidget(local_page)
                local_pages.append((local_scroll, self.role_names[agent], agent))
            else:
                agent_layout.addLayout(form)
            fields[agent] = (saved, enabled, executable, timeout, model, effort, project)
        agent_scroll = QScrollArea()
        agent_scroll.setWidgetResizable(True)
        agent_scroll.setWidget(agent_page)
        tabs.addTab(agent_scroll, "角色與模型")
        for local_scroll, name, local_agent in local_pages:
            tabs.addTab(local_scroll, name)
            if requested_agent == local_agent:
                tabs.setCurrentWidget(local_scroll)
        for name, text in (
            ("Projects", "Each Agent keeps its own Project and Session. Record-page navigation never switches an Agent. Git integration is read only."),
            ("Logs", "Raw JSONL and structured events are retained locally. Safety filtering redacts credentials and excludes hidden reasoning before persistence. Open per-agent logs from each panel."),
            ("Permissions", "各後端原有的權限與 sandbox 設定仍有效。Claude／Codex 可透過 Workspace 回覆工具核准，預設每次詢問；可在角色的 ⋯ 選單調整。Hermes 使用自身工具權限設定，不支援 Workspace 的核准模式；Workspace 不修改 Hermes config，也不使用 --yolo。"),
            ("Advanced", "Automatic orchestration: OFF\nNo agents connect automatically at startup. Unsupported capabilities remain unavailable. Use Diagnostics for executable, backend, session, cwd, last event and last error."),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(label(text))
            page_layout.addStretch()
            tabs.addTab(page, {"Projects":"專案", "Logs":"日誌", "Permissions":"權限", "Advanced":"進階"}.get(name, name))
        paths = QWidget()
        paths_form = QFormLayout(paths)
        paths_form.addRow("應用程式資料", label(str(getattr(self.core, "data_dir", "Per-user app data")), True))
        legacy_root = QLineEdit(self.core.get_setting("legacy.root", LEGACY_MONITOR_ROOT))
        paths_form.addRow("舊版監看根目錄", legacy_root)
        paths_form.addRow(label("Monitor reads the existing four log files incrementally. It does not write, reset or control the original Monitor sessions.", True))
        tabs.addTab(paths, "路徑")
        appearance = QWidget()
        appearance_layout = QVBoxLayout(appearance)
        appearance_layout.addWidget(label('主題', True))
        theme_choice = QComboBox()
        theme_choice.setObjectName('ui_theme')
        for name in ('desktop', 'hacker', 'metal'):
            theme_choice.addItem(name, name)
        theme_choice.setCurrentIndex(max(0, theme_choice.findData(self.theme_name)))
        def change_theme():
            name = theme_choice.currentData()
            self.core.set_setting('ui.theme', name)
            self.apply_theme(name)
        theme_choice.currentIndexChanged.connect(change_theme)
        appearance_layout.addWidget(theme_choice)
        topmost = QCheckBox("保持在最上層")
        topmost.setChecked(self.core.get_setting("ui.always_on_top", False))
        appearance_layout.addWidget(topmost)
        appearance_layout.addWidget(label("Ctrl+B toggles projects/sessions. Ctrl+1/2/3/4 focuses a role. Ctrl+Shift+D opens work details. Ctrl+Enter sends after IME composition. F11 toggles fullscreen. Drafts and view state survive navigation during this app run; window geometry restores across launches.", True))
        appearance_layout.addStretch()
        tabs.addTab(appearance, "外觀")
        retention = QWidget()
        retention_form = QFormLayout(retention)
        days, size = QSpinBox(), QSpinBox()
        days.setRange(1, 3650)
        size.setRange(1, 1024)
        days.setValue(int(self.core.get_setting("retention.days", 90)))
        size.setValue(int(self.core.get_setting("retention.max_mb", 20)))
        archive = QCheckBox("封存輪替日誌")
        archive.setChecked(self.core.get_setting("retention.archive", True))
        retention_form.addRow("保留天數", days)
        retention_form.addRow("原始日誌上限（MB）", size)
        retention_form.addRow(archive)
        tabs.addTab(retention, "保留")
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Save).setText("儲存")
        actions.button(QDialogButtonBox.Cancel).setText("取消")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() == QDialog.Accepted:
            for agent, (saved, enabled, executable, timeout, model, effort, project) in fields.items():
                values = dict(saved, enabled=enabled.isChecked(), executable=executable.text().strip(), timeout=timeout.value(), default_project=project.currentData())
                if self.core.provider(agent) == 'local':
                    values.update(self.hermes_field_values(local_fields[agent]))
                    values['harness'] = 'hermes'
                if model.isEnabled():
                    values["default_model"] = model.currentData()
                if effort.isEnabled():
                    values["default_effort"] = effort.currentData()
                if self.core.provider(agent) == 'local':
                    values['default_model'] = values['model']
                if agent in codex_fields:
                    sandbox, approval_policy = codex_fields[agent]
                    permissions = dict(sandbox=sandbox.currentData(), approval_policy=approval_policy.currentData())
                    values.update(permissions)
                    adapter = self.core.adapters.get(agent)
                    if adapter is not None:
                        adapter.settings.update(permissions)
                self.core.set_setting("agent." + agent, values)
                self.panels[agent].update_controls()
            self.core.set_setting("legacy.root", legacy_root.text().strip())
            self.core.set_setting("ui.always_on_top", topmost.isChecked())
            self.core.set_setting("retention.days", days.value())
            self.core.set_setting("retention.max_mb", size.value())
            self.core.set_setting("retention.archive", archive.isChecked())
            self.setWindowFlag(Qt.WindowStaysOnTopHint, topmost.isChecked())
            self.show()
            self.footer.setText("Settings saved. Reconnect idle agents to apply backend settings.")

    def closeEvent(self, event):
        busy = self.workers or any(panel.connection_state == "Busy" for panel in self.panels.values())
        if self._close_pending and busy:
            event.ignore()
            return
        request = self.core.requests.active()
        if not self._close_pending and (request or busy):
            message = (f"{self.core.agent_name(self.core.requests.agent)} 仍在執行 skill 派來的步驟 {request['label']}（{request['worktree']}）。"
                       "關閉會中止它，工作目錄可能留下未提交的修改。仍要關閉？" if request else
                       "仍有 Agent 在執行。關閉會要求取消，歷史會保留，重啟不會自動重送。仍要關閉？")
            result = QMessageBox.question(self, "確認關閉", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if result != QMessageBox.Yes:
                event.ignore()
                return
            # Keep the event loop and store alive until adapter-defined
            # cancellation and in-flight workers finish. Each adapter owns its
            # cancellation boundary, including Hermes child-tree termination.
            self._close_pending = True
            if self.orchestrator and self.orchestrator.active:
                self.orchestrator.stop('正在關閉工作區')
            self.run_timer.stop()
            self.footer.setText("Waiting for adapter cancellation before closing…")
            started = time.monotonic()
            def ready_to_close():
                if not self._close_pending:
                    return
                if self.workers or any(panel.connection_state == "Busy" for panel in self.panels.values()):
                    if time.monotonic() - started > 30:
                        self._close_pending = False
                        self.show_error("Cancellation is still pending. The workspace remains open so history can be retained.", False)
                        return
                    QTimer.singleShot(100, self, ready_to_close)
                    return
                self.close()
            def cancelled(_):
                QTimer.singleShot(0, self, ready_to_close)
            def failed(_):
                self._close_pending = False
            self.run(lambda: self.core.stop_task(confirmed=True), cancelled, on_error=failed)
            event.ignore()
            return
        self.save_context_state()
        self.core.set_setting("ui.geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.timer.stop()
        self.sync_timer.stop()
        self.run_timer.stop()
        if self.orchestrator and self.orchestrator.active:
            self.orchestrator.stop('工作區視窗已關閉')
        self._closed = True
        self._close_pending = False
        event.accept()
