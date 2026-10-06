"""Native desktop workspace. All backend interaction passes through WorkspaceCore.

Qt workers isolate backend handshakes and requests from the GUI thread. This module
never spawns a shell, reads credentials, or creates an agent session on startup.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from .presentation import (session_identity, session_display, local_session_displays,
                           project_label, task_label, compact)
from .theme import EVENT_COLOR, HEADING_COLOR, STATE_COLORS, STATE_IDLE, build_style, metal_palette

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QUrl, QByteArray
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton, QTreeWidget, QTabBar,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

AGENTS = ("claude", "dot", "codex", "local")
STATUSES = ("NEW", "PLANNING", "REVIEWING", "READY", "IMPLEMENTING", "VERIFYING",
            "WAITING_USER", "BLOCKED", "DONE", "FAILED", "CANCELLED")
ROLE_NAMES = {"claude": "Claude", "dot": "G8毛", "codex": "Codex", "local": "Local LLM"}
ROLE_LABELS = {"claude": "主審", "dot": "轉接／複核", "codex": "實作", "local": "本地模型"}
STATE_LABELS = {"Disconnected": "未連線", "Connected": "已連線", "Busy": "處理中", "Connecting": "連線中",
                "Error": "錯誤", "Blocked": "受阻", "Offline": "離線", "Stopping": "停止中", "Interrupted": "已中斷"}
STATUS_LABELS = dict(zip(STATUSES, ("新任務", "規劃中", "主審中", "可實作", "實作中", "驗證中",
                                  "等待使用者", "受阻", "已完成", "失敗", "已取消")))
BUTTON_LABELS = {
    "Connect": "連線", "Send": "傳送", "Stop": "停止", "Attach": "附件", "Clear": "清除附件",
    "New": "新增", "Resume": "恢復", "Rename": "重新命名", "Discover…": "探索原生對話…",
    "Refresh": "重新整理", "Older page": "較早訊息", "Settings…": "設定…", "Work details": "工作詳情",
    "Three panes": "並排", "New messages ↓": "新訊息 ↓", "Pending backend approval · Review…": "等待核准 · 檢視…",
    "Select G8毛…": "選擇 G8毛…", "Copy": "複製", "Close": "關閉", "Deny": "拒絕", "Approve…": "核准…",
    "Open Diff / Tests / Artifacts…": "檢視差異／測試／附件…", "Open full timeline": "完整時間線",
}


def plain(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, default=str)


def asdict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return vars(value) if hasattr(value, "__dict__") else {}


def identifier(item: dict) -> str:
    return str(item.get("id") or item.get("session_id") or item.get("task_id") or item.get("project_id") or "")


def button(text, callback=None, name=None):
    result = QPushButton(BUTTON_LABELS.get(text, text))
    if name:
        result.setObjectName(name)
    if callback:
        result.clicked.connect(callback)
    return result


def label(text, muted=False):
    result = QLabel(text)
    result.setTextFormat(Qt.PlainText)
    if muted:
        result.setObjectName("muted")
    result.setWordWrap(True)
    return result


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.result.emit(self.operation())
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class FocusLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        event.accept()


class PromptEdit(QPlainTextEdit):
    """Ctrl+Enter sends only after the input method has committed its text."""
    _ime_preedit = False

    def inputMethodEvent(self, event):
        self._ime_preedit = bool(event.preeditString())
        super().inputMethodEvent(event)

    submit = Signal()
    files_dropped = Signal(list)

    def keyPressEvent(self, event):
        if not self._ime_preedit and event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.submit.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_dropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class DetailDialog(QDialog):
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(870, 620)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(plain(content))
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 10))
        layout.addWidget(self.text)
        actions = QHBoxLayout()
        actions.addWidget(button("Copy", lambda: QApplication.clipboard().setText(self.text.toPlainText())))
        actions.addStretch()
        actions.addWidget(button("Close", self.accept))
        layout.addLayout(actions)


class MessageCard(QFrame):
    """Plain response content plus explicit actions; source text is never rewritten."""
    def __init__(self, message, panel):
        super().__init__()
        self.setObjectName("message")
        self.message = dict(message)
        self.panel = panel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 8)
        header = QHBoxLayout()
        role = message.get("role", "assistant")
        self.heading = label(role.upper())
        self.heading.setStyleSheet(f"font-weight: 650; color: {HEADING_COLOR}; font-size: 12px;")
        header.addWidget(self.heading)
        stamp = str(message.get("timestamp", ""))
        header.addWidget(label(stamp[11:19] if "T" in stamp else stamp, True))
        header.addStretch()
        menu_button = QToolButton()
        menu_button.setText("⋯")
        menu_button.setToolTip("Copy, raw event, and handoff")
        menu_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(menu_button)
        menu.addAction("Copy", lambda: self.copy(False))
        menu.addAction("複製含中繼資料", lambda: self.copy(True))
        menu.addAction("檢視原始事件", lambda: panel.window.open_raw(self.message))
        if role == "assistant":
            menu.addSeparator()
            for target in AGENTS:
                if target != panel.agent:
                    menu.addAction(f"轉交給 {ROLE_NAMES[target]}…", lambda checked=False, target=target: panel.window.forward(self.message, target))
        menu_button.setMenu(menu)
        header.addWidget(menu_button)
        layout.addLayout(header)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setFrameShape(QFrame.NoFrame)
        self.body.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 15px;")
        self.body.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.body)
        if role == "assistant":
            forward = QHBoxLayout()
            forward.addStretch()
            self.forward_button = QToolButton()
            self.forward_button.setText("轉交 ▾")
            self.forward_button.setPopupMode(QToolButton.InstantPopup)
            targets = QMenu(self.forward_button)
            for target in AGENTS:
                if target != panel.agent:
                    targets.addAction(ROLE_NAMES[target], lambda checked=False, target=target: panel.window.forward(self.message, target))
            self.forward_button.setMenu(targets)
            forward.addWidget(self.forward_button)
            layout.addLayout(forward)
        self.update_content(message.get("content", ""))

    def update_content(self, content):
        self.message["content"] = content
        cursor = self.body.textCursor()
        start, end = cursor.anchor(), cursor.position()
        scroll = self.body.verticalScrollBar().value()
        self.body.setPlainText(plain(content))
        cursor.setPosition(min(start, len(plain(content))))
        cursor.setPosition(min(end, len(plain(content))), QTextCursor.KeepAnchor)
        self.body.setTextCursor(cursor)
        self.body.verticalScrollBar().setValue(scroll)
        lines = max(1, sum(max(1, (len(line) + 51) // 52) for line in plain(content).splitlines()))
        self.body.setFixedHeight(min(420, 32 + lines * 23))

    def copy(self, metadata=False):
        content = plain(self.message.get("content", ""))
        if metadata:
            content = plain({k: v for k, v in self.message.items() if k != "content"}) + "\n\n" + content
        QApplication.clipboard().setText(content)


class EventCard(QFrame):
    def __init__(self, event, window, historical=False):
        super().__init__()
        event = {**(event.get("payload") or {}), **event}
        self.setObjectName("event")
        self.event_key = identifier(event) or str(event.get("request_id") or event.get("timestamp") or plain(event))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 4)
        kind = event.get("type", "event")
        summary = event.get("command") or event.get("tool") or event.get("summary") or event.get("name") or event.get("status", "")
        self.toggle = QToolButton()
        self.toggle.setText(f"{kind.replace('_', ' ').upper()}  {str(summary)[:100]}")
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toggle.setCheckable(True)
        self.toggle.setStyleSheet(f"text-align: left; border: none; background: transparent; color: {EVENT_COLOR};")
        layout.addWidget(self.toggle)
        detail = dict(event)
        if "output" in detail and (detail.get("output_stream") == "combined" or not ("stdout" in detail or "stderr" in detail)):
            detail["output_stream"] = "Combined output supplied by backend; stdout/stderr separation unavailable."
        self.body = QPlainTextEdit(plain(detail))
        self.body.setReadOnly(True)
        self.body.setFont(QFont("Consolas", 9))
        self.body.setMaximumHeight(300)
        self.body.hide()
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self.set_expanded)
        self.approval_actions = []
        self.historical = historical
        self.approval_resolved = False
        if kind in ("approval", "approval_request", "tool_approval"):
            actions = QHBoxLayout()
            actions.addWidget(label("Backend approval required. Review the request above.", True))
            self.approval_actions = [button("Deny", lambda: window.approve(event, False)), button("Approve…", lambda: window.approve(event, True))]
            for control in self.approval_actions:
                control.setEnabled(not historical and window.mode.currentData() != 'Monitor' and bool(window.core.capabilities(event.get("agent", "")).get("supports_approval")))
                actions.addWidget(control)
            layout.addLayout(actions)
            self.toggle.setChecked(True)

    def set_expanded(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.updateGeometry()

    def resolve_approval(self):
        self.approval_resolved = True
        for control in self.approval_actions:
            control.setEnabled(False)


class AgentPanel(QFrame):
    def __init__(self, agent, window):
        super().__init__()
        self.agent, self.window = agent, window
        self.capabilities = {}
        self.cards = {}
        self.approvals = {}
        self.pending_approval_events = {}
        self.attachments = []
        self.connection_state = "Disconnected"
        self.monitor = False
        self._effort_invalid = False
        self._effort_error = ""
        self._restoring_view = False
        self.setObjectName("panel")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = FocusLabel(ROLE_NAMES[agent])
        self.title.setObjectName("agentTitle")
        self.title.setToolTip("按兩下以專注此角色")
        self.title.double_clicked.connect(lambda: window.focus_agent(agent))
        titles.addWidget(self.title)
        titles.addWidget(label(ROLE_LABELS[agent], True))
        header.addLayout(titles)
        header.addStretch()
        self.state = label("未連線")
        self.state.setObjectName("status")
        self.state.setWordWrap(False)
        self.state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.state)
        self.connect_button = button("Connect", self.connect_agent, f"connect_{agent}")
        self.connect_button.setAccessibleName(f"Connect {ROLE_NAMES[agent]}")
        header.addWidget(self.connect_button)
        self.more_button = QToolButton()
        self.more_button.setText("⋯")
        self.more_button.setAccessibleName(f"{ROLE_NAMES[agent]} conversation actions")
        self.more_button.setToolTip("對話、歷史、能力、原始事件與日誌")
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        more = QMenu(self.more_button)
        more.addAction("對話…", lambda: window.show_sessions(agent))
        more.addAction("本機歷史…", self.show_session_history)
        if agent == "claude":
            more.addAction("Desktop 專案與對話…", window.show_desktop_sessions)
        more.addAction("能力詳情…", self.show_capabilities)
        more.addSeparator()
        more.addAction("原始事件…", lambda: window.show_agent_events(agent))
        more.addAction("日誌…", lambda: window.open_logs(agent))
        more.addAction("專案檔案", window.open_project)
        self.more_button.setMenu(more)
        header.addWidget(self.more_button)
        layout.addLayout(header)
        self.notice = label("能力尚未偵測 · 請在準備好時連線", True)
        self.notice.setMaximumHeight(38)
        self.notice.setToolTip(self.notice.text())
        layout.addWidget(self.notice)

        # These are the original session actions, moved together to the sidebar.
        # Keeping the same widgets and callbacks retains backend/consent behavior.
        self.session_controls = QWidget()
        session_layout = QVBoxLayout(self.session_controls)
        session_layout.setContentsMargins(0, 8, 0, 0)
        session_layout.setSpacing(8)
        self.session_search = QLineEdit()
        self.session_search.setObjectName(f"session_search_{agent}")
        self.session_search.setPlaceholderText("搜尋已保存的對話…")
        self.session_search.setAccessibleName(f"Search {ROLE_NAMES[agent]} local sessions")
        self.session_search.textChanged.connect(self.filter_sessions)
        session_layout.addWidget(self.session_search)
        self.session = QComboBox()
        self.session.setObjectName(f"session_{agent}")
        self.session.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.session.setMinimumContentsLength(10)
        self.session.setAccessibleName(f"{ROLE_NAMES[agent]} session")
        session_layout.addWidget(self.session)
        self.current_session_label = label("目前對話：尚未建立或恢復", True)
        self.current_session_label.setObjectName(f"current_session_{agent}")
        session_layout.addWidget(self.current_session_label)
        session_buttons = QGridLayout()
        self.session_details = button("詳細 / ID", self.show_session_details, f"session_details_{agent}")
        self.new_button = button("New", self.new_session, f"new_session_{agent}")
        self.resume_button = button("Resume", self.resume_session, f"resume_session_{agent}")
        self.rename_button = button("Rename", self.rename_session, f"rename_session_{agent}")
        self.discover_button = button("Discover…", self.discover_sessions, f"discover_sessions_{agent}")
        self.discover_button.setToolTip("Explicitly list native backend sessions; import metadata without resuming")
        for index, control in enumerate((self.new_button, self.resume_button, self.rename_button, self.session_details)):
            session_buttons.addWidget(control, index // 2, index % 2)
        session_layout.addLayout(session_buttons)
        session_layout.addWidget(self.discover_button)
        if agent == "dot":
            self.dot_select = button("Select G8毛…", self.select_dot, "select_dot")
            self.dot_refresh = button("Refresh", lambda: self.read_dot(False), "refresh_dot")
            self.dot_older = button("Older page", lambda: self.read_dot(True), "older_dot")
            session_layout.addWidget(self.dot_select)
            dot_controls = QHBoxLayout()
            dot_controls.addWidget(self.dot_refresh)
            dot_controls.addWidget(self.dot_older)
            session_layout.addLayout(dot_controls)
            session_layout.addWidget(label("Unofficial adapter · each live action needs your consent. No automatic reads or relay.", True))
        self.cwd_label = label("工作目錄：尚未選擇", True)
        self.cwd_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # A long unbreakable path must not widen the sidebar past its viewport.
        self.cwd_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.branch_label = label("分支：—", True)
        session_layout.addWidget(self.cwd_label)
        session_layout.addWidget(self.branch_label)
        session_layout.addStretch()

        self.pending_review = button("Pending backend approval · Review…", self.review_pending_approval, f"pending_approval_{agent}")
        self.pending_review.setToolTip("A human must review and explicitly confirm this request. New events do not hide this reminder.")
        self.pending_review.hide()
        layout.addWidget(self.pending_review)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName(f"conversation_{agent}")
        self.scroll.setProperty("well", True)
        self.transcript = QWidget()
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(0, 4, 0, 4)
        self.transcript_layout.setSpacing(12)
        self.empty = label("對話將顯示在這裡。\n請在準備好時連線。", True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.transcript_layout.addWidget(self.empty)
        self.transcript_layout.addStretch()
        self.scroll.setWidget(self.transcript)
        layout.addWidget(self.scroll, 1)
        self.new_messages = button("New messages ↓", self.jump_to_latest, f"new_messages_{agent}")
        self.new_messages.hide()
        layout.addWidget(self.new_messages)
        self.input = PromptEdit()
        self.input.setObjectName(f"input_{agent}")
        self.input.setAccessibleName(f"Message {ROLE_NAMES[agent]}")
        self.input.setPlaceholderText(f"傳送訊息給 {ROLE_NAMES[agent]}…  Ctrl+Enter 傳送")
        self.input.setMinimumHeight(82)
        self.input.setMaximumHeight(125)
        self.input.submit.connect(self.send)
        self.input.files_dropped.connect(self.add_attachments)
        layout.addWidget(self.input)
        self.attachment_label = label("", True)
        self.attachment_label.hide()
        layout.addWidget(self.attachment_label)
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model = QComboBox()
        self.model.setObjectName(f"model_{agent}")
        self.model.setAccessibleName(f"{ROLE_NAMES[agent]} 模型")
        self.model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model.setMinimumContentsLength(7)
        self.model.currentIndexChanged.connect(self.model_changed)
        self.effort = QComboBox()
        self.effort.setObjectName(f"effort_{agent}")
        self.effort.setAccessibleName(f"{ROLE_NAMES[agent]} 思考強度")
        self.effort.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.effort.setMinimumContentsLength(6)
        self.effort.currentIndexChanged.connect(self.effort_selected)
        model_row.addWidget(self.model, 3)
        model_row.addWidget(self.effort, 2)
        layout.addLayout(model_row)
        controls = QHBoxLayout()
        self.attach_button = button("Attach", self.attach)
        self.attach_button.setAccessibleName(f"Attach files to {ROLE_NAMES[agent]}")
        self.clear_attach_button = button("Clear", self.clear_attachments)
        self.clear_attach_button.hide()
        controls.addWidget(self.attach_button)
        controls.addWidget(self.clear_attach_button)
        controls.addStretch()
        self.stop_button = button("Stop", self.stop, "stop")
        self.stop_button.setAccessibleName(f"Stop {ROLE_NAMES[agent]}")
        controls.addWidget(self.stop_button)
        self.send_button = button("Send", self.send, "primary")
        self.send_button.setAccessibleName(f"Send to {ROLE_NAMES[agent]}")
        controls.addWidget(self.send_button)
        layout.addLayout(controls)
        self.update_capabilities({})

    def show_capabilities(self):
        self.window.show_detail(f"{ROLE_NAMES[self.agent]} capabilities", {
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
        for index in range(self.transcript_layout.count()):
            widget = self.transcript_layout.itemAt(index).widget()
            if isinstance(widget, EventCard):
                events[widget.event_key] = widget.toggle.isChecked()
        return {
            "draft": self.input.toPlainText(), "draft_cursor": (cursor.anchor(), cursor.position()),
            "attachments": list(self.attachments), "model": self.model.currentData(),
            "effort": self.effort.currentData(), "effort_invalid": self._effort_invalid, "session": self.session.currentData(),
            "session_search": self.session_search.text(), "scroll": self.scroll.verticalScrollBar().value(),
            "selections": selections, "expanded_events": events,
            "pending": dict(self.pending_approval_events),
        }

    def restore_view_state(self, state):
        self._restoring_view = True
        self.input.setPlainText(state.get("draft", ""))
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
        for index in range(self.transcript_layout.count()):
            widget = self.transcript_layout.itemAt(index).widget()
            if isinstance(widget, EventCard) and widget.event_key in state.get("expanded_events", {}):
                widget.toggle.setChecked(state["expanded_events"][widget.event_key])
        self.update_controls()
        def restore_scroll():
            self.scroll.verticalScrollBar().setValue(state.get("scroll", 0))
            self._restoring_view = False
        QTimer.singleShot(0, self, restore_scroll)

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
            if self.agent in ('claude', 'local') and not self.window.core.current_project:
                self.window.require_project(ROLE_NAMES[self.agent] + " 需要先有專案資料夾才能連線。")
                return
            self.set_state("Connecting")
            self.window.run(lambda: self.window.core.connect(self.agent), lambda _: self.window.refresh_agent(self.agent), self.agent)

    def dot_consent(self, action):
        if self.monitor: return False
        from .adapters.dot import DISCLOSURE
        adapter = self.window.core.adapters['dot']
        target = adapter.target_name+' ('+adapter.target+')' if adapter.target else 'Identifier/name enumeration only; select G8毛 next'
        box = QMessageBox(QMessageBox.Question, 'Unofficial Dot — explicit local action', '', QMessageBox.Yes | QMessageBox.No, self)
        box.setTextFormat(Qt.PlainText)
        box.setText(DISCLOSURE+'\nAction: '+action+'\nTarget: '+target+'\nStreaming / server Stop / attachments / New chat: Unsupported.')
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
            self.window.core.set_setting('agent.dot',dict(saved,dot_id=item['id'],dot_name=item['name']))
            self.window.refresh_agent('dot')
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

    def read_dot(self, older=False):
        if self.connection_state != 'Connected' or self.monitor: return
        if not self.window.core.current_task:
            self.window.show_error('Select a task before retrieving messages.'); return
        adapter=self.window.core.adapters['dot']
        if self.window.core.current_task.get('dot_session') != adapter.target:
            self.window.show_error('Resume the selected existing Dot for this task first.'); return
        if not self.dot_consent('messages'): return
        self.window.run(lambda: adapter.refresh_messages(older), agent='dot')

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
        self.state.setText(STATE_LABELS.get(state, "狀態待確認（" + state + "）"))
        color = STATE_COLORS.get(state, STATE_IDLE)
        self.state.setStyleSheet(f"color: {color};")
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
                self.notice.setText(error)
                self.notice.setToolTip(error)

    def update_controls(self):
        ready = self.connection_state == "Connected" and not self.monitor
        busy = self.connection_state == "Busy"
        cap = self.capabilities
        files_supported = self.attachment_supported()
        blocked = self.agent == "dot" and not cap.get("supports_sessions")
        settings = self.window.core.get_setting("agent." + self.agent, {}) or {}
        enabled = settings.get("enabled", True)
        local_missing = self.agent == 'local' and not (str(settings.get('base_url') or '').strip() and str(settings.get('model') or '').strip())
        self.connect_button.setEnabled(enabled and not blocked and not busy and self.connection_state != "Connecting" and (not local_missing or self.connection_state == 'Connected'))
        self.send_button.setEnabled(ready and not blocked and not (self.attachments and not files_supported) and not (self._effort_invalid and self.effort.currentData() is None))
        self.send_button.setToolTip("請移除暫存附件或選擇支援的模型" if self.attachments and not files_supported else "請先選擇此模型支援的強度" if self._effort_invalid and self.effort.currentData() is None else "傳送訊息")
        self.input.setReadOnly(self.monitor or blocked)
        self.stop_button.setEnabled(busy and cap.get("supports_cancel", False))
        self.new_button.setEnabled(ready and cap.get("supports_sessions", False) and cap.get('supports_create_session') is not False)
        self.resume_button.setEnabled(ready and cap.get("supports_sessions", False) and bool(self.session.currentData()))
        self.rename_button.setEnabled(bool(self.session.currentData()) and not self.monitor)
        self.session_details.setEnabled(bool(self.session.currentData()))
        display = self.selected_session_display()
        self.session.setToolTip(display['details'] if display else '選擇對話；ID 保留在詳細資訊')
        self.discover_button.setEnabled(ready and cap.get("supports_sessions", False) and self.agent != 'dot')
        if self.agent == 'dot':
            self.connect_button.setEnabled(self.connect_button.isEnabled() and not self.monitor)
            self.dot_select.setEnabled(enabled and not self.monitor and self.connection_state not in ('Busy','Connected','Connecting'))
            self.dot_refresh.setEnabled(ready)
            self.dot_older.setEnabled(ready)
            self.stop_button.setToolTip('Unsupported: no server cancellation; manual reads are not streaming')
            self.new_button.setToolTip('Unsupported: map an existing Dot identity with Resume')
        self.attach_button.setVisible(files_supported)
        self.attach_button.setEnabled(ready and files_supported)
        self.input.setAcceptDrops(files_supported and not self.monitor)
        self.pending_review.setEnabled(bool(cap.get("supports_approval")) and not self.monitor)
        for card in self.approvals.values():
            for control in card.approval_actions:
                control.setEnabled(bool(cap.get('supports_approval')) and not self.monitor and not card.historical and not card.approval_resolved)
        if local_missing:
            self.notice.setText("請先在設定填入本地端點與模型名稱")
            self.notice.setToolTip(self.notice.text())
        elif blocked:
            if self.connection_state != 'Error':
                self.state.setText("受阻")
                self.notice.setText("請先選擇 G8毛 · 非官方整合 · 僅手動操作")
                self.notice.setToolTip(cap.get("detail") or "Dot bridge unavailable. History remains readable.")
            self.input.setPlaceholderText("請先選擇 G8毛。非官方整合；手動重新整理，無串流。")
        elif not enabled:
            self.notice.setText("此角色已在設定中停用")
        elif self.agent == 'local' and self.connection_state in ('Disconnected', 'Offline'):
            self.notice.setText("本地模型設定已備妥 · 請按「連線」")
            self.notice.setToolTip(self.notice.text())
        elif self.agent == 'dot':
            self.input.setPlaceholderText("手動傳送文字；按重新整理讀取回覆。無串流／伺服器停止。")

    def set_monitor(self, monitor):
        self.monitor = monitor
        self.update_capabilities(self.capabilities)

    def refresh_sessions(self, sessions, active=None):
        selected = active or self.session.currentData()
        self._session_rows = local_session_displays(self.window.core, self.agent, sessions)
        current = next((d for r, d in self._session_rows if d['id'] == active), None)
        self.current_session_label.setText('目前對話：' + (current['label'] if current else '尚未建立或恢復'))
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

    def show_session_history(self):
        SessionHistoryDialog(self.window, self.agent).exec()

    def new_session(self):
        self.window.run(lambda: self.window.core.create_session(self.agent), lambda _: self.window.reload_context(), self.agent)

    def resume_session(self):
        sid = self.session.currentData()
        if sid:
            self.window.run(lambda: self.window.core.resume_session(self.agent, sid), lambda _: self.window.reload_context(), self.agent)

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
        if not self.window.core.current_task:
            self.window.require_task()
            return
        model, effort, attachments = self.model.currentData(), self.effort.currentData(), list(self.attachments)
        if self.agent == 'dot' and not self.dot_consent('send'): return
        self.set_state("Busy")
        self.input.clear()
        self.clear_attachments()
        self.window.run(lambda: self.window.core.send_message(self.agent, content, model=model, effort=effort, attachments=attachments or None), agent=self.agent,
                        on_error=lambda _: self.input.setPlainText(content) if not self.input.toPlainText() else None)

    def stop(self):
        self.window.run(lambda: self.window.core.stop(self.agent), agent=self.agent)

    def clear_conversation(self):
        self.cards.clear()
        self.approvals.clear()
        self.pending_approval_events.clear()
        self.pending_review.hide()
        while self.transcript_layout.count() > 1:
            item = self.transcript_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.empty = label("這個任務尚無訊息", True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.transcript_layout.insertWidget(0, self.empty)

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
        self.scroll_bottom()

    def add_event(self, event, historical=False):
        event = {**(event.get("payload") or {}), **event}
        self.empty.hide()
        card = EventCard(event, self.window, historical)
        self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, card)
        # A live insertion must be exposed before it can receive pointer input.
        # Layout geometry is still allowed to settle in the normal event loop.
        card.show()
        if event.get("type") in ("approval", "approval_request", "tool_approval"):
            request_id = event.get("request_id") or (event.get("payload") or {}).get("request_id")
            if request_id:
                self.approvals[request_id] = card
                if not historical:
                    self.pending_approval_events[request_id] = event
                    self.pending_review.show()
                    self.window.update_role_tabs()
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


class ScreenshotReviewDialog(QDialog):
    """Preview only registered, core-validated image files; no pixel redaction."""
    def __init__(self, window, artifacts, require_confirmation=True):
        super().__init__(window)
        self.window, self.artifacts = window, artifacts
        self.visited = set()
        self.pixmap = None
        self.require_confirmation = require_confirmation
        self.setWindowTitle("Review screenshot pixels before export" if require_confirmation else "Screenshot preview")
        self.resize(1050, 780)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Screenshot pixels are NOT automatically redacted. Images may contain credentials, private text, or other sensitive information. Review every image; use Actual size to inspect small text.", True))
        controls = QHBoxLayout()
        self.selector = QComboBox()
        for artifact in artifacts:
            self.selector.addItem(artifact.get("name") or artifact["id"], artifact)
        controls.addWidget(self.selector, 1)
        self.actual_size = QCheckBox("Actual size")
        self.actual_size.toggled.connect(self.render_image)
        controls.addWidget(self.actual_size)
        layout.addLayout(controls)
        self.status = label("", True)
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setTextFormat(Qt.PlainText)
        self.scroll.setWidget(self.picture)
        layout.addWidget(self.scroll, 1)
        self.reviewed = QCheckBox("I reviewed every image and confirm that these unredacted pixels may be exported.")
        self.reviewed.setObjectName("confirm_screenshot_pixels")
        self.reviewed.setVisible(require_confirmation)
        self.reviewed.toggled.connect(self.update_confirmation)
        layout.addWidget(self.reviewed)
        actions = QDialogButtonBox(QDialogButtonBox.Cancel if require_confirmation else QDialogButtonBox.Close)
        self.confirm_button = None
        if require_confirmation:
            self.confirm_button = actions.addButton("Confirm image export", QDialogButtonBox.AcceptRole)
            self.confirm_button.setEnabled(False)
            actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self.selector.currentIndexChanged.connect(self.load_selected)
        self.load_selected()

    def load_selected(self, index=0):
        artifact = self.selector.currentData()
        if not artifact:
            return
        self.pixmap = None
        self.picture.clear()
        try:
            # The core revalidates signature/dimensions and limits this path to
            # a registered file inside its managed artifact directory.
            path = self.window.core.artifact_path(artifact["id"])
            image = QPixmap(str(path))
            if image.isNull():
                raise ValueError("The verified image could not be decoded for review")
            self.pixmap = image
            self.visited.add(artifact["id"])
            self.status.setText(f"{artifact.get('name', artifact['id'])} · {image.width()} × {image.height()} · Pixels unchanged")
            self.render_image()
        except Exception as exc:
            self.status.setText("Preview unavailable: " + str(exc))
            self.visited.discard(artifact["id"])
        self.update_confirmation()

    def render_image(self, checked=False):
        if self.pixmap is None:
            return
        image = self.pixmap if self.actual_size.isChecked() else self.pixmap.scaled(970, 570, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.picture.setPixmap(image)
        self.picture.resize(image.size())

    def update_confirmation(self, checked=False):
        if self.confirm_button is not None:
            all_loaded = len(self.visited) == len({artifact['id'] for artifact in self.artifacts})
            self.confirm_button.setEnabled(all_loaded and self.reviewed.isChecked())


class ArtifactPanel(QWidget):
    """Task-scoped imports and exports go through the workspace core boundary."""
    def __init__(self, window, task_id=None):
        super().__init__()
        self.window, self.task_id = window, task_id or identifier(window.core.current_task or {})
        layout = QVBoxLayout(self)
        layout.addWidget(label("Import UTF-8 text, diff, patch, JSONL, Markdown, reports, test logs, or PNG/JPEG screenshots from the selected project. Copies are stored as managed task artifacts. Screenshot pixels are not redacted.", True))
        self.table = QTreeWidget()
        self.table.setObjectName("artifact_table")
        self.table.setHeaderLabels(["Kind", "Name", "Created", "Safety handling"])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.currentItemChanged.connect(self.selection_changed)
        self.table.itemDoubleClicked.connect(lambda item: self.open_selected())
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.import_button = button("Import file…", self.import_file, "import_artifact")
        self.import_button.setEnabled(bool(self.task_id))
        actions.addWidget(self.import_button)
        self.open_button = button("Open selected", self.open_selected, "open_artifact")
        self.export_button = button("Export selected…", self.export_selected, "export_artifact")
        self.metadata_button = button("Metadata", self.show_metadata)
        for control in (self.open_button, self.export_button, self.metadata_button):
            control.setEnabled(False)
            actions.addWidget(control)
        actions.addStretch()
        actions.addWidget(button("Refresh", self.refresh))
        layout.addLayout(actions)
        self.status = label("", True)
        layout.addWidget(self.status)
        self.refresh()

    def selected(self):
        item = self.table.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def selection_changed(self, current, previous=None):
        for control in (self.open_button, self.export_button, self.metadata_button):
            control.setEnabled(current is not None)

    def refresh(self):
        self.table.clear()
        if not self.task_id:
            self.status.setText("Select a task to manage artifacts.")
            return
        try:
            rows = self.window.core.artifacts(self.task_id)
            for artifact in rows:
                is_image = artifact.get("type") == "screenshot"
                item = QTreeWidgetItem([str(artifact.get("type", "")), str(artifact.get("name", "")), str(artifact.get("timestamp", "")), "Pixels NOT redacted; review before export" if is_image else "Safety-filtered text"])
                item.setData(0, Qt.UserRole, artifact)
                self.table.addTopLevelItem(item)
            self.table.setColumnWidth(0, 110)
            self.table.setColumnWidth(1, 280)
            self.table.setColumnWidth(2, 200)
            self.status.setText(f"{len(rows)} managed artifacts")
        except Exception as exc:
            self.status.setText(str(exc))

    def import_file(self):
        if not self.task_id:
            return
        project = self.window.core.current_project or {}
        filters = "Supported artifacts (*.txt *.log *.diff *.patch *.jsonl *.md *.markdown *.png *.jpg *.jpeg);;Text / reports (*.txt);;Test logs (*.log);;Patch / diff (*.patch *.diff);;JSONL (*.jsonl);;Markdown (*.md *.markdown);;Screenshots (*.png *.jpg *.jpeg)"
        path, _ = QFileDialog.getOpenFileName(self, "Import project artifact", project.get("repo_path", ""), filters)
        if not path:
            return
        screenshot = Path(path).suffix.lower() in (".png", ".jpg", ".jpeg")
        if screenshot and not self.window.confirm_screenshot_import(path, self):
            return
        self.import_button.setEnabled(False)
        self.status.setText("Importing the selected file through workspace safety checks…")
        def imported(record):
            self.import_button.setEnabled(True)
            self.refresh()
            for index in range(self.table.topLevelItemCount()):
                item = self.table.topLevelItem(index)
                if item.data(0, Qt.UserRole)["id"] == record["id"]:
                    self.table.setCurrentItem(item)
                    break
            self.status.setText("Imported managed copy. " + ("Review screenshot pixels before exporting." if screenshot else "Text safety filtering applied."))
        def failed(error):
            self.import_button.setEnabled(True)
            self.status.setText("Import failed: " + error)
        self.window.run(lambda: self.window.core.import_artifact(path, task_id=self.task_id, user_selected=screenshot), imported, on_error=failed)

    def open_selected(self):
        artifact = self.selected()
        if not artifact:
            return
        try:
            if artifact.get("type") == "screenshot":
                ScreenshotReviewDialog(self.window, [artifact], require_confirmation=False).exec()
            else:
                path = self.window.core.artifact_path(artifact["id"])
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                    raise RuntimeError("The operating system could not open this artifact; no file handler may be installed.")
        except Exception as exc:
            self.status.setText("Open failed: " + str(exc))

    def show_metadata(self):
        artifact = self.selected()
        if artifact:
            self.window.show_detail("Managed artifact metadata", artifact)

    def export_selected(self):
        artifact = self.selected()
        if not artifact:
            return
        is_screenshot = artifact.get("type") == "screenshot"
        if is_screenshot and not self.window.confirm_screenshot_export([artifact]):
            return
        suffix = Path(artifact.get("path") or "").suffix or {"diff": ".diff", "patch": ".patch", "test log": ".log", "markdown": ".md", "jsonl": ".jsonl"}.get(artifact.get("type"), ".txt")
        name = Path(artifact.get("name") or "artifact").stem + suffix
        target, _ = QFileDialog.getSaveFileName(self, "Export managed artifact", name, f"Artifact (*{suffix})")
        if target:
            self.window.run(lambda: self.window.core.export_artifact(artifact["id"], target, screenshot_reviewed=is_screenshot),
                            lambda path: self.status.setText("Exported · " + str(path)))


def native_transcript(history):
    """Format already-sanitized native records without changing persisted state."""
    sections = []
    rows = history if isinstance(history, list) else [history]
    for row in rows:
        if not isinstance(row, dict):
            sections.append(plain(row))
            continue
        entries = row.get("items") if isinstance(row.get("items"), list) else [row]
        for entry in entries:
            kind = entry.get("role") or entry.get("type") or "event"
            if kind == "agentMessage":
                kind = "assistant"
            elif kind == "userMessage":
                kind = "user"
            content = entry.get("content", entry.get("text"))
            if isinstance(content, list):
                content = "\n".join(block.get("text", plain(block)) if isinstance(block, dict) else str(block) for block in content)
            if content is None:
                content = plain(entry)
            stamp = str(entry.get("timestamp") or entry.get("created_at") or "")
            sections.append(f"{str(kind).upper()}  {stamp}\n{plain(content)}")
    return "\n\n".join(sections) or "No visible conversation records returned."


class SessionDetailsDialog(QDialog):
    def __init__(self, display, parent=None):
        super().__init__(parent)
        self.setWindowTitle('對話詳細資訊')
        self.resize(700, 400)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit(display['details']); text.setReadOnly(True)
        layout.addWidget(text)
        layout.addWidget(button('Copy session ID', lambda: QApplication.clipboard().setText(str(display['id'])), 'copy_session_id'))
        layout.addWidget(button('Close', self.accept))


class SessionHistoryDialog(QDialog):
    """Offline cross-project list of Workspace-owned sessions; no native read."""
    def __init__(self, window, agent):
        super().__init__(window)
        self.window, self.agent = window, agent
        self.setWindowTitle(f'{agent.title()} · 本機對話歷史')
        self.resize(1100, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(label('只顯示已保存的本機資料。選取不會連線、送訊或 Resume。跨專案 Resume 前請先切到該專案與任務。', True))
        self.search = QLineEdit(); self.search.setPlaceholderText('搜尋專案、標題、路徑…')
        self.search.textChanged.connect(self.filter_rows); layout.addWidget(self.search)
        self.table = QTreeWidget(); self.table.setHeaderLabels(['專案', '對話', '最近時間', '工作目錄', '後端 / 來源'])
        self.table.setRootIsDecorated(False)
        self.table.currentItemChanged.connect(self.show_saved); layout.addWidget(self.table, 1)
        self.transcript = QPlainTextEdit(); self.transcript.setReadOnly(True); layout.addWidget(self.transcript, 1)
        for row, display in local_session_displays(window.core, agent, window.core.sessions(agent)):
            item = QTreeWidgetItem([display['project'], display['title'], display['updated'], display['cwd'], display['source']])
            item.setData(0, Qt.UserRole, display); item.setToolTip(0, display['details']); self.table.addTopLevelItem(item)
        for column, width in enumerate((230, 290, 200, 260)): self.table.setColumnWidth(column, width)
        actions = QHBoxLayout()
        actions.addWidget(button('詳細 / Copy ID', self.details))
        actions.addWidget(button('選取對話（不 Resume）', self.select_session, 'select_history_session'))
        actions.addWidget(button('Task History', lambda: (self.accept(), window.show_history(agent))))
        actions.addWidget(button('Close', self.accept)); layout.addLayout(actions)

    def filter_rows(self):
        query = self.search.text().casefold().strip()
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index); display = item.data(0, Qt.UserRole)
            item.setHidden(bool(query and query not in (display['label']+display['cwd']).casefold()))
        current = self.table.currentItem()
        if current and current.isHidden(): self.table.setCurrentItem(None); self.transcript.clear()

    def show_saved(self, current, previous=None):
        if not current: self.transcript.clear(); return
        display = current.data(0, Qt.UserRole)
        core = self.window.core
        rows = core.store.query("SELECT role,content,timestamp FROM messages WHERE agent=? AND session_id=? ORDER BY timestamp,id LIMIT 500", (self.agent, display['id'])) if hasattr(core, 'store') else []
        self.transcript.setPlainText('\n\n'.join(f"{row['role']} · {row['timestamp']}\n{row['content']}" for row in rows) or '沒有已保存的對話內容；未向後端讀取歷史。')

    def details(self):
        item = self.table.currentItem()
        if item: SessionDetailsDialog(item.data(0, Qt.UserRole), self).exec()

    def select_session(self):
        item = self.table.currentItem()
        if not item or item.isHidden(): return
        panel = self.window.panels[self.agent]
        panel.session_search.clear()
        index = panel.session.findData(item.data(0, Qt.UserRole)['id'])
        if index >= 0: panel.session.setCurrentIndex(index); self.accept()


class NativeHistoryDialog(QDialog):
    def __init__(self, agent, session_id, history, parent=None, record=None):
        super().__init__(parent)
        self.setWindowTitle(f"{agent.title()} native history — read only")
        self.resize(940, 690)
        layout = QVBoxLayout(self)
        display = session_display(record or {'id': session_id}, agent,
                                  parent.window.core.list_projects() if hasattr(parent, 'window') else ())
        layout.addWidget(label(display['label'], True))
        layout.addWidget(button('詳細 / Copy ID', lambda: SessionDetailsDialog(display, self).exec()))
        layout.addWidget(label('Preview only. This does not import messages, remap the task, resume the session, or send a prompt.', True))
        tabs = QTabWidget()
        self.transcript = QPlainTextEdit(native_transcript(history))
        self.transcript.setObjectName("native_history_transcript")
        self.transcript.setReadOnly(True)
        tabs.addTab(self.transcript, "Conversation / activity")
        raw = QPlainTextEdit(plain(history))
        raw.setReadOnly(True)
        raw.setFont(QFont("Consolas", 10))
        tabs.addTab(raw, "Sanitized structured records")
        layout.addWidget(tabs, 1)
        layout.addWidget(button("Close", self.accept))


class NativeSessionDialog(QDialog):
    """Explicit discovery and metadata import; never resume an existing thread."""
    def __init__(self, window, agent):
        super().__init__(window)
        self.window, self.agent = window, agent
        self.history_capability = {"supported": False, "detail": "Discover native sessions first."}
        self.request_pending = False
        self.setWindowTitle(f"Discover {agent.title()} sessions")
        self.resize(960, 590)
        layout = QVBoxLayout(self)
        layout.addWidget(label("This action lists the session index supported by the backend. Import adds local metadata only. Select Resume separately if you intend to continue that session.", True))
        self.status = label("Ready to discover sessions", True)
        layout.addWidget(self.status)
        self.table = QTreeWidget()
        self.table.setObjectName("native_sessions")
        self.table.setHeaderLabels(["專案", "對話", "Directory", "Updated", "Source"])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.currentItemChanged.connect(self.selection_changed)
        self.search = QLineEdit(); self.search.setPlaceholderText('搜尋專案、對話名稱、路徑…')
        self.search.textChanged.connect(self.filter_rows); layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        self.import_button = button("Import selected (no resume)", self.import_selected, "import_native_session")
        self.import_button.setEnabled(False)
        self.history_button = button("View native history", self.view_history, "view_native_history")
        self.history_button.setEnabled(False)
        self.history_button.setToolTip(self.history_capability["detail"])
        actions = QHBoxLayout()
        actions.addWidget(self.import_button)
        actions.addWidget(self.history_button)
        actions.addWidget(button('詳細 / Copy ID', self.show_details))
        actions.addStretch()
        actions.addWidget(button("Close", self.reject))
        layout.addLayout(actions)

    def load(self):
        self.status.setText("Listing backend sessions…")
        self.import_button.setEnabled(False)
        self.history_button.setEnabled(False)
        self.window.run(lambda: self.window.core.discover_sessions(self.agent), self.set_sessions,
                        on_error=lambda error: self.status.setText("Discovery failed: " + error))

    def set_sessions(self, rows):
        self.table.clear()
        for row, display in local_session_displays(self.window.core, self.agent, rows):
            sid = session_identity(row)
            if not sid:
                continue
            item = QTreeWidgetItem([display['project'], display['title'], display['cwd'], display['updated'], display['source']])
            item.setData(0, Qt.UserRole, row)
            item.setToolTip(0, display['details'])
            self.table.addTopLevelItem(item)
        self.status.setText(f"{self.table.topLevelItemCount()} session records returned. Nothing has been imported or resumed.")
        self.table.setColumnWidth(0, 230)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(2, 260)
        try:
            self.history_capability = self.window.core.native_history_capability(self.agent)
        except Exception as exc:
            self.history_capability = {"supported": False, "detail": str(exc)}
        self.history_button.setToolTip(self.history_capability.get("detail", "Native history unavailable"))
        self.history_button.setText("View native history" if self.history_capability.get("supported") else "Native history unavailable")
        self.selection_changed(self.table.currentItem())

    def filter_rows(self):
        query = self.search.text().casefold().strip()
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            item.setHidden(bool(query and query not in ' '.join(item.text(c) for c in range(5)).casefold()))
        current = self.table.currentItem()
        if current and current.isHidden(): self.table.setCurrentItem(None)

    def show_details(self):
        item = self.table.currentItem()
        if item: SessionDetailsDialog(session_display(item.data(0, Qt.UserRole), self.agent, self.window.core.list_projects()), self).exec()

    def selection_changed(self, current, previous=None):
        self.import_button.setEnabled(current is not None and not self.request_pending)
        self.history_button.setEnabled(current is not None and not self.request_pending and bool(self.history_capability.get("supported")))

    def view_history(self):
        item = self.table.currentItem()
        if not item or not self.history_button.isEnabled():
            return
        record = item.data(0, Qt.UserRole)
        session_id = record.get("id") or record.get("session_id") or record.get("sessionId") or record.get("threadId")
        self.request_pending = True
        self.table.setEnabled(False)
        self.selection_changed(item)
        self.status.setText("Reading only the explicitly selected native session…")
        def loaded(history):
            self.request_pending = False
            self.table.setEnabled(True)
            self.selection_changed(self.table.currentItem())
            self.status.setText("Native history fetched for a read-only preview. Task and session mapping unchanged.")
            NativeHistoryDialog(self.agent, session_id, history, self, record=record).exec()
        def failed(error):
            self.request_pending = False
            self.table.setEnabled(True)
            self.selection_changed(self.table.currentItem())
            self.status.setText("Native history unavailable: " + error)
        self.window.run(lambda: self.window.core.native_history(self.agent, session_id), loaded, on_error=failed)

    def import_selected(self):
        item = self.table.currentItem()
        if not item:
            return
        record = dict(item.data(0, Qt.UserRole))
        self.request_pending = True
        self.import_button.setEnabled(False)
        self.history_button.setEnabled(False)
        self.table.setEnabled(False)
        self.status.setText("Importing local session metadata…")
        def imported(_):
            self.window.footer.setText(f"{self.agent.title()} session metadata imported. Resume requires a separate action.")
            self.accept()
        def failed(error):
            self.status.setText("Import failed: " + error)
            self.request_pending = False
            self.table.setEnabled(True)
            self.selection_changed(self.table.currentItem())
        self.window.run(lambda: self.window.core.import_session(self.agent, record), imported, on_error=failed)


class DesktopSessionsDialog(QDialog):
    """Pick a Claude desktop project or conversation. Reading happens only after this is opened."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("desktop_sessions_dialog")
        self.setWindowTitle("Claude Desktop 專案與對話")
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(label("這裡列出 Claude Desktop 在本機保存的 Code 對話，依專案資料夾分組。"
                               "選擇後會切換到該資料夾、載入可見的對話紀錄，並在 Claude 面板接續同一個對話。", True))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("desktop_session_search")
        self.search.setPlaceholderText("搜尋對話標題或資料夾…")
        self.search.textChanged.connect(self.fill)
        filters.addWidget(self.search, 1)
        self.archived = QCheckBox("顯示已封存")
        self.archived.toggled.connect(self.fill)
        filters.addWidget(self.archived)
        layout.addLayout(filters)
        self.tree = QTreeWidget()
        self.tree.setObjectName("desktop_session_tree")
        self.tree.setHeaderLabels(["專案／對話", "最後活動", "模型"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 540)
        self.tree.setColumnWidth(1, 130)
        self.tree.currentItemChanged.connect(lambda *_: self.selection_changed())
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_selected(True))
        layout.addWidget(self.tree, 1)
        self.status = label("", True)
        layout.addWidget(self.status)
        layout.addWidget(label("注意：同一個對話不要同時在 Claude Desktop 和這裡傳送訊息，兩邊會寫入同一份紀錄。", True))
        actions = QHBoxLayout()
        self.new_button = button("在此專案開新對話", self.new_conversation, "desktop_new_conversation")
        self.load_button = button("只載入紀錄", lambda: self.open_selected(False), "desktop_load_only")
        self.open_button = button("開啟並接續對話", lambda: self.open_selected(True), "primary")
        actions.addWidget(self.new_button)
        actions.addStretch()
        actions.addWidget(button("Close", self.reject))
        actions.addWidget(self.load_button)
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
        self.sessions = []
        self.selection_changed()

    def load(self):
        self.status.setText("正在讀取 Claude Desktop 的對話清單…")
        def failed(error):
            self.status.setText("無法讀取 Claude Desktop 對話：" + error)
        self.window.run(self.window.core.desktop_sessions, self.set_sessions, on_error=failed)

    def set_sessions(self, sessions):
        self.sessions = list(sessions or [])
        self.fill()

    @staticmethod
    def local_time(value):
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            return ""

    def fill(self, *_):
        from .desktop_sessions import group_by_project
        query = self.search.text().casefold().strip()
        self.tree.clear()
        shown = 0
        for group in group_by_project(self.sessions):
            rows = [s for s in group["sessions"] if (self.archived.isChecked() or not s["archived"])
                    and (not query or query in (s["title"] + " " + s["cwd"]).casefold())]
            if not rows:
                continue
            parent = QTreeWidgetItem([group["name"] + ("" if group["cwd_exists"] else "（資料夾不存在）"),
                                      self.local_time(rows[0]["last_activity"]), f"{len(rows)} 個對話"])
            parent.setData(0, Qt.UserRole, {"kind": "project", "cwd": group["cwd"], "cwd_exists": group["cwd_exists"]})
            parent.setToolTip(0, group["cwd"])
            self.tree.addTopLevelItem(parent)
            for session in rows:
                child = QTreeWidgetItem([session["title"] + ("（已封存）" if session["archived"] else ""),
                                         self.local_time(session["last_activity"]), session["model"]])
                child.setData(0, Qt.UserRole, dict(session, kind="session"))
                child.setToolTip(0, session["cwd"] + "\n對話 ID：" + session["id"])
                parent.addChild(child)
            parent.setExpanded(bool(query) or self.tree.topLevelItemCount() <= 3)
            shown += len(rows)
        self.status.setText(f"共 {shown} 個對話" if self.sessions else "找不到 Claude Desktop 的本機對話。")
        self.selection_changed()

    def selected(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def selection_changed(self):
        record = self.selected() or {}
        usable = bool(record.get("cwd_exists")) and self.window.mode.currentData() != "Monitor"
        self.open_button.setEnabled(usable and record.get("kind") == "session")
        self.load_button.setEnabled(usable and record.get("kind") == "session")
        self.new_button.setEnabled(usable)

    def open_selected(self, resume):
        record = self.selected() or {}
        if record.get("kind") != "session" or not self.open_button.isEnabled():
            return
        self.accept()
        self.window.open_desktop_session(record, resume)

    def new_conversation(self):
        record = self.selected() or {}
        if not self.new_button.isEnabled():
            return
        self.accept()
        self.window.new_desktop_conversation(record["cwd"])


class HandoffDialog(QDialog):
    def __init__(self, window, message, target):
        super().__init__(window)
        self.window, self.message, self.target = window, message, target
        self.setWindowTitle("Handoff preview — original content preserved")
        self.resize(760, 630)
        self.preview = window.core.prepare_handoff(identifier(message), target)
        layout = QVBoxLayout(self)
        layout.addWidget(label(f"{ROLE_NAMES.get(message.get('agent'), message.get('agent', ''))} → {ROLE_NAMES[target]}", False))
        task = window.core.current_task or {}
        project = window.core.current_project or {}
        projects = window.core.list_projects()
        layout.addWidget(label(f"任務：{task_label(task, projects)}\n專案：{project_label(project, projects)}\nBranch: {task.get('branch', '')}", True))
        rows = window.core.sessions(message.get('agent'))
        source_row = next((r for r in rows if session_identity(r) == message.get('session_id')), {'id': message.get('session_id')})
        layout.addWidget(label('來源對話：' + session_display(source_row, message.get('agent', ''), projects)['label'], True))
        layout.addWidget(label("Original source message"))
        source = QPlainTextEdit(plain(message.get("content", "")))
        source.setReadOnly(True)
        source.setObjectName("handoff_source")
        layout.addWidget(source, 1)
        layout.addWidget(label("Additional note (saved separately)"))
        self.annotation = QPlainTextEdit()
        self.annotation.setObjectName("handoff_annotation")
        self.annotation.setMaximumHeight(90)
        layout.addWidget(self.annotation)
        self.annotation.textChanged.connect(self.update_preview)
        layout.addWidget(label("Outgoing handoff"))
        self.outgoing = QPlainTextEdit()
        self.outgoing.setReadOnly(True)
        self.outgoing.setObjectName("handoff_outgoing")
        layout.addWidget(self.outgoing, 1)
        self.update_preview()
        layout.addWidget(label("自動協作已關閉。必須由你確認後才能傳送。", True))
        actions = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.send_button = actions.addButton("Confirm and send", QDialogButtonBox.AcceptRole)
        self.send_button.setObjectName("handoff_send")
        ready = window.panels[target].connection_state == "Connected"
        self.send_button.setEnabled(ready)
        if not ready:
            layout.addWidget(label(f"{ROLE_NAMES[target]} 尚未連線。此預覽尚未傳送。", True))
        actions.rejected.connect(self.reject)
        actions.accepted.connect(self.accept)
        layout.addWidget(actions)

    def update_preview(self):
        self.preview = self.window.core.update_handoff_annotation(self.preview["id"], self.annotation.toPlainText())
        self.outgoing.setPlainText(plain(self.preview.get("handoff_message") or self.preview.get("content") or self.preview))


class MainWindow(QMainWindow):
    def __init__(self, core):
        super().__init__()
        self.core = core
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
        self._loaded_context_key = None
        self._layout_updating = False
        self._grid_sizes = [400] * len(AGENTS)
        self._preferred_agent = "claude"
        self.setWindowTitle("AI Collaboration Workspace")
        self.setObjectName("ai_collaboration_workspace")
        self.resize(1530, 920)
        self.setMinimumSize(640, 420)
        QApplication.instance().setPalette(metal_palette())
        self.setStyleSheet(build_style())
        root = QWidget()
        root.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        self.sidebar_toggle = button("☰", self.toggle_sidebar, "sidebar_toggle")
        self.sidebar_toggle.setAccessibleName("切換專案與對話側欄")
        self.sidebar_toggle.setToolTip("專案與對話 · Ctrl+B")
        self.sidebar_toggle.setCheckable(True)
        self.sidebar_toggle.setChecked(True)
        heading.addWidget(self.sidebar_toggle)
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
        self.layout_mode.setAccessibleName("對話布局")
        self.layout_mode.setToolTip("自動布局：窄視窗顯示一個角色，空間足夠時顯示三欄")
        self.layout_mode.currentIndexChanged.connect(self.update_workspace_layout)
        heading.addWidget(self.layout_mode)
        self.details_toggle = button("Work details", self.toggle_details, "details_toggle")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setToolTip("工具、命令、變更、測試、時間線與交接 · Ctrl+Shift+D")
        heading.addWidget(self.details_toggle)
        workspace_menu = QToolButton()
        workspace_menu.setObjectName("workspace_actions")
        workspace_menu.setText("⋯")
        workspace_menu.setAccessibleName("工作區操作")
        workspace_menu.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(workspace_menu)
        for text, callback in (("任務筆記…", self.notes), ("比較回覆…", self.compare),
                               ("差異／測試／附件…", self.inspect_artifacts), ("匯出…", self.export),
                               ("同步專案至角色", self.sync_project), ("設定…", self.settings),
                               ("診斷…", self.diagnostics), ("停止目前任務…", self.stop_task)):
            menu.addAction(text, callback)
        workspace_menu.setMenu(menu)
        heading.addWidget(workspace_menu)
        layout.addLayout(heading)
        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(230)
        self.sidebar.setMaximumWidth(310)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(8)
        side.addWidget(label("專案與對話", True))
        project_row = QHBoxLayout()
        self.project_combo = QComboBox()
        self.project_combo.setObjectName("global_project")
        self.project_combo.setAccessibleName("目前專案")
        self.project_combo.setMinimumContentsLength(10)
        self.project_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.project_combo.currentIndexChanged.connect(self.project_changed)
        project_row.addWidget(self.project_combo, 1)
        create_project = button("+", self.new_project, "new_project")
        create_project.setAccessibleName("新增專案")
        create_project.setToolTip("新增專案")
        project_row.addWidget(create_project)
        side.addLayout(project_row)
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
        side.addLayout(task_row)
        self.task_status = QComboBox()
        self.task_status.addItem("尚未選擇任務", None)
        for value in STATUSES:
            self.task_status.addItem(STATUS_LABELS[value], value)
        self.task_status.setObjectName("task_status")
        self.task_status.setAccessibleName("任務狀態")
        self.task_status.currentIndexChanged.connect(lambda _: self.status_changed(self.task_status.currentData()))
        side.addWidget(label("任務狀態", True))
        side.addWidget(self.task_status)
        self.mode = QComboBox()
        for title, value in (("對話", "Workspace"), ("監看（唯讀）", "Monitor"), ("時間線", "Timeline"), ("歷史", "History")):
            self.mode.addItem(title, value)
        self.mode.setObjectName("view_mode")
        self.mode.setAccessibleName("工作區檢視")
        self.mode.currentIndexChanged.connect(lambda _: self.change_mode(self.mode.currentData()))
        side.addWidget(label("檢視", True))
        side.addWidget(self.mode)
        self.session_tabs = QTabWidget()
        self.session_tabs.setObjectName("sidebar_sessions")
        self.session_tabs.setDocumentMode(True)
        self.session_tabs.setAccessibleName("各角色對話")
        side.addWidget(self.session_tabs, 1)
        side.addWidget(button("Desktop 專案與對話…", self.show_desktop_sessions, "desktop_sessions"))
        side.addWidget(button("Settings…", self.settings, "settings"))
        self.workspace_splitter.addWidget(self.sidebar)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        roles = QHBoxLayout()
        self.role_tabs = QTabBar()
        self.role_tabs.setObjectName("role_tabs")
        self.role_tabs.setExpanding(False)
        self.role_tabs.setUsesScrollButtons(True)
        self.role_tabs.setElideMode(Qt.ElideRight)
        self.role_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.role_tabs.setDrawBase(False)
        self.role_tabs.setAccessibleName("對話角色")
        for agent in AGENTS:
            self.role_tabs.addTab(ROLE_NAMES[agent] + " · " + ROLE_LABELS[agent])
        self.role_tabs.currentChanged.connect(self.select_role)
        roles.addWidget(self.role_tabs, 1)
        self.unfocus_button = button("四欄並排", lambda: self.focus_agent(None), "unfocus")
        self.unfocus_button.hide()
        roles.addWidget(self.unfocus_button)
        content_layout.addLayout(roles)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.splitter = QSplitter(Qt.Horizontal)
        self.panels = {agent: AgentPanel(agent, self) for agent in AGENTS}
        for agent, panel in self.panels.items():
            self.splitter.addWidget(panel)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(panel.session_controls)
            self.session_tabs.addTab(scroll, ROLE_NAMES[agent])
        self.session_tabs.currentChanged.connect(self.sidebar_role_changed)
        self.splitter.setChildrenCollapsible(False)
        self.stack.addWidget(self.splitter)
        self.timeline = QTreeWidget()
        self.timeline.setHeaderLabels(["Time", "Agent", "Event", "Status", "Summary"])
        self.timeline.setAlternatingRowColors(True)
        self.timeline.itemDoubleClicked.connect(lambda item: self.show_detail("Event detail", item.data(0, Qt.UserRole)))
        self.stack.addWidget(self.timeline)
        self.history_page = self.build_history()
        self.stack.addWidget(self.history_page)
        content_layout.addWidget(self.stack, 1)
        self.details_panel = QFrame()
        self.details_panel.setObjectName("work_details")
        self.details_panel.setMinimumHeight(140)
        self.details_panel.setMaximumHeight(300)
        detail_layout = QVBoxLayout(self.details_panel)
        detail_layout.setContentsMargins(12, 8, 12, 8)
        self.details_tabs = QTabWidget()
        self.details_tabs.setObjectName("details_tabs")
        self.detail_trees = {}
        for title in ("Tools", "Commands", "Changes", "Tests", "Timeline", "Handoffs"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 6, 0, 0)
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
            ("新增任務", "Ctrl+N", self.new_task),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        for index, agent in enumerate(AGENTS, 1):
            action = QAction("Focus " + ROLE_NAMES[agent], self)
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
        QTimer.singleShot(0, self, self.update_workspace_layout)

    def context_key(self):
        task = self.core.current_task or {}
        return (identifier(self.core.current_project or {}), identifier(task),
                tuple(task.get(agent + "_session") or "" for agent in AGENTS))

    def save_context_state(self):
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

    def show_sessions(self, agent):
        self.sidebar.show()
        self.sidebar_toggle.setChecked(True)
        self.session_tabs.setCurrentIndex(AGENTS.index(agent))
        self.panels[agent].session.setFocus()
        QTimer.singleShot(0, self, self.update_workspace_layout)

    def sidebar_role_changed(self, index):
        if index >= 0 and hasattr(self, "role_tabs"):
            self.role_tabs.setCurrentIndex(index)

    def select_role(self, index):
        if index < 0 or not hasattr(self, "panels"):
            return
        self._preferred_agent = AGENTS[index]
        self.session_tabs.setCurrentIndex(index)
        if self.focused_agent is not None:
            self.update_workspace_layout()

    def update_role_tabs(self):
        if not hasattr(self, "panels"):
            return
        for index, agent in enumerate(AGENTS):
            panel = self.panels[agent]
            pending = len(panel.pending_approval_events)
            self.role_tabs.setTabText(index, ROLE_NAMES[agent] + " · " + ("待核准" if pending else ROLE_LABELS[agent]))
            self.role_tabs.setTabToolTip(index, f"{ROLE_NAMES[agent]} · {ROLE_LABELS[agent]} · {panel.state.text()}")

    def update_workspace_layout(self, *_):
        if not hasattr(self, "panels") or self._layout_updating:
            return
        self._layout_updating = True
        try:
            if self.height() < 700 and not self.details_panel.isHidden():
                self.show_details_dialog()
            if hasattr(self, "workspace_scroll"):
                self.workspace_scroll.widget().setMaximumHeight(max(450, self.workspace_scroll.viewport().height()))
            available = self.splitter.width()
            narrow = available < len(AGENTS) * 300 + (len(AGENTS) - 1) * self.splitter.handleWidth()
            focused = self.layout_mode.currentData() == "Focus" or narrow
            was_focused = self.focused_agent is not None
            if focused and not was_focused and all(not panel.isHidden() for panel in self.panels.values()):
                self._grid_sizes = self.splitter.sizes()
            self.focused_agent = self._preferred_agent if focused else None
            for agent, panel in self.panels.items():
                panel.setVisible(not focused or agent == self._preferred_agent)
            if not focused and was_focused:
                self.splitter.setSizes(self._grid_sizes)
            self.unfocus_button.setVisible(focused and not narrow)
            self.role_tabs.setToolTip("窄視窗 · 一次顯示一個可讀的對話" if narrow else "選擇角色，或按兩下角色標題以專注")
            self.update_role_tabs()
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
            dialog_layout.setContentsMargins(12, 12, 12, 12)
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

    def refresh_work_details(self):
        groups = {name: [] for name in self.detail_trees}
        for event in reversed(self.core.events(limit=500)):
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
        groups["Handoffs"] = handoffs() if callable(handoffs) else []
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
                item = QTreeWidgetItem([ROLE_NAMES.get(source, source) + (" → " + ROLE_NAMES.get(target, target) if target else ""),
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
        def failed(message):
            if agent:
                self.panels[agent].set_state("Error")
                self.panels[agent].notice.setText(message)
                self.panels[agent].notice.setToolTip(message)
            if on_error:
                on_error(message)
            self.show_error(message, modal=False)
        if callback:
            def delivered(result):
                try:callback(result)
                except Exception as exc:
                    from .security import sanitize
                    message=str(sanitize(str(exc)))
                    adapter=getattr(self.core,'adapters',{}).get(agent) if agent else None
                    if adapter is not None:
                        adapter.last_error=message
                        self.core.ingest_event(agent,'error',content=message,source='UI result callback')
                        adapter.set_state('Error')
                    failed(message)
            worker.signals.result.connect(delivered)
        worker.signals.error.connect(failed)
        worker.signals.finished.connect(lambda: self.workers.discard(worker))
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
        current_task_id = identifier(self.core.current_task or {})
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
            full_title = (project.get("name") or "選擇專案") + " › " + (task.get("title") or "選擇任務")
            self.context_title.setText(compact(full_title, 90))
            self.context_title.setToolTip(full_title)
            for agent, panel in self.panels.items():
                view = saved_view.get("panels", {}).get(agent, {})
                self.reconcile_pending_approvals(view, agent, identifier(task))
                panel._restoring_view = True
                panel.clear_conversation()
                for message in self.core.messages(agent=agent):
                    if message.get("role") in ("user", "assistant"):
                        panel.add_message(message)
                for event in reversed(self.core.events(agent=agent, limit=100)):
                    if event.get("type") in ("tool_start", "tool_result", "command", "command_output", "file", "file_edit", "error", "test", "approval", "approval_request", "tool_approval"):
                        pending_id = event.get("request_id") or (event.get("payload") or {}).get("request_id")
                        panel.add_event(event, historical=pending_id not in view.get("pending", {}))
                panel.cwd_label.setText(("中繼資料：" if agent == "dot" else "工作目錄：") + (project.get("name", "尚未選擇") if agent == "dot" else project.get(f"{agent}_cwd") or project.get("repo_path") or project.get("repo") or "尚未選擇"))
                panel.cwd_label.setToolTip(panel.cwd_label.text())
                panel.branch_label.setText("分支：" + (task.get("branch") or project.get("active_branch") or "—"))
                self.refresh_agent(agent)
                panel.restore_view_state(view)
            self._loaded_context_key = key
            self._preferred_agent = saved_view.get("role", self._preferred_agent)
            self.role_tabs.setCurrentIndex(AGENTS.index(self._preferred_agent))
            self.session_tabs.setCurrentIndex(saved_view.get("session_tab", AGENTS.index(self._preferred_agent)))
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
            panel.refresh_sessions(self.core.sessions(agent), diag.get("session") or (self.core.current_task or {}).get(f"{agent}_session"))
            if diag.get("last_error"):
                panel.notice.setText(diag["last_error"])
                panel.notice.setToolTip(diag["last_error"])
        except Exception as exc:
            self.show_error(str(exc), False)

    def poll_events(self):
        self._legacy_clock += 1
        self._git_clock += 1
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
            legacy_root = self.core.get_setting("legacy.root", r"C:\Users\ryant\Desktop\AI-Collab-Monitor")
            self.run(lambda: self.core.poll_legacy(legacy_root), loaded_legacy,
                     on_error=lambda _: setattr(self, "_legacy_busy", False))
        if self._git_clock >= 100 and not self._git_busy and self.core.current_project and not self._close_pending:
            self._git_clock = 0
            self._git_busy = True
            def loaded_git(snapshot):
                self._git_busy = False
                for agent in ("claude", "codex", "local"):
                    self.panels[agent].branch_label.setText(self.branch_text(snapshot))
            self.run(self.core.git_snapshot, loaded_git, on_error=lambda _: setattr(self, "_git_busy", False))
        try:
            events = self.core.drain_events()
        except Exception as exc:
            self.footer.setText("Event reader error · " + str(exc))
            return
        if not events:
            return
        latest_delta = {event.get("message_id"): index for index, event in enumerate(events) if event.get("type") == "message_delta"}
        current_task_id = identifier(self.core.current_task or {})
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
            if event.get("task_id") and event.get("task_id") != current_task_id:
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
            elif panel and kind not in ("raw", "state", "connection_state", "heartbeat", "message_delta", "legacy"):
                panel.add_event(event)
            if self.mode.currentData() == "Timeline":
                self.add_timeline_event(event)
        if self.details_toggle.isChecked():
            self.refresh_work_details()
        error_panel=next((panel for panel in self.panels.values() if panel.connection_state=='Error'),None)
        self.footer.setText('Error · '+error_panel.agent+' · '+error_panel.notice.text() if error_panel else self.last_event)

    def show_desktop_sessions(self):
        dialog = DesktopSessionsDialog(self)
        dialog.load()
        dialog.exec()

    def _claude_ready(self):
        if self.core.adapters["claude"].state != "Connected":
            self.core.connect("claude")

    def open_desktop_session(self, record, resume=True):
        if not self.confirm_context_change():
            return
        def opened(result):
            self.reload_context()
            self.focus_role("claude")
            self.footer.setText(f"已載入 Desktop 對話「{record.get('title', '')}」· 匯入 {result['imported']} 則可見訊息")
            if resume:
                self.panels["claude"].set_state("Connecting")
                def continue_session():
                    self._claude_ready()
                    return self.core.resume_session("claude", result["session_id"])
                self.run(continue_session, lambda _: (self.reload_context(), self.refresh_agent("claude")), "claude")
        self.run(lambda: self.core.open_desktop_session(record), opened)

    def new_desktop_conversation(self, directory):
        if not self.confirm_context_change():
            return
        title = "新對話 " + datetime.now().strftime("%m-%d %H:%M")
        def opened(_):
            self.reload_context()
            self.focus_role("claude")
            self.panels["claude"].set_state("Connecting")
            def start():
                self._claude_ready()
                return self.core.create_session("claude")
            self.run(start, lambda _: (self.reload_context(), self.refresh_agent("claude")), "claude")
        self.run(lambda: self.core.open_desktop_project(directory, title), opened)

    def focus_role(self, agent):
        self._preferred_agent = agent
        self.role_tabs.setCurrentIndex(AGENTS.index(agent))
        self.session_tabs.setCurrentIndex(AGENTS.index(agent))

    def require_project(self, reason):
        box = QMessageBox(QMessageBox.Question, "需要專案", "", QMessageBox.Yes | QMessageBox.No, self)
        box.setTextFormat(Qt.PlainText)
        box.setText(reason + "\n專案就是這個角色工作時所在的資料夾。\n\n要現在建立專案嗎？建立後請再按一次「連線」。")
        box.button(QMessageBox.Yes).setText("建立專案…")
        box.button(QMessageBox.No).setText("稍後")
        if box.exec() == QMessageBox.Yes:
            self.new_project()

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

    def new_project(self):
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
            if not self.confirm_context_change():
                return
            project_name, project_repo = name.text().strip(), repo.text().strip()
            project_branch, project_notes = branch.text().strip(), notes.toPlainText()
            def create():
                project = self.core.create_project(project_name, project_repo, default_branch=project_branch, notes=project_notes)
                self.core.select_project(identifier(project))
            self.run(create, lambda _: self.reload_context())

    def new_task(self):
        if not self.core.current_project:
            self.require_project("建立任務前需要先有專案。")
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
        if any(panel.connection_state == "Busy" for panel in self.panels.values()):
            self.show_error("Wait for or stop active turns before changing project or task.")
            return False
        # Navigation saves drafts locally in memory. It never sends or discards them.
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
        task = self.core.current_task
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
            self._preferred_agent = agent
            self.role_tabs.setCurrentIndex(AGENTS.index(agent))
            self.layout_mode.setCurrentIndex(self.layout_mode.findData("Focus"))
        self.update_workspace_layout()

    def change_mode(self, mode):
        for panel in self.panels.values():
            panel.set_monitor(mode == "Monitor")
            for mid, card in panel.cards.items():
                if mid.startswith("legacy-"):
                    card.setVisible(mode == "Monitor")
        self.stack.setCurrentIndex(1 if mode == "Timeline" else 2 if mode == "History" else 0)
        if mode == "Timeline":
            self.refresh_timeline()
        elif mode == "History":
            self.refresh_history()
        elif mode == "Monitor":
            self._legacy_clock = 10
            self.footer.setText("Monitor · Read-only workspace and legacy logs · Existing sessions are untouched")

    def forward(self, message, target):
        try:
            if self.handoff_mode.currentData() == "manual":
                if self.panels[target].connection_state != "Connected":
                    self.show_error(f"{ROLE_NAMES[target]} 尚未連線。未傳送交接。")
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
            messages = [message for message in self.core.messages(agent=source)
                        if message.get("role") == "assistant" and message.get("status", "complete") == "complete"]
            state = self.panels[target].connection_state
            blocked = target == "dot" and not self.panels[target].capabilities.get("supports_sessions")
            reason = " · 受阻" if blocked else " · 請先連線目標角色" if state != "Connected" else " · 尚無來源回覆" if not messages else ""
            action = menu.addAction(f"第 {number} 步：最新 {ROLE_NAMES[source]} 回覆 → {ROLE_NAMES[target]}{reason}")
            action.setEnabled(bool(messages) and state == "Connected" and not blocked)
            if messages:
                action.triggered.connect(lambda checked=False, message=messages[-1], target=target: self.forward(message, target))
        menu.addSeparator()
        explanation = menu.addAction("每一步都需你手動操作 · 自動協作關閉")
        explanation.setEnabled(False)

    def stop_task(self):
        if QMessageBox.question(self, "Stop current task", "Request cancellation from all four adapters for the current task?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.run(lambda: self.core.stop_task(confirmed=True))

    def approve(self, event, approved):
        event = {**(event.get("payload") or {}), **event}
        request_id = event.get("request_id") or event.get("approval_id")
        if not request_id:
            self.show_error("核准要求缺少後端識別碼。未傳送回覆。")
            return
        if approved:
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

    def open_project(self):
        project = self.core.current_project or {}
        path = project.get("repo_path") or project.get("repo")
        if path:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                self.show_error("The operating system could not open the project directory.")
        else:
            self.show_error("No project directory selected.")

    def refresh_timeline(self):
        self.timeline.clear()
        for event in reversed(self.core.events(limit=2000)):
            self.add_timeline_event(event)
        for col, width in enumerate((175, 75, 140, 90)):
            self.timeline.setColumnWidth(col, width)

    def add_timeline_event(self, event):
        item = QTreeWidgetItem([str(event.get(key, "")) for key in ("timestamp", "agent", "type", "status", "summary")])
        item.setData(0, Qt.UserRole, event)
        self.timeline.addTopLevelItem(item)

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
        for agent in AGENTS:
            self.history_agent.addItem(ROLE_NAMES[agent], agent)
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
        layout.addWidget(label("Double-click a task to restore its project and session mapping; double-click a search result to inspect it.", True))
        return page

    def show_history(self, agent=None):
        if agent:
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
        if self.history_project.isChecked() and self.core.current_project:
            filters["project_id"] = identifier(self.core.current_project)
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
            self.run(lambda: self.core.select_task(identifier(row)), lambda _: (self.reload_context(), self.mode.setCurrentIndex(self.mode.findData("Workspace"))))
        elif kind == "result":
            self.show_detail("Search result", row)

    def compare(self):
        messages = [message for message in self.core.messages() if message.get("role") == "assistant"]
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
                if panel.agent != "dot":
                    panel.branch_label.setText(self.branch_text(snapshot))
        self.run(lambda: self.core.git_snapshot(), loaded)
        for event in self.core.events(limit=3000):
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
            path = self.core.project_file(item.data(0, Qt.UserRole))
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise RuntimeError("The operating system could not open the selected file; no file handler may be installed.")
        except Exception as exc:
            self.show_error(str(exc))

    def export(self):
        task = self.core.current_task
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

    def settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("設定")
        dialog.resize(800, 660)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        agent_page = QWidget()
        agent_layout = QVBoxLayout(agent_page)
        agent_layout.addWidget(label("後端設定於下次連線生效。模型與思考強度選項來自實際連線的後端。", True))
        fields = {}
        local_fields = {}
        for agent in AGENTS:
            form = QFormLayout()
            form.addRow(label(ROLE_NAMES[agent] + " · " + ROLE_LABELS[agent]))
            diag = self.core.diagnostics(agent)
            saved = self.core.get_setting("agent." + agent, {}) or {}
            enabled = QCheckBox("啟用")
            enabled.setObjectName(f"default_enabled_{agent}")
            enabled.setChecked(saved.get("enabled", True))
            executable = QLineEdit(saved.get("executable", "" if agent == 'local' else diag.get("executable", "")))
            if agent == 'local':
                executable.setPlaceholderText('留空時依 Harness 自動偵測官方 CLI')
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
            project.addItem("目前工作區專案", None)
            for item in self.core.list_projects():
                project.addItem(project_label(item, self.core.list_projects()), identifier(item))
            project.setCurrentIndex(max(0, project.findData(saved.get("default_project"))))
            form.addRow("", enabled)
            form.addRow("後端", label(diag.get("backend", "Unknown"), True))
            form.addRow("執行檔", executable)
            if agent == 'local':
                harness = QComboBox()
                harness.setObjectName('local_harness')
                harness.addItem('Codex', 'codex')
                harness.addItem('Claude Code', 'claude')
                harness.setCurrentIndex(max(0, harness.findData(saved.get('harness', 'codex'))))
                base_url = QLineEdit(saved.get('base_url', ''))
                base_url.setObjectName('local_base_url')
                local_model = QLineEdit(saved.get('model', ''))
                local_model.setObjectName('local_model')
                api_key_env = QLineEdit(saved.get('api_key_env', ''))
                api_key_env.setObjectName('local_api_key_env')
                form.addRow('Harness', harness)
                form.addRow('端點 Base URL', base_url)
                form.addRow('模型名稱', local_model)
                form.addRow('API key 環境變數名稱', api_key_env)
                form.addRow(label('Codex 需要 Responses API；Claude Code 需要 Anthropic Messages API。儲存後請中斷連線再重新連線。', True))
                local_fields = dict(harness=harness, base_url=base_url, model=local_model, api_key_env=api_key_env)
            form.addRow("逾時（秒）", timeout)
            form.addRow("預設模型", model)
            form.addRow("預設強度", effort)
            form.addRow("預設專案", project)
            form.addRow("串流", label(self.panels[agent].capability_status("supports_streaming"), True))
            form.addRow("原始日誌", label("安全過濾後的稽核紀錄固定啟用", True))
            if agent == 'local':
                local_page = QWidget()
                local_layout = QVBoxLayout(local_page)
                local_layout.addLayout(form)
                local_layout.addStretch()
                local_scroll = QScrollArea()
                local_scroll.setWidgetResizable(True)
                local_scroll.setWidget(local_page)
            else:
                agent_layout.addLayout(form)
            fields[agent] = (saved, enabled, executable, timeout, model, effort, project)
        agent_scroll = QScrollArea()
        agent_scroll.setWidgetResizable(True)
        agent_scroll.setWidget(agent_page)
        tabs.addTab(agent_scroll, "角色與模型")
        tabs.addTab(local_scroll, "Local LLM")
        for name, text in (
            ("Projects", "Use the project selector to choose a working directory. Sync sets Claude, Codex and Local LLM cwd; dot receives metadata only. Git integration is read only."),
            ("Logs", "Raw JSONL and structured events are retained locally. Safety filtering redacts credentials and excludes hidden reasoning before persistence. Open per-agent logs from each panel."),
            ("Permissions", "Original backend permission and sandbox settings remain authoritative. Tool approval requires an explicit user action. Automatic approval and sandbox bypass are not available."),
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
        legacy_root = QLineEdit(self.core.get_setting("legacy.root", r"C:\Users\ryant\Desktop\AI-Collab-Monitor"))
        paths_form.addRow("舊版監看根目錄", legacy_root)
        paths_form.addRow(label("Monitor reads the existing four log files incrementally. It does not write, reset or control the original Monitor sessions.", True))
        tabs.addTab(paths, "路徑")
        appearance = QWidget()
        appearance_layout = QVBoxLayout(appearance)
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
                if agent == 'local':
                    values.update({key: field.currentData() if key == 'harness' else field.text().strip() for key, field in local_fields.items()})
                if model.isEnabled():
                    values["default_model"] = model.currentData()
                if effort.isEnabled():
                    values["default_effort"] = effort.currentData()
                if agent == 'local':
                    values['default_model'] = values['model']
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
        if self._close_pending:
            event.ignore()
            return
        if self.workers or any(panel.connection_state == "Busy" for panel in self.panels.values()):
            result = QMessageBox.question(self, "Active backend work", "Backend work is active. Closing records history but does not silently resend prompts on restart. Request cancellation and close?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if result != QMessageBox.Yes:
                event.ignore()
                return
            # Keep the event loop and store alive until adapter-defined
            # cancellation and in-flight workers finish. Never kill a tree.
            self._close_pending = True
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
                self._close_pending = False
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
        self._closed = True
        event.accept()

