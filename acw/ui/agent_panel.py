"""Per-agent conversation panel."""
from __future__ import annotations

import time
from pathlib import Path
from ..presentation import local_session_displays, project_label, task_label, compact
from .. import approvals
from ..theme import STATE_COLORS, STATE_IDLE, desktop_state_color

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .widgets import (
    APPROVAL_EVENTS,
    ActivityGroup,
    BUTTON_LABELS,
    EventCard,
    FocusLabel,
    MessageCard,
    PromptEdit,
    asdict,
    button,
    identifier,
    label,
)
from .dialogs import NativeSessionDialog, SessionDetailsDialog, SessionHistoryDialog


ROLE_NAMES = {"claude": "Claude", "dot": "G8毛", "codex": "Codex", "local": "Hermes"}
ROLE_LABELS = {"claude": "協作 agent", "dot": "轉接／複核", "codex": "協作 agent", "local": "Hermes agent"}
STATE_LABELS = {"Disconnected": "未連線", "Connected": "已連線", "Busy": "處理中", "Connecting": "連線中",
                "Error": "錯誤", "Blocked": "受阻", "Offline": "離線", "Stopping": "停止中", "Interrupted": "已中斷"}


class AgentPanel(QFrame):
    def __init__(self, agent, window):
        super().__init__()
        self.agent, self.window = agent, window
        self.provider = window.core.provider(agent)
        self.capabilities = {}
        self.cards = {}
        self.approvals = {}
        self.pending_approval_events = {}
        self.visible_limit = 300
        self.hidden_count = 0
        self.approval_rules = set()  # "always allow" choices; they last until this role disconnects
        self.attachments = []
        self.connection_state = "Disconnected"
        self.monitor = False
        self._effort_invalid = False
        self._effort_error = ""
        self._restoring_view = False
        self._view_generation = 0
        self._restore_scroll = None
        self.setObjectName("panel")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = FocusLabel(self.window.role_names[agent])
        self.title.setObjectName("agentTitle")
        self.title.setToolTip("按兩下以專注此角色")
        self.title.double_clicked.connect(lambda: window.focus_agent(agent))
        titles.addWidget(self.title)
        titles.addWidget(label(ROLE_LABELS[self.provider], True))
        header.addLayout(titles)
        header.addStretch()
        self.state = label("未連線")
        self.state.setObjectName("status")
        self.state.setWordWrap(False)
        self.state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.state)
        self.connect_button = button("Connect", self.connect_agent, f"connect_{agent}")
        self.connect_button.setProperty("primary", True)
        self.connect_button.setAccessibleName(f"Connect {self.window.role_names[agent]}")
        header.addWidget(self.connect_button)
        self.more_button = QToolButton()
        self.more_button.setText("⋯")
        self.more_button.setAccessibleName(f"{self.window.role_names[agent]} conversation actions")
        self.more_button.setToolTip("對話、歷史、能力、原始事件與日誌")
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        more = QMenu(self.more_button)
        more.addAction("工作交接關聯…" if agent=="dot" else "對話…", lambda: window.show_sessions(agent))
        if agent=="dot":
            more.addAction("載入更早訊息…",lambda:self.read_dot(True))
        else:
            more.addAction("本機歷史…", self.show_session_history)
        if self.provider == 'codex':
            more.addAction("Codex 本機對話…", lambda: window.show_instance_sessions(agent))
        if self.provider == 'claude':
            more.addAction("Desktop 專案與對話…", lambda: window.show_instance_sessions(agent))
        more.addAction("能力詳情…", self.show_capabilities)
        more.addSeparator()
        more.addAction("原始事件…", lambda: window.show_agent_events(agent))
        more.addAction("日誌…", lambda: window.open_logs(agent))
        more.addAction("專案檔案", lambda: window.open_project(agent))
        if agent != "dot" and self.provider != 'local':
            more.addSeparator()
            mode_menu = more.addMenu("核准方式")
            self.approval_actions_menu = {}
            for mode in approvals.MODES:
                action = mode_menu.addAction(approvals.MODE_LABELS[mode], lambda checked=False, mode=mode: window.set_approval_mode(agent, mode))
                action.setCheckable(True)
                self.approval_actions_menu[mode] = action
            mode_menu.aboutToShow.connect(lambda: [action.setChecked(mode == window.approval_mode(agent))
                                                   for mode, action in self.approval_actions_menu.items()])
        self.more_button.setMenu(more)
        header.addWidget(self.more_button)
        layout.addLayout(header)
        self.context_button = button("選擇專案與對話…", lambda: window.show_sessions(agent), f"context_{agent}")
        self.context_button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.context_button)
        if agent=="dot": self.context_button.hide()
        self.notice = label("能力尚未偵測 · 請在準備好時連線", True)
        # One quiet line; the full text stays in the tooltip.
        self.notice.setWordWrap(False)
        self.notice.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.notice.setToolTip(self.notice.text())
        layout.addWidget(self.notice)

        # These are the original session actions, moved together to the sidebar.
        # Keeping the same widgets and callbacks retains backend/consent behavior.
        self.session_controls = QWidget()
        session_layout = QVBoxLayout(self.session_controls)
        session_layout.setContentsMargins(0, 8, 0, 0)
        session_layout.setSpacing(8)
        session_layout.addWidget(label('Project · 只影響此 Agent', True))
        project_row = QHBoxLayout()
        self.project = QComboBox()
        self.project.setObjectName(f"project_{agent}")
        self.project.setAccessibleName(f"{self.window.role_names[agent]} 專案")
        self.project.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.project.setMinimumContentsLength(10)
        self.project.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.project.currentIndexChanged.connect(self.project_selected)
        project_row.addWidget(self.project, 1)
        project_row.addWidget(button('+', lambda: self.window.new_project(agent=self.agent), f'new_project_{agent}'))
        session_layout.addLayout(project_row)
        task_row = QHBoxLayout()
        self.task = QComboBox()
        self.task.setObjectName(f"task_{agent}")
        self.task.setAccessibleName(f"{self.window.role_names[agent]} 任務")
        self.task.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.task.setMinimumContentsLength(10)
        self.task.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.task.currentIndexChanged.connect(self.task_selected)
        task_row.addWidget(self.task, 1)
        self.new_task_button = button("新增任務", self.new_task, f"new_task_{agent}")
        task_row.addWidget(self.new_task_button)
        session_layout.addLayout(task_row)
        # Retain legacy task mappings for data compatibility, outside everyday chat controls.
        if agent != 'dot':
            self.task.hide()
            self.new_task_button.hide()
        session_heading = QWidget()
        session_heading_row = QHBoxLayout(session_heading)
        session_heading_row.setContentsMargins(0, 0, 0, 0)
        session_heading_row.addWidget(label('Session', True), 1)
        self.session_more = QToolButton()
        self.session_more.setObjectName(f'session_actions_{agent}')
        self.session_more.setText('⋯')
        self.session_more.setAccessibleName(f'{self.window.role_names[agent]} 對話與專案操作')
        self.session_more.setToolTip('重新命名、詳細 / ID、探索對話與專案資訊')
        self.session_more.setPopupMode(QToolButton.InstantPopup)
        self.session_menu = QMenu(self.session_more)
        self.session_more.setMenu(self.session_menu)
        session_heading_row.addWidget(self.session_more)
        session_layout.addWidget(session_heading)
        session_heading.setVisible(agent != 'dot')
        self.session_search = QLineEdit()
        self.session_search.setObjectName(f"session_search_{agent}")
        self.session_search.setPlaceholderText("搜尋已保存的對話…")
        self.session_search.setAccessibleName(f"Search {self.window.role_names[agent]} local sessions")
        self.session_search.textChanged.connect(self.filter_sessions)
        session_layout.addWidget(self.session_search)
        self.session = QComboBox()
        self.session.setObjectName(f"session_{agent}")
        self.session.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.session.setMinimumContentsLength(10)
        self.session.setAccessibleName(f"{self.window.role_names[agent]} session")
        session_layout.addWidget(self.session)
        self.current_session_label = label("綁定對話：尚未建立或開啟", True)
        self.current_session_label.setObjectName(f"current_session_{agent}")
        session_layout.addWidget(self.current_session_label)
        self.current_session_label.hide()
        session_buttons = QGridLayout()
        self.session_details = button("詳細 / ID", self.show_session_details, f"session_details_{agent}")
        self.new_button = button("New", self.new_session, f"new_session_{agent}")
        self.resume_button = button("Resume", self.resume_session, f"resume_session_{agent}")
        self.new_button.setText('新對話')
        self.resume_button.setText('開啟對話')
        self.rename_button = button("Rename", self.rename_session, f"rename_session_{agent}")
        self.discover_button = button("Discover…", self.discover_sessions, f"discover_sessions_{agent}")
        self.discover_button.setToolTip("Explicitly list native backend sessions; import metadata without resuming")
        for index, control in enumerate((self.new_button, self.resume_button)):
            session_buttons.addWidget(control, 0, index)
        session_layout.addLayout(session_buttons)
        self.session_actions = {}
        for key, control in (('rename', self.rename_button), ('details', self.session_details), ('discover', self.discover_button)):
            session_layout.addWidget(control)
            control.hide()
            action = self.session_menu.addAction(control.text(), lambda checked=False, control=control: control.click())
            self.session_actions[key] = (action, control)
        self.session_menu.addSeparator()
        self.session_menu.addAction('專案資訊…', self.show_project_details)
        if self.provider == 'local':
            self.session_menu.addAction('Hermes 設定…', lambda: window.settings(agent=self.agent))
        if agent == "dot":
            self.dot_select = button("Select G8毛…", self.select_dot, "select_dot")
            self.dot_refresh = button("Refresh", lambda: self.read_dot(False), "refresh_dot")
            self.dot_older = button("Older page", lambda: self.read_dot(True), "older_dot")
            session_layout.addWidget(self.dot_select)
            dot_controls = QHBoxLayout()
            dot_controls.addWidget(self.dot_refresh)
            dot_controls.addWidget(self.dot_older)
            session_layout.addLayout(dot_controls)
            session_layout.addWidget(label("Workspace 專案與任務僅供交接關聯，不會切換 G8毛 的持續對話。", True))
            for control in (self.session_search,self.session,self.current_session_label,self.new_button,
                            self.resume_button,self.rename_button,self.discover_button,self.session_details):
                control.hide()
            self.dot_select.setText("選擇 G8毛")
            self.dot_older.setText("載入更早訊息")
            self.dot_bind = button('將對話關聯到交接任務',self.bind_dot_task,'bind_dot_task')
            self.dot_bind.setToolTip('僅在 Workspace 保存此任務的交接對象，不建立、切換或讀取 dot 對話')
            session_layout.addWidget(self.dot_bind)
        self.cwd_label = label("工作目錄：尚未選擇", True)
        self.cwd_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # A long unbreakable path must not widen the sidebar past its viewport.
        self.cwd_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.branch_label = label("分支：—", True)
        session_layout.addWidget(self.cwd_label)
        session_layout.addWidget(self.branch_label)
        self.cwd_label.hide()
        self.branch_label.hide()
        session_layout.addStretch()

        self.pending_review = button("Pending backend approval · Review…", self.review_pending_approval, f"pending_approval_{agent}")
        self.pending_review.setToolTip("A human must review and explicitly confirm this request. New events do not hide this reminder.")
        self.pending_review.hide()
        layout.addWidget(self.pending_review)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName(f"conversation_{agent}")
        self.scroll.setMinimumHeight(100)
        self.scroll.setProperty("well", True)
        self.transcript = QWidget()
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(8, 8, 8, 8)
        self.transcript_layout.setSpacing(10)
        self.empty = label("對話將顯示在這裡。\n請在準備好時連線。", True)
        self.empty.setObjectName('empty_conversation')
        self.empty.setAlignment(Qt.AlignCenter)
        self.transcript_layout.addWidget(self.empty)
        self.transcript_layout.addStretch()
        self.scroll.setWidget(self.transcript)
        # Outside the transcript layout so it never counts as a conversation item.
        self.older_button = self.make_older_button()
        layout.addWidget(self.older_button)
        layout.addWidget(self.scroll, 1)
        self.new_messages = button("New messages ↓", self.jump_to_latest, f"new_messages_{agent}")
        self.new_messages.hide()
        layout.addWidget(self.new_messages)
        self.input = PromptEdit()
        self.input.setObjectName(f"input_{agent}")
        self.input.setAccessibleName(f"Message {self.window.role_names[agent]}")
        self.input.setPlaceholderText(f"傳送訊息給 {self.window.role_names[agent]}…  Ctrl+Enter 傳送")
        self.input.setMinimumHeight(56)
        self.input.setMaximumHeight(96)
        self.input.submit.connect(self.send)
        self.input.files_dropped.connect(self.add_attachments)
        self.composer = QFrame()
        self.composer.setObjectName("composer")
        composer = QVBoxLayout(self.composer)
        composer.setContentsMargins(10, 8, 10, 8)
        composer.setSpacing(4)
        layout.addWidget(self.composer)
        self.send_error = ''
        self.send_feedback = label('')
        self.send_feedback.setObjectName(f'send_feedback_{agent}')
        self.send_feedback.hide()
        composer.addWidget(self.send_feedback)
        composer.addWidget(self.input)
        self.attachment_label = label("", True)
        self.attachment_label.hide()
        composer.addWidget(self.attachment_label)
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model = QComboBox()
        self.model.setObjectName(f"model_{agent}")
        self.model.setAccessibleName(f"{self.window.role_names[agent]} 模型")
        self.model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model.setMinimumContentsLength(7)
        self.model.currentIndexChanged.connect(self.model_changed)
        self.effort = QComboBox()
        self.effort.setObjectName(f"effort_{agent}")
        self.effort.setAccessibleName(f"{self.window.role_names[agent]} 思考強度")
        self.effort.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.effort.setMinimumContentsLength(6)
        self.effort.currentIndexChanged.connect(self.effort_selected)
        model_row.addWidget(self.model, 3)
        model_row.addWidget(self.effort, 2)
        composer.addLayout(model_row)
        if agent == 'dot':
            self.model.hide(); self.effort.hide()
        controls = QHBoxLayout()
        self.attach_button = button("Attach", self.attach)
        self.attach_button.setAccessibleName(f"Attach files to {self.window.role_names[agent]}")
        self.clear_attach_button = button("Clear", self.clear_attachments)
        self.clear_attach_button.hide()
        controls.addWidget(self.attach_button)
        controls.addWidget(self.clear_attach_button)
        self.approval_button = QToolButton()
        self.approval_button.setObjectName("ghost")
        self.approval_button.setAccessibleName(f"{self.window.role_names[agent]} 核准方式")
        self.approval_button.setPopupMode(QToolButton.InstantPopup)
        approval_menu = QMenu(self.approval_button)
        for mode in approvals.MODES:
            approval_menu.addAction(approvals.MODE_LABELS[mode], lambda checked=False, mode=mode: window.set_approval_mode(agent, mode))
        self.approval_button.setMenu(approval_menu)
        self.approval_button.setVisible(agent != "dot" and self.provider != 'local')
        controls.addWidget(self.approval_button)
        self._dot_follow = None
        self._dot_status_note = ""
        self.dot_visible_limit = 200
        if agent == "dot":
            self.dot_refresh_inline = button("Refresh", lambda: self.read_dot(False), "refresh_dot_inline")
            self.dot_refresh_inline.setToolTip("讀取 G8毛 的最新回覆")
            controls.addWidget(self.dot_refresh_inline)
            self._dot_timer = QTimer(self)
            self._dot_timer.timeout.connect(self._dot_follow_tick)
        controls.addStretch()
        self.stop_button = button("Stop", self.stop, "stop")
        self.stop_button.setAccessibleName(f"Stop {self.window.role_names[agent]}")
        controls.addWidget(self.stop_button)
        self.send_button = button("Send", self.send, "primary")
        self.send_button.setAccessibleName(f"Send to {self.window.role_names[agent]}")
        controls.addWidget(self.send_button)
        composer.addLayout(controls)
        self.update_capabilities({})

    def show_capabilities(self):
        self.window.show_detail(f"{self.window.role_names[self.agent]} capabilities", {
            "connection_state": self.connection_state,
            "model_selection": self.capability_status("supports_model_selection"),
            "effort": self.capability_status("supports_effort"),
            "capabilities": self.capabilities,
            "note": "Disconnected metadata is not a live handshake. Unknown does not mean unsupported.",
        })

    def capability_status(self, key):
        value = self.capabilities.get(key)
        if value is None:
            return "尚未偵測"
        if self.agent != "dot" and self.connection_state not in ("Connected", "Busy"):
            return "尚未偵測 · 需連線確認"
        return "已確認支援" if value else "此後端不支援"

    def capture_view_state(self):
        cursor = self.input.textCursor()
        selections = {}
        for mid, card in self.cards.items():
            selection = card.body.textCursor()
            selections[mid] = (selection.anchor(), selection.position(), card.body.verticalScrollBar().value())
        events = {}
        for widget in self.event_cards():
            events[widget.event_key] = widget.toggle.isChecked()
        return {
            "draft": self.input.toPlainText(), "draft_cursor": (cursor.anchor(), cursor.position()),
            "send_error": self.send_error,
            "attachments": list(self.attachments), "model": self.model.currentData(),
            "effort": self.effort.currentData(), "effort_invalid": self._effort_invalid, "session": self.session.currentData(),
            "session_search": self.session_search.text(), "scroll": self._restore_scroll if self._restore_scroll is not None else self.scroll.verticalScrollBar().value(),
            "selections": selections, "expanded_events": events,
            "pending": dict(self.pending_approval_events),
        }

    def restore_view_state(self, state):
        self._restoring_view = True
        self._view_generation += 1
        generation = self._view_generation
        self._restore_scroll = state.get('scroll', 0)
        self.input.setPlainText(state.get("draft", ""))
        self.send_error = state.get('send_error', '')
        self.attachments = list(state.get("attachments", []))
        self.attachment_label.setText("附件：" + ", ".join(Path(value).name for value in self.attachments))
        self.attachment_label.setVisible(bool(self.attachments))
        self.clear_attach_button.setVisible(bool(self.attachments))
        anchor, position = state.get("draft_cursor", (0, 0))
        cursor = self.input.textCursor()
        size = len(self.input.toPlainText())
        cursor.setPosition(min(anchor, size))
        cursor.setPosition(min(position, size), QTextCursor.KeepAnchor)
        self.input.setTextCursor(cursor)
        # A cached choice-required state is user intent, not a backend default.
        # Capability refresh must not replace it with the first available value.
        self._effort_invalid = bool(state.get("effort_invalid", False))
        index = self.model.findData(state.get("model"))
        if index >= 0:
            self.model.setCurrentIndex(index)
        if "effort" in state:
            value = state["effort"]
            index = self.effort.findData(value)
            if self._effort_invalid or (value is not None and index < 0):
                self._effort_invalid = True
                self.model_changed()
            elif index >= 0:
                self.effort.setCurrentIndex(index)
                # This restores a previously explicit, still-supported choice.
                if value is not None:
                    self._effort_invalid = False
        else:
            # A new context has no cached unresolved choice from another task.
            self.model_changed()
        self.session_search.setText(state.get("session_search", ""))
        self._fill_sessions(state.get("session", self.session.currentData()))
        for mid, selection in state.get("selections", {}).items():
            card = self.cards.get(mid)
            if card:
                cursor = card.body.textCursor()
                size = len(card.body.toPlainText())
                cursor.setPosition(min(selection[0], size))
                cursor.setPosition(min(selection[1], size), QTextCursor.KeepAnchor)
                card.body.setTextCursor(cursor)
                card.body.verticalScrollBar().setValue(selection[2])
        for widget in self.event_cards():
            if widget.event_key in state.get("expanded_events", {}):
                widget.toggle.setChecked(state["expanded_events"][widget.event_key])
        for group in self.activity_groups():
            if any(card.toggle.isChecked() for card in group.cards):
                group.toggle.setChecked(True)
        self.update_controls()
        def restore_scroll():
            if generation != self._view_generation: return
            self.scroll.verticalScrollBar().setValue(state.get("scroll", 0))
            self._restore_scroll = None
            self._restoring_view = False
        QTimer.singleShot(0, self, restore_scroll)

    def activity_groups(self):
        widgets = (self.transcript_layout.itemAt(index).widget() for index in range(self.transcript_layout.count()))
        return [widget for widget in widgets if isinstance(widget, ActivityGroup)]

    def event_cards(self):
        for index in range(self.transcript_layout.count()):
            widget = self.transcript_layout.itemAt(index).widget()
            if isinstance(widget, EventCard):
                yield widget
            elif isinstance(widget, ActivityGroup):
                yield from widget.cards

    def jump_to_latest(self):
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
        self.new_messages.hide()

    def connect_agent(self):
        if self.connection_state in ("Connected", "Busy"):
            if self.connection_state == "Busy":
                self.window.show_error("Stop the current turn before disconnecting.")
                return
            self.window.run(lambda: self.window.core.disconnect(self.agent), lambda _: self.window.refresh_agent(self.agent), self.agent)
        else:
            if self.agent == 'dot' and not self.dot_consent('connect'): return
            # Claude Code needs a working directory; guide instead of failing with a terse error.
            if self.agent != 'dot' and not self.window.core.agent_project(self.agent):
                self.window.require_project(self.window.role_names[self.agent] + " 需要先選擇 Project 才能連線。", agent=self.agent)
                return
            self.set_state("Connecting")
            def connect_agent():
                self.window.core.connect(self.agent)
                task = self.window.core.agent_task(self.agent) or {}
                if self.provider != 'local' and task.get(self.agent + '_session'):
                    self.window.core.resume_session(self.agent, task[self.agent + '_session'])
            operation = self.connect_dot_conversation if self.agent == 'dot' else connect_agent
            self.window.run(operation, lambda _: self.window.reload_context(), self.agent)

    def connect_dot_conversation(self):
        return self.window.core.connect_dot_conversation()

    def dot_consent(self, action):
        if self.monitor: return False
        from ..adapters.dot import DISCLOSURE
        adapter = self.window.core.adapters['dot']
        target = adapter.target_name+' ('+adapter.target+')' if adapter.target else 'Identifier/name enumeration only; select G8毛 next'
        box = QMessageBox(QMessageBox.Question, 'Unofficial Dot — explicit local action', '', QMessageBox.Yes | QMessageBox.No, self)
        box.setTextFormat(Qt.PlainText)
        follow = ('\nAfter this send the workspace reads this Dot for replies automatically, about every 8 seconds '
                  'for up to 5 minutes, then stops.') if action == 'send' else ''
        initial = '\n連接後會立即讀取這個 dot 既有對話的最近一頁訊息；不會建立新對話。' if action == 'connect' else ''
        box.setText(DISCLOSURE+'\nAction: '+action+'\nTarget: '+target+initial+follow+'\n此連接器不提供串流、伺服器停止、附件或建立新對話。')
        box.setDefaultButton(QMessageBox.No)
        if box.exec() != QMessageBox.Yes: return False
        adapter.authorize_manual_action(action)
        return True

    def select_dot(self):
        if self.monitor or self.connection_state in ('Busy','Connected','Connecting'): return
        if not self.dot_consent('list'): return
        def selected(items):
            if not items:
                self.window.show_error('Backend returned no Dot identifiers. No conversation selected.'); return
            item=self.choose_dot(items)
            if item is None: return
            if item['name'] != 'G8毛':
                self.window.show_error('This approved integration is scoped to G8毛. No other Dot was selected.'); return
            adapter=self.window.core.adapters['dot'];adapter.configure_target(item['id'],item['name'])
            saved=self.window.core.get_setting('agent.dot',{}) or {}
            if saved.get('dot_id')!=item['id']: saved.pop('expected_room_id',None)
            self.window.core.set_setting('agent.dot',dict(saved,dot_id=item['id'],dot_name=item['name']))
            self.window.reload_context()
            self.window.footer.setText('G8毛 selection saved. Click Connect Dot and review its separate consent; no conversation has been read.')
        self.window.run(self.window.core.adapters['dot'].discover_targets, selected, 'dot')

    def choose_dot(self, items):
        dialog=QDialog(self)
        dialog.setObjectName('dot_selection_dialog')
        dialog.setWindowTitle('Select and save G8毛 — no conversation read')
        layout=QVBoxLayout(dialog)
        layout.addWidget(label('Choose G8毛, then click Use G8毛 to save the selection. Connect is a separate action.',True))
        choices=QComboBox(dialog);choices.setObjectName('dot_target_choice')
        for item in items:
            choices.addItem(item['name'], item)
            choices.setItemData(choices.count()-1, 'Native Dot ID: '+item['id'], Qt.ToolTipRole)
        choices.setCurrentIndex(next((i for i,item in enumerate(items) if item['name']=='G8毛'),0))
        layout.addWidget(choices)
        layout.addWidget(label('Native Dot ID (unchanged; not room/thread)',True))
        native_id=QLineEdit(dialog);native_id.setReadOnly(True);native_id.setObjectName('dot_native_identifier')
        layout.addWidget(native_id)
        copy_id=button('Copy native ID',lambda:QApplication.clipboard().setText(native_id.text()),'copy_dot_identifier')
        layout.addWidget(copy_id)
        actions=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel,dialog)
        commit=actions.button(QDialogButtonBox.Ok);commit.setText('Use G8毛');commit.setObjectName('commit_dot_selection')
        actions.button(QDialogButtonBox.Cancel).setText('Keep disconnected')
        def availability():
            item=choices.currentData() or {};approved=item.get('name')=='G8毛'
            commit.setEnabled(approved)
            value=item.get('id','') if approved else ''
            native_id.setText(value if isinstance(value,str) else '')
            copy_id.setEnabled(approved and isinstance(value,str) and bool(value))
        choices.currentIndexChanged.connect(availability);availability()
        actions.accepted.connect(dialog.accept);actions.rejected.connect(dialog.reject);layout.addWidget(actions)
        if dialog.exec()!=QDialog.Accepted:return None
        return choices.currentData()

    def bind_dot_task(self):
        adapter=self.window.core.adapters['dot']
        self.window.run(lambda:self.window.core.resume_session('dot',adapter.target),lambda _:self.window.reload_context(),'dot')

    def read_dot(self, older=False):
        if self.connection_state != 'Connected' or self.monitor: return
        if self.window.orchestrator and self.window.orchestrator.active:
            self.window.show_error('自動協作進行中，請先結束這一輪再手動讀取持續對話。'); return
        if not self.dot_consent('messages'): return
        def loaded(_):
            if older: self.dot_visible_limit += 32
            self.window.reload_context()
        self.window.run(lambda: self.window.core.read_dot_conversation(older), loaded, agent='dot')

    def update_capabilities(self, value):
        self.capabilities = asdict(value)
        cap = self.capabilities
        old = self.model.currentData()
        self.model.blockSignals(True)
        self.model.clear()
        models = cap.get("models", []) if cap.get("supports_model_selection") else []
        for item in models:
            if isinstance(item, str):
                self.model.addItem(item, item)
            else:
                name = item.get("displayName") or item.get("display_name") or item.get("name") or item.get("model") or item.get("id", "")
                self.model.addItem(name, item.get("id") or item.get("model") or item.get("value") or name)
        if not models:
            self.model.addItem("由 ChatGPT 管理" if self.agent == "dot" else ("尚未偵測" if "尚未偵測" in self.capability_status("supports_model_selection") else "模型清單暫不可用" if cap.get("supports_model_selection") else "後端預設 · 無模型選擇"), None)
        selected = self.model.findData(old)
        if selected < 0:
            saved = self.window.core.get_setting("agent." + self.agent, {}) or {}
            selected = self.model.findData(saved.get("default_model"))
        if selected >= 0:
            self.model.setCurrentIndex(selected)
        self.model.blockSignals(False)
        self.model.setToolTip("模型 · " + self.capability_status("supports_model_selection") + " · 下次請求生效")
        self.model.setEnabled(bool(models) and not self.monitor)
        self.model_changed()
        if cap.get("detail"):
            self.notice.setText(compact(cap["detail"], 115))
            self.notice.setToolTip(str(cap["detail"]))
        self.update_controls()

    def model_changed(self):
        choice_required = self._effort_invalid
        self._effort_error = ""
        selected = self.model.currentData()
        efforts = self.capabilities.get("efforts", [])
        for model in self.capabilities.get("models", []):
            if isinstance(model, dict) and selected in (model.get("id"), model.get("model"), model.get("value")):
                efforts = model.get("supportedReasoningEfforts", model.get("supported_efforts", model.get("supportedEffortLevels", efforts)))
        if isinstance(efforts, dict):
            efforts = efforts.get(selected, [])
        if self.capabilities.get("supports_effort"):
            try:
                # Both official adapters expose this from handshake metadata;
                # selected-model efforts can differ from the default model.
                efforts = self.window.core.list_efforts(self.agent, selected)
            except Exception as exc:
                self._effort_error = str(exc)
                efforts = []
        old_effort = self.effort.currentData()
        signals_blocked = self.effort.blockSignals(True)
        self.effort.clear()
        if self.capabilities.get("supports_effort"):
            for item in efforts:
                value = item if isinstance(item, str) else item.get("reasoningEffort") or item.get("effort") or item.get("id") or item.get("value")
                if value:
                    self.effort.addItem(str(value), value)
        available = self.effort.count() > 0
        if not available:
            self.effort.addItem("由 ChatGPT 管理" if self.agent == "dot" else ("尚未偵測" if "尚未偵測" in self.capability_status("supports_effort") else "偵測失敗" if self._effort_error else "選項暫不可用 · 後端預設" if self.capabilities.get("supports_effort") else "不支援 · 後端預設"), None)
        else:
            saved = self.window.core.get_setting("agent." + self.agent, {}) or {}
            index = self.effort.findData(old_effort if old_effort is not None else saved.get("default_effort"))
            if choice_required or (index < 0 and old_effort is not None):
                self.effort.insertItem(0, "請選擇支援的強度…", None)
                self.effort.setCurrentIndex(0)
                self._effort_invalid = True
            elif index >= 0:
                self.effort.setCurrentIndex(index)
        self.effort.blockSignals(signals_blocked)
        self.effort.setToolTip("思考強度 · " + self.capability_status("supports_effort") + (" · 偵測失敗：" + self._effort_error if self._effort_error else "") + (" · 此模型不支援先前的強度；請選擇支援值" if self._effort_invalid else " · 下次請求生效"))
        self.effort.setEnabled(available and not self.monitor)
        self.update_controls()

    def effort_selected(self, index=0):
        # Only a selection outside capability rebuilding/restore chooses a value.
        # The rebuild blocks this signal, so refresh cannot act as user input.
        if self.effort.currentData() is not None:
            self._effort_invalid = False
        self.update_controls()

    def attachment_supported(self):
        probe = getattr(self.window.core,"attachment_capability",None)
        if callable(probe):
            try:
                return bool(probe(self.agent,self.model.currentData()).get('supported'))
            except Exception:
                return False
        return bool(self.capabilities.get('supports_files'))

    def set_state(self, state):
        old_state = self.connection_state
        self.connection_state = state
        self.state.setText(({'Connected':'通道已連接','Busy':'正在傳輸','Connecting':'正在連接'}.get(state)
                            if self.agent == 'dot' else None) or STATE_LABELS.get(state, "狀態待確認（" + state + "）"))
        if self.agent == 'dot': self.state.setToolTip('這是 Workspace 訊息通道狀態，不代表 dot 所有工作的執行狀態')
        self.update_state_style()
        if state in ("Disconnected", "Offline"):
            self.approval_rules.clear()
            if self._dot_follow is not None:
                self.stop_dot_follow()
        if (old_state in ("Connected", "Busy")) != (state in ("Connected", "Busy")):
            self.update_capabilities(self.capabilities)
        self.connect_button.setText("中斷連線" if state in ("Connected", "Busy") else ("重新連線" if state in ("Error", "Offline") else "連線"))
        self.update_controls()
        if hasattr(self.window, "role_tabs"):
            self.window.update_role_tabs()
        if state == 'Error':
            adapter=getattr(self.window.core,'adapters',{}).get(self.agent)
            error=getattr(adapter,'last_error','') if adapter is not None else ''
            if error:
                note = error + (' · ' + self.codex_permission_note() if self.provider == 'codex' else '')
                self.notice.setText(note)
                self.notice.setToolTip(note)

    def update_state_style(self):
        color = (desktop_state_color(self.connection_state, bool(self.pending_approval_events))
                 if self.window.theme_name == 'desktop' else STATE_COLORS.get(self.connection_state, STATE_IDLE))
        self.state.setStyleSheet(f'color: {color};')

    def update_controls(self):
        operating = bool(getattr(self.window, '_agent_operations', {}).get(self.agent))
        run = getattr(self.window, 'orchestrator', None)
        participating = bool(run and run.active and self.agent in run.agents)
        ready = self.connection_state == "Connected" and not self.monitor and not operating and not participating
        busy = self.connection_state == "Busy"
        cap = self.capabilities
        files_supported = self.attachment_supported()
        blocked = self.agent == "dot" and not cap.get("supports_sessions")
        settings = self.window.core.get_setting("agent." + self.agent, {}) or {}
        enabled = settings.get("enabled", True)
        changing = busy or self.connection_state == 'Connecting' or self.monitor or operating or participating or self.agent in self.window._opening_agents
        self.project.setEnabled(not changing)
        self.task.setEnabled(not changing)
        self.new_task_button.setEnabled(not changing and bool(self.window.core.agent_project(self.agent)))
        self.connect_button.setEnabled(enabled and not blocked and not busy and not operating and not participating and not self.monitor and self.connection_state != "Connecting")
        self.send_button.setEnabled(ready and not blocked and not (self.attachments and not files_supported) and not (self._effort_invalid and self.effort.currentData() is None))
        self.send_button.setToolTip("請移除暫存附件或選擇支援的模型" if self.attachments and not files_supported else "請先選擇此模型支援的強度" if self._effort_invalid and self.effort.currentData() is None else "傳送訊息")
        legacy = self.window.core.legacy_local_conversation(self.agent)
        missing = self.window.core.missing_session(self.agent)
        self.send_button.setText('新對話並傳送' if legacy or missing else BUTTON_LABELS['Send'])
        feedback = (f'此對話的紀錄已不存在（{missing[:8]}），請開新對話' if missing else
                    '傳送失敗：' + self.send_error if self.send_error else '')
        if not feedback and legacy:
            name = ROLE_NAMES[legacy['harness']]
            feedback = f'這是舊的 {name} Local 對話。按「新對話並傳送」會建立 Hermes 對話，舊紀錄保留。'
        self.send_feedback.setText(feedback)
        self.send_feedback.setVisible(bool(feedback))
        self.input.setReadOnly(self.monitor or blocked or participating)
        self.stop_button.setEnabled(busy and cap.get("supports_cancel", False))
        self.new_button.setEnabled(ready and cap.get("supports_sessions", False) and cap.get('supports_create_session') is not False)
        self.resume_button.setEnabled(ready and cap.get("supports_sessions", False) and bool(self.session.currentData()))
        self.rename_button.setEnabled(bool(self.session.currentData()) and not self.monitor)
        self.session_details.setEnabled(bool(self.session.currentData()))
        display = self.selected_session_display()
        self.session.setToolTip(display['details'] if display else '選擇對話；ID 保留在詳細資訊')
        self.discover_button.setEnabled(ready and cap.get("supports_sessions", False) and self.agent != 'dot')
        for action, control in self.session_actions.values():
            action.setEnabled(control.isEnabled())
        if self.agent == 'dot':
            self.connect_button.setEnabled(self.connect_button.isEnabled() and not self.monitor)
            self.dot_select.setEnabled(enabled and not self.monitor and self.connection_state not in ('Busy','Connected','Connecting'))
            self.dot_refresh.setEnabled(ready)
            self.dot_refresh_inline.setEnabled(ready)
            self.dot_older.setEnabled(ready)
            self.dot_bind.setEnabled(ready and bool(self.window.core.agent_task('dot')))
            self.stop_button.hide()
            self.new_button.setToolTip('此連接器不會建立新的 dot 對話')
            adapter=self.window.core.adapters.get('dot')
            stamp=getattr(adapter,'last_read_at','')
            if self.connection_state != 'Error':
                self.notice.setText(self._dot_status_note or ('持續對話 · 已載入最近訊息，可讀取更早內容' if stamp else '持續對話 · 連接後載入最近訊息'))
            self.notice.setToolTip('非官方訊息連接器。畫面顯示最近 '+str(self.dot_visible_limit)+' 則以內的已載入訊息，可按載入更早訊息。快照可能不完整。最後成功讀取：'+(stamp or '尚未讀取'))
            if self.window.orchestrator and self.window.orchestrator.active:
                self.send_button.setEnabled(False);self.dot_refresh.setEnabled(False);self.dot_refresh_inline.setEnabled(False);self.dot_older.setEnabled(False)
        self.attach_button.setVisible(files_supported)
        self.attach_button.setEnabled(ready and files_supported)
        self.input.setAcceptDrops(files_supported and not self.monitor)
        self.pending_review.setEnabled(bool(cap.get("supports_approval")) and not self.monitor)
        self.approval_button.setText({"ask": "每次都問", "edits": "自動核准編輯", "all": "自動核准全部"}[self.window.approval_mode(self.agent)])
        self.approval_button.setEnabled(self.provider != 'local' and not self.monitor)
        for card in self.approvals.values():
            for control in card.approval_actions:
                control.setEnabled(bool(cap.get('supports_approval')) and not self.monitor and not card.historical and not card.approval_resolved)
        if blocked:
            if self.connection_state != 'Error':
                self.state.setText("受阻")
                self.notice.setText("請先選擇 G8毛 · 非官方整合 · 僅手動操作")
                self.notice.setToolTip(cap.get("detail") or "Dot bridge unavailable. History remains readable.")
            self.input.setPlaceholderText("請先選擇 G8毛。非官方整合；手動重新整理，無串流。")
        elif not enabled:
            self.notice.setText("此角色已在設定中停用")
        elif self.provider == 'local' and self.connection_state in ('Disconnected', 'Offline'):
            self.notice.setText("Hermes · 請按「連線」檢查 CLI；工具權限由 Hermes 管理")
            self.notice.setToolTip(self.notice.text())
        elif self.agent == 'dot':
            self.input.setPlaceholderText("傳送訊息給 G8毛，繼續原本的對話…")
        if self.provider == 'codex' and enabled:
            permission_note = self.codex_permission_note()
            detail = compact(cap.get('detail') or '能力尚未偵測', 115)
            self.notice.setText(permission_note + ' · ' + detail)
            self.notice.setToolTip(str(cap.get('detail') or '') + '\n' + permission_note)
        if self.agent == 'dot' and self.connection_state == 'Error':
            error=getattr(self.window.core.adapters.get('dot'),'last_error','')
            if error: self.notice.setText(error);self.notice.setToolTip(error)

    def codex_permission_note(self):
        adapter = self.window.core.adapters.get(self.agent)
        # Disconnected or newly selected projects must not display the previous thread's permissions.
        current = getattr(adapter, 'session_id', '') and getattr(adapter, '_session_ready', False)
        permissions = (getattr(adapter, '_permission_state', {}) or {}) if current else {}
        sandbox = (permissions.get('sandbox') or {}).get('type')
        sandbox = {'readOnly': 'read-only', 'workspaceWrite': 'workspace-write',
                   'dangerFullAccess': 'danger-full-access'}.get(sandbox, sandbox)
        return '目前 thread · 沙箱：%s · 核准：%s' % (
            sandbox or '尚未取得', permissions.get('approvalPolicy') or '尚未取得')

    def set_monitor(self, monitor):
        self.monitor = monitor
        self.update_capabilities(self.capabilities)

    def refresh_sessions(self, sessions, active=None):
        selected = active or self.session.currentData()
        self._session_rows = local_session_displays(self.window.core, self.agent, sessions)
        current = next((d for r, d in self._session_rows if d['id'] == active), None)
        self.current_session_label.setText('綁定對話：' + (current['label'] if current else '尚未建立或開啟'))
        self.current_session_label.setToolTip(current['details'] if current else '')
        self._fill_sessions(selected)

    def _fill_sessions(self, selected=None):
        query = self.session_search.text().casefold().strip()
        self.session.blockSignals(True)
        self.session.clear()
        self.session.addItem("選擇對話…", None)
        for row, display in getattr(self, '_session_rows', []):
            if query and query not in (display['label'] + display['cwd']).casefold(): continue
            self.session.addItem(display['label'], display['id'])
            self.session.setItemData(self.session.count()-1, display['details'], Qt.ToolTipRole)
        index = self.session.findData(selected)
        self.session.setCurrentIndex(index if index >= 0 else 0)
        self.session.blockSignals(False)
        self.session.currentIndexChanged.connect(self.update_controls) if not getattr(self, "_session_connected", False) else None
        self._session_connected = True
        self.update_controls()
        self.session_details.setEnabled(bool(self.session.currentData()))

    def filter_sessions(self):
        self._fill_sessions(self.session.currentData())

    def selected_session_display(self):
        sid = self.session.currentData()
        return next((display for row, display in getattr(self, '_session_rows', []) if display['id'] == sid), None)

    def show_session_details(self):
        display = self.selected_session_display()
        if display: SessionDetailsDialog(display, self).exec()

    def show_project_details(self):
        self.window.show_detail(self.window.role_names[self.agent] + ' · 專案資訊', {
            'project': self.window.core.agent_project(self.agent) or {},
            'working_directory': self.cwd_label.text(),
            'git_status': self.branch_label.text(),
        })

    def show_session_history(self):
        SessionHistoryDialog(self.window, self.agent).exec()

    def new_session(self):
        if not self.new_button.isEnabled() or not self.window.confirm_agent_context_change(self.agent): return
        self.window.run(lambda: self.window.core.prepare_conversation(self.agent, fresh=True),
                        lambda _: self.window.reload_context(), self.agent)

    def refresh_projects(self):
        core = self.window.core
        project, task = core.agent_project(self.agent) or {}, core.agent_task(self.agent) or {}
        projects = core.list_projects()
        for combo in (self.project, self.task):
            combo.blockSignals(True)
            combo.clear()
        self.project.addItem("選擇此角色的專案…", None)
        for row in projects:
            self.project.addItem(project_label(row, projects), row['id'])
        self.project.setCurrentIndex(max(0, self.project.findData(project.get('id'))))
        self.task.addItem("選擇此角色的任務…", None)
        if project:
            for row in core.list_tasks(project_id=project['id']):
                self.task.addItem(task_label(row, projects), row['id'])
        self.task.setCurrentIndex(max(0, self.task.findData(task.get('id'))))
        for combo in (self.project, self.task): combo.blockSignals(False)
        title = (project.get('name') or '選擇 Project') + ' › ' + (task.get('title') or '新對話')
        self.context_button.setText('專案與對話…')
        self.context_button.setToolTip(title + ('\n僅供 Workspace 交接使用；不會切換或建立 dot 對話' if self.agent=='dot' else '\n只切換此角色的專案、任務與對話'))

    def project_selected(self, *_):
        pid = self.project.currentData()
        current = (self.window.core.agent_project(self.agent) or {}).get('id')
        if pid and pid != current and not self.window._loading:
            if self.window.confirm_agent_context_change(self.agent):
                self.window.run(lambda: self.window.core.select_agent_project(self.agent, pid),
                                lambda _: self.window.reload_context(), self.agent)
            else: self.refresh_projects()

    def task_selected(self, *_):
        tid = self.task.currentData()
        current = (self.window.core.agent_task(self.agent) or {}).get('id')
        if tid and tid != current and not self.window._loading:
            if self.window.confirm_agent_context_change(self.agent):
                self.window.run(lambda: self.window.core.select_agent_task(self.agent, tid),
                                lambda _: self.window.reload_context(), self.agent)
            else: self.refresh_projects()

    def new_task(self):
        if not self.window.confirm_agent_context_change(self.agent): return
        title, ok = QInputDialog.getText(self, '新增此角色的任務', '任務名稱')
        if ok and title.strip():
            self.window.run(lambda: self.window.core.create_agent_task(self.agent, title.strip()),
                            lambda _: self.window.reload_context(), self.agent)

    def resume_session(self):
        sid = self.session.currentData()
        if sid and self.resume_button.isEnabled() and self.window.confirm_agent_context_change(self.agent):
            self.window.run(lambda: self.window.core.open_saved_conversation(self.agent, sid), lambda _: self.window.reload_context(), self.agent)

    def rename_session(self):
        sid = self.session.currentData()
        if not sid:
            return
        display = self.selected_session_display() or {}
        title, ok = QInputDialog.getText(self, "Rename workspace session", "Name", text=display.get('title', ''))
        if ok and title.strip():
            self.window.run(lambda: self.window.core.rename_session(self.agent, sid, title.strip()), lambda _: self.window.reload_context(), self.agent)

    def discover_sessions(self):
        if not self.discover_button.isEnabled():
            return
        dialog = NativeSessionDialog(self.window, self.agent)
        dialog.load()
        if dialog.exec() == QDialog.Accepted:
            self.window.refresh_agent(self.agent)

    def add_attachments(self, paths):
        if not self.attachment_supported():
            self.window.show_error("This backend does not support attachments.")
            return
        self.attachments.extend(path for path in paths if path and path not in self.attachments)
        self.attachment_label.setText("附件：" + ", ".join(Path(path).name for path in self.attachments))
        self.attachment_label.setVisible(bool(self.attachments))
        self.clear_attach_button.setVisible(bool(self.attachments))

    def attach(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach files supported by this backend")
        self.add_attachments(paths)

    def clear_attachments(self):
        self.attachments = []
        self.attachment_label.hide()
        self.clear_attach_button.hide()
        self.update_controls()

    def send(self):
        content = self.input.toPlainText()
        if not content.strip() or not self.send_button.isEnabled():
            return
        model, effort, attachments = self.model.currentData(), self.effort.currentData(), list(self.attachments)
        legacy = self.window.core.legacy_local_conversation(self.agent)
        missing = self.window.core.missing_session(self.agent)
        if self.agent == 'dot':
            if self.window.orchestrator and self.window.orchestrator.active:
                self.window.show_error('請先結束自動協作，再傳送持續對話訊息。');return
            if not self.dot_consent('send'): return
        self.send_error = ''
        self.set_state("Busy")
        self.input.clear()
        self.clear_attachments()
        def failed(message):
            from ..security import sanitize
            retained_text = self.input.toPlainText() or content
            retained_files = list(dict.fromkeys(self.attachments + attachments))
            if self.agent != 'dot': self.window.reload_context()
            self.input.setPlainText(retained_text)
            self.clear_attachments()
            if retained_files: self.add_attachments(retained_files)
            self.send_error = str(sanitize(str(message)))
            self.update_controls()
            if self.agent == 'dot':
                # A network timeout does not tell whether G8毛 received it; sending again may duplicate.
                self.window.footer.setText("傳送沒有得到確認：訊息可能已經送出。請先按「重新整理」確認，再決定要不要重送。")
        def dispatch():
            if self.agent == 'dot': return self.window.core.send_dot_conversation(content)
            if self.window.core.legacy_local_conversation(self.agent) != legacy:
                raise RuntimeError('對話已變更，請確認目前對話後再傳送')
            self.window.core.prepare_conversation(self.agent, fresh=bool(legacy or missing))
            return self.window.core.send_message(self.agent, content, model=model, effort=effort, attachments=attachments or None)
        def sent(_):
            if self.agent == 'dot': self.follow_dot_replies()
            else:
                # Typing during preparation belongs to the newly opened conversation.
                next_draft, next_files = self.input.toPlainText(), list(self.attachments)
                self.window.reload_context()
                self.input.setPlainText(next_draft)
                self.clear_attachments()
                if next_files: self.add_attachments(next_files)
        self.window.run(dispatch,
                        sent, agent=self.agent, on_error=failed)

    def _dot_replies(self):
        return tuple((m["id"], len(str(m["content"]))) for m in self.window.core.dot_conversation_messages() if m.get("role") == "assistant")

    def follow_dot_replies(self):
        """After a consented send, read G8毛 for its reply for a few minutes so the answer shows up here."""
        adapter = self.window.core.adapters.get("dot")
        run = self.window.orchestrator
        task = self.window.core.agent_task(self.agent) or {}
        if not hasattr(adapter, "grant_run") or (run and run.active) or not getattr(adapter, "target", None):
            return
        try:
            adapter.grant_run(45)
        except Exception:
            return
        self._dot_follow = {"until": time.monotonic() + 300, "baseline": self._dot_replies(), "seen": None, "stable": 0, "target": adapter.target}
        self._dot_timer.start(8000)
        self._dot_status_note="已送出 · 正在讀取回覆（最多 5 分鐘）"
        self.notice.setText("已送出 · 正在自動讀取 G8毛 的回覆（最多 5 分鐘）")

    def stop_dot_follow(self, note=""):
        if self._dot_follow is None:
            return
        self._dot_follow = None
        self._dot_timer.stop()
        adapter, run = self.window.core.adapters.get("dot"), self.window.orchestrator
        if hasattr(adapter, "revoke_run") and not (run and run.active):
            adapter.revoke_run()
        if note:
            self._dot_status_note=note
            self.notice.setText(note)
            self.notice.setToolTip(note)

    def _dot_follow_tick(self):
        follow = self._dot_follow
        if follow is None:
            return self._dot_timer.stop()
        if self.window.orchestrator and self.window.orchestrator.active:
            return self.stop_dot_follow()
        if self.connection_state == "Busy":
            return
        if self.monitor or self.connection_state != "Connected" or getattr(self.window.core.adapters.get("dot"),"target",None) != follow["target"]:
            return self.stop_dot_follow()
        if time.monotonic() > follow["until"]:
            return self.stop_dot_follow("已停止自動讀取 · 需要時請按「重新整理」")
        def done(_):
            if self._dot_follow is not follow:
                return
            current = self._dot_replies()
            if current != follow["baseline"]:
                # G8毛 may answer in several messages; it is finished once two reads in a row match.
                follow["stable"] = follow["stable"] + 1 if current == follow["seen"] else 0
                follow["seen"] = current
                if follow["stable"] >= 2:
                    self.stop_dot_follow("已讀取新回覆 · 尚無原生完成訊號")
        self.window.run(lambda: self.window.core.read_dot_conversation(False), done, agent="dot",
                        on_error=lambda _: self.stop_dot_follow("讀取回覆失敗 · 請按「重新整理」再試"))

    def stop(self):
        self.window.run(lambda: self.window.core.stop(self.agent), agent=self.agent)

    def clear_conversation(self):
        self.cards.clear()
        self.approvals.clear()
        self.pending_approval_events.clear()
        self.hidden_count = 0
        self.pending_review.hide()
        while self.transcript_layout.count() > 1:
            item = self.transcript_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        dot_empty="這一頁沒有可顯示的文字訊息；可嘗試載入更早訊息。" if getattr(self.window.core.adapters.get("dot"),"last_read_at","") else "尚未載入 G8毛 的對話。連接後會讀取最近訊息。"
        self.empty = label(dot_empty if self.agent=="dot" else "從這裡開始對話\n\n先選擇專案與 session，再連線討論。\n需要協作時，選擇隊員並啟動派工。", True)
        self.empty.setObjectName('empty_conversation')
        self.empty.setAlignment(Qt.AlignCenter)
        self.transcript_layout.insertWidget(0, self.empty)
        self.set_hidden_count(0)

    def make_older_button(self):
        older = QPushButton()
        older.setObjectName("older_messages")
        older.setCursor(Qt.PointingHandCursor)
        older.clicked.connect(self.show_more_messages)
        older.hide()
        return older

    def set_hidden_count(self, count):
        self.hidden_count = max(0, int(count))
        self.older_button.setText(f"已收合較早的 {self.hidden_count} 則 · 顯示更多")
        self.older_button.setVisible(self.hidden_count > 0)

    def show_more_messages(self):
        state = self.capture_view_state()
        self.visible_limit += 300
        self.window.rebuild_panel(self.agent, state)
        self.restore_view_state(state)

    def prune_transcript(self):
        if self.agent == "dot":
            return
        layout = self.transcript_layout
        protected = {id(self.approvals[request_id]) for request_id in self.pending_approval_events if request_id in self.approvals}

        def keep(widget):
            if isinstance(widget, ActivityGroup):
                return any(id(card) in protected for card in widget.cards)
            return id(widget) in protected
        # Layout holds: empty label, cards..., trailing stretch.
        while layout.count() - 2 > self.visible_limit:
            victim = None
            for index in range(1, layout.count() - 1):
                widget = layout.itemAt(index).widget()
                if widget is not None and not keep(widget):
                    victim = index
                    break
            if victim is None:
                break
            widget = layout.takeAt(victim).widget()
            if isinstance(widget, MessageCard):
                for mid in [key for key, card in self.cards.items() if card is widget]:
                    del self.cards[mid]
            else:
                gone = {id(card) for card in widget.cards} if isinstance(widget, ActivityGroup) else {id(widget)}
                for request_id in [key for key, card in self.approvals.items() if id(card) in gone]:
                    del self.approvals[request_id]
            widget.hide()
            widget.deleteLater()
            self.set_hidden_count(self.hidden_count + 1)

    def add_message(self, message):
        mid = identifier(message)
        if mid in self.cards:
            self.cards[mid].message.update(message)
            self.cards[mid].update_content(message.get("content", ""))
            return
        self.empty.hide()
        card = MessageCard(message, self)
        self.cards[mid] = card
        self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, card)
        card.show()
        self.prune_transcript()
        self.scroll_bottom()

    def add_event(self, event, historical=False):
        event = {**(event.get("payload") or {}), **event}
        self.empty.hide()
        card = EventCard(event, self.window, historical)
        approval = event.get("type") in APPROVAL_EVENTS
        request_id = event.get("request_id") or (event.get("payload") or {}).get("request_id")
        automatic = approval and not historical and bool(request_id) and self.window.auto_approve(self.agent, event, request_id)
        if approval and (historical or automatic):
            # Already answered: it belongs with the rest of the tool activity, not in the user's way.
            card.resolve_approval()
            card.toggle.setChecked(False)
            if automatic:
                card.toggle.setText("已自動核准  " + card.toggle.text().split("  ", 1)[-1])
        if approval and not (historical or automatic):
            self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, card)
            # A live insertion must be exposed before it can receive pointer input.
            # Layout geometry is still allowed to settle in the normal event loop.
            card.show()
        else:
            # Tool activity folds into the group that ends the transcript, or starts a new one.
            last = self.transcript_layout.itemAt(self.transcript_layout.count() - 2)
            group = last.widget() if last else None
            if not isinstance(group, ActivityGroup):
                group = ActivityGroup()
                self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, group)
                group.show()
            group.add(card)
        if approval:
            if request_id:
                self.approvals[request_id] = card
                if not historical and not automatic:
                    self.pending_approval_events[request_id] = event
                    self.pending_review.show()
                    self.window.update_role_tabs()
        self.prune_transcript()
        self.scroll_bottom()

    def review_pending_approval(self):
        if self.pending_approval_events:
            event = next(iter(self.pending_approval_events.values()))
            self.window.approve(event, True)

    def resolve_pending_approval(self, request_id):
        card = self.approvals.get(request_id)
        if card:
            card.resolve_approval()
        self.pending_approval_events.pop(request_id, None)
        self.pending_review.setVisible(bool(self.pending_approval_events))
        self.window.update_role_tabs()

    def scroll_bottom(self):
        if self._restoring_view:
            return
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - bar.value() < 100:
            QTimer.singleShot(0, self, lambda: bar.setValue(bar.maximum()) if not self._restoring_view else None)
        else:
            self.new_messages.show()
