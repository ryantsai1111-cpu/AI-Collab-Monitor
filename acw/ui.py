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

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QUrl, QByteArray
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

AGENTS = ("claude", "dot", "codex")
STATUSES = ("NEW", "PLANNING", "REVIEWING", "READY", "IMPLEMENTING", "VERIFYING",
            "WAITING_USER", "BLOCKED", "DONE", "FAILED", "CANCELLED")
STYLE = """
QWidget { color: #dce3ef; background: #141b27; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow, QDialog { background: #111721; }
QLabel#brand { font-size: 22px; font-weight: 650; color: #f3f6fb; }
QLabel#subtitle, QLabel#muted { color: #8494ad; }
QLabel#agentTitle { font-size: 16px; font-weight: 700; letter-spacing: 1px; }
QLabel#status { color: #9facbe; }
QFrame#panel { background: #182130; border: 1px solid #303d51; border-radius: 8px; }
QFrame#message { border: 1px solid #29374b; border-radius: 5px; background: #182130; }
QFrame#event { border: 1px solid #29374b; border-radius: 4px; background: #131c29; }
QPushButton, QToolButton { background: #243247; border: 1px solid #354761; border-radius: 5px; padding: 6px 10px; }
QPushButton:hover, QToolButton:hover { background: #30455f; border-color: #557395; }
QPushButton:disabled, QToolButton:disabled { color: #63728a; background: #1d2838; border-color: #28354a; }
QPushButton#primary { background: #37679a; border-color: #487cb5; color: white; font-weight: 600; }
QPushButton#stop { color: #ffb6ab; }
QPushButton#primary:disabled, QPushButton#stop:disabled { color: #63728a; background: #1d2838; border-color: #28354a; }
QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QSpinBox { background: #101823; border: 1px solid #334157; border-radius: 4px; padding: 5px; selection-background-color: #355d8c; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #1a2637; selection-background-color: #365477; }
QScrollArea { border: none; }
QScrollBar:vertical { width: 9px; background: #141b27; }
QScrollBar::handle:vertical { background: #3b4c65; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTabWidget::pane { border: 1px solid #2b3b51; }
QTabBar::tab { background: #172131; padding: 9px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { background: #22344d; border-bottom-color: #6ea9e6; }
QHeaderView::section { background: #24344b; padding: 7px; border: none; font-weight: 600; }
QTreeWidget, QTableWidget { background: #111b29; border: 1px solid #303f56; alternate-background-color: #192637; }
QSplitter::handle { background: #111721; width: 7px; }
QMenu { background: #1b293c; border: 1px solid #42546e; }
QMenu::item:selected { background: #355d8c; }
QToolTip { color: #edf3fa; background: #2a3c54; border: 1px solid #657a98; }
"""


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
    result = QPushButton(text)
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
    submit = Signal()
    files_dropped = Signal(list)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
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
        self.heading.setStyleSheet("font-weight: 650; color: #a4c5e7;")
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
        menu.addAction("Copy with metadata", lambda: self.copy(True))
        menu.addAction("Open raw event", lambda: panel.window.open_raw(self.message))
        if role == "assistant":
            menu.addSeparator()
            for target in AGENTS:
                if target != panel.agent:
                    menu.addAction(f"Send to {target.title()}…", lambda checked=False, target=target: panel.window.forward(self.message, target))
        menu_button.setMenu(menu)
        header.addWidget(menu_button)
        layout.addLayout(header)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setFrameShape(QFrame.NoFrame)
        self.body.setStyleSheet("background: transparent; border: none; padding: 0;")
        self.body.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.body)
        if role == "assistant":
            forward = QHBoxLayout()
            forward.addStretch()
            self.forward_button = QToolButton()
            self.forward_button.setText("Forward ▾")
            self.forward_button.setPopupMode(QToolButton.InstantPopup)
            targets = QMenu(self.forward_button)
            for target in AGENTS:
                if target != panel.agent:
                    targets.addAction(target.title(), lambda checked=False, target=target: panel.window.forward(self.message, target))
            self.forward_button.setMenu(targets)
            forward.addWidget(self.forward_button)
            layout.addLayout(forward)
        self.update_content(message.get("content", ""))

    def update_content(self, content):
        self.message["content"] = content
        self.body.setPlainText(plain(content))
        lines = max(1, sum(max(1, (len(line) + 51) // 52) for line in plain(content).splitlines()))
        self.body.setFixedHeight(min(360, 25 + lines * 18))

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
        self.toggle.setStyleSheet("text-align: left; border: none; background: transparent;")
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
                control.setEnabled(not historical and window.mode.currentText() != 'Monitor' and bool(window.core.capabilities(event.get("agent", "")).get("supports_approval")))
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
        self.setObjectName("panel")
        self.setMinimumWidth(305)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 11, 11, 10)
        header = QHBoxLayout()
        self.title = FocusLabel(agent.upper())
        self.title.setObjectName("agentTitle")
        self.title.setToolTip("Double-click to focus this agent")
        self.title.double_clicked.connect(lambda: window.focus_agent(agent))
        header.addWidget(self.title)
        header.addStretch()
        self.state = label("Disconnected")
        self.state.setObjectName("status")
        self.state.setWordWrap(False)
        self.state.setMinimumWidth(self.state.fontMetrics().horizontalAdvance("Disconnected") + 8)
        self.state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.state.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        header.addWidget(self.state)
        layout.addLayout(header)
        self.connect_button = button(f"Connect {agent.title()}", self.connect_agent, f"connect_{agent}")
        layout.addWidget(self.connect_button)
        if agent == 'dot':
            dot_controls = QHBoxLayout()
            self.dot_select = button('Select Dot...', self.select_dot, 'select_dot')
            self.dot_refresh = button('Refresh', lambda: self.read_dot(False), 'refresh_dot')
            self.dot_older = button('Older page', lambda: self.read_dot(True), 'older_dot')
            for control in (self.dot_select, self.dot_refresh, self.dot_older): dot_controls.addWidget(control)
            layout.addLayout(dot_controls)
        self.notice = label("Official backend · connect to discover capabilities", True)
        self.notice.setMaximumHeight(56)
        layout.addWidget(self.notice)
        form = QGridLayout()
        form.setHorizontalSpacing(7)
        form.addWidget(label("Model", True), 0, 0)
        self.model = QComboBox()
        self.model.setObjectName(f"model_{agent}")
        self.model.currentIndexChanged.connect(self.model_changed)
        form.addWidget(self.model, 0, 1, 1, 3)
        form.addWidget(label("Effort", True), 1, 0)
        self.effort = QComboBox()
        self.effort.setObjectName(f"effort_{agent}")
        form.addWidget(self.effort, 1, 1, 1, 3)
        form.addWidget(label("Session", True), 2, 0)
        self.session = QComboBox()
        self.session.setObjectName(f"session_{agent}")
        self.session.view().setMinimumWidth(700)
        form.addWidget(self.session, 2, 1, 1, 2)
        self.session_details = button("詳細 / ID", self.show_session_details, f"session_details_{agent}")
        form.addWidget(self.session_details, 2, 3)
        self.session_search = QLineEdit()
        self.session_search.setObjectName(f"session_search_{agent}")
        self.session_search.setPlaceholderText("搜尋專案、對話名稱、路徑…（本機）")
        self.session_search.textChanged.connect(self.filter_sessions)
        form.addWidget(self.session_search, 4, 0, 1, 4)
        self.current_session_label = label('目前對話：尚未建立或恢復', True)
        self.current_session_label.setObjectName(f'current_session_{agent}')
        form.addWidget(self.current_session_label, 5, 0, 1, 4)
        self.new_button = button("New", self.new_session, f"new_session_{agent}")
        self.resume_button = button("Resume", self.resume_session, f"resume_session_{agent}")
        self.rename_button = button("Rename", self.rename_session)
        self.discover_button = button("Discover…", self.discover_sessions, f"discover_sessions_{agent}")
        self.discover_button.setToolTip("Explicitly list backend sessions; import metadata without resuming")
        form.addWidget(self.discover_button, 3, 0)
        form.addWidget(self.new_button, 3, 1)
        form.addWidget(self.resume_button, 3, 2)
        form.addWidget(self.rename_button, 3, 3)
        layout.addLayout(form)
        self.cwd_label = label("Project: none", True)
        self.cwd_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.cwd_label)
        self.branch_label = label("Branch: —", True)
        layout.addWidget(self.branch_label)
        utilities = QHBoxLayout()
        utilities.setSpacing(4)
        utilities.addWidget(button("Raw", lambda: window.show_agent_events(agent)))
        utilities.addWidget(button("Logs", lambda: window.open_logs(agent)))
        utilities.addWidget(button("Files", window.open_project))
        utilities.addWidget(button("History", self.show_session_history))
        layout.addLayout(utilities)
        self.pending_review = button("Pending backend approval - Review...", self.review_pending_approval, f"pending_approval_{agent}")
        self.pending_review.setToolTip("A human must review and explicitly confirm this request. New events do not hide this reminder.")
        self.pending_review.hide()
        layout.addWidget(self.pending_review)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName(f"conversation_{agent}")
        self.transcript = QWidget()
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(0, 4, 0, 4)
        self.transcript_layout.setSpacing(7)
        self.empty = label("Your conversation will appear here.\nConnect when you are ready.", True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.transcript_layout.addWidget(self.empty)
        self.transcript_layout.addStretch()
        self.scroll.setWidget(self.transcript)
        layout.addWidget(self.scroll, 1)
        self.input = PromptEdit()
        self.input.setObjectName(f"input_{agent}")
        self.input.setPlaceholderText(f"Message {agent.title()}…  Ctrl+Enter to send")
        self.input.setMinimumHeight(66)
        self.input.setMaximumHeight(110)
        self.input.submit.connect(self.send)
        self.input.files_dropped.connect(self.add_attachments)
        layout.addWidget(self.input)
        self.attachment_label = label("", True)
        self.attachment_label.hide()
        layout.addWidget(self.attachment_label)
        controls = QHBoxLayout()
        self.attach_button = button("Attach", self.attach)
        self.clear_attach_button = button("Clear", self.clear_attachments)
        self.clear_attach_button.hide()
        controls.addWidget(self.attach_button)
        controls.addWidget(self.clear_attach_button)
        controls.addStretch()
        self.stop_button = button("Stop", self.stop, "stop")
        self.stop_button.setAccessibleName(f"Stop {agent.title()}")
        controls.addWidget(self.stop_button)
        self.send_button = button("Send", self.send, "primary")
        self.send_button.setAccessibleName(f"Send to {agent.title()}")
        controls.addWidget(self.send_button)
        layout.addLayout(controls)
        self.update_capabilities({})

    def connect_agent(self):
        if self.connection_state in ("Connected", "Busy"):
            if self.connection_state == "Busy":
                self.window.show_error("Stop the current turn before disconnecting.")
                return
            self.window.run(lambda: self.window.core.disconnect(self.agent), lambda _: self.window.refresh_agent(self.agent), self.agent)
        else:
            if self.agent == 'dot' and not self.dot_consent('connect'): return
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
            self.model.addItem("Managed by ChatGPT / dot" if self.agent == "dot" else "Default backend model", None)
        selected = self.model.findData(old)
        if selected < 0:
            saved = self.window.core.get_setting("agent." + self.agent, {}) or {}
            selected = self.model.findData(saved.get("default_model"))
        if selected >= 0:
            self.model.setCurrentIndex(selected)
        self.model.blockSignals(False)
        self.model.setEnabled(bool(models) and not self.monitor)
        self.model_changed()
        if cap.get("detail"):
            self.notice.setText(str(cap["detail"]))
            self.notice.setToolTip(str(cap["detail"]))
        self.update_controls()

    def model_changed(self):
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
            except Exception:
                efforts = []
        self.effort.clear()
        if self.capabilities.get("supports_effort"):
            for item in efforts:
                value = item if isinstance(item, str) else item.get("reasoningEffort") or item.get("effort") or item.get("id") or item.get("value")
                if value:
                    self.effort.addItem(str(value), value)
        available = self.effort.count() > 0
        if not available:
            self.effort.addItem("Managed by ChatGPT / dot" if self.agent == "dot" else "Unsupported / backend default", None)
        else:
            saved = self.window.core.get_setting("agent." + self.agent, {}) or {}
            index = self.effort.findData(saved.get("default_effort"))
            if index >= 0:
                self.effort.setCurrentIndex(index)
        self.effort.setEnabled(available and not self.monitor)
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
        self.connection_state = state
        self.state.setText(state)
        color = "#80cbaa" if state == "Connected" else "#e4bd73" if state in ("Busy", "Connecting") else "#f29f95" if state in ("Error", "Blocked") else "#9facbe"
        self.state.setStyleSheet(f"color: {color};")
        self.connect_button.setText("Disconnect" if state in ("Connected", "Busy") else ("Reconnect" if state in ("Error", "Offline") else f"Connect {self.agent.title()}"))
        self.update_controls()
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
        enabled = (self.window.core.get_setting("agent." + self.agent, {}) or {}).get("enabled", True)
        self.connect_button.setEnabled(enabled and not blocked and not busy and self.connection_state != "Connecting")
        self.send_button.setEnabled(ready and not blocked and not (self.attachments and not files_supported))
        self.send_button.setToolTip('Remove queued attachments or select a supported model before sending.' if self.attachments and not files_supported else 'Send message')
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
        if blocked:
            if self.connection_state != 'Error':
                self.state.setText("Blocked")
                self.notice.setText(cap.get("detail") or "Official dot bridge unavailable. History remains readable.")
            self.input.setPlaceholderText("Select G8毛 first. Unofficial integration; manual Refresh, no streaming.")
        elif not enabled:
            self.notice.setText("Agent disabled in Settings.")
        elif self.agent == 'dot':
            self.input.setPlaceholderText('Manual text send; Refresh reads replies. No streaming / server Stop.')

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
        self.attachment_label.setText("Attachments: " + ", ".join(Path(path).name for path in self.attachments))
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
            self.window.show_error("Create or select a task before sending a message.")
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
                item.widget().deleteLater()
        self.empty = label("No messages in this task yet.", True)
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

    def scroll_bottom(self):
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - bar.value() < 100:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))


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


class HandoffDialog(QDialog):
    def __init__(self, window, message, target):
        super().__init__(window)
        self.window, self.message, self.target = window, message, target
        self.setWindowTitle("Handoff preview — original content preserved")
        self.resize(760, 630)
        self.preview = window.core.prepare_handoff(identifier(message), target)
        layout = QVBoxLayout(self)
        layout.addWidget(label(f"{message.get('agent', '').title()} → {target.title()}", False))
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
        layout.addWidget(label("Automatic orchestration is OFF. Send requires this explicit confirmation.", True))
        actions = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.send_button = actions.addButton("Confirm and send", QDialogButtonBox.AcceptRole)
        self.send_button.setObjectName("handoff_send")
        ready = window.panels[target].connection_state == "Connected"
        self.send_button.setEnabled(ready)
        if not ready:
            layout.addWidget(label(f"{target.title()} is not connected. This preview has not been sent.", True))
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
        self.setWindowTitle("AI Collaboration Workspace")
        self.setObjectName("ai_collaboration_workspace")
        self.resize(1510, 940)
        self.setMinimumSize(640, 420)
        self.setStyleSheet(STYLE)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(17, 14, 17, 10)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        title = label("AI Collaboration Workspace")
        title.setObjectName("brand")
        title.setWordWrap(False)
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(label("LOCAL WORKSPACE  ·  AUTOMATION OFF", True))
        heading.addWidget(button("Settings", self.settings))
        heading.addWidget(button("Diagnostics", self.diagnostics))
        layout.addLayout(heading)
        context = QHBoxLayout()
        context.addWidget(label("Project", True))
        self.project_combo = QComboBox()
        self.project_combo.setObjectName("global_project")
        self.project_combo.setMinimumWidth(150)
        self.project_combo.currentIndexChanged.connect(self.project_changed)
        context.addWidget(self.project_combo, 1)
        context.addWidget(button("+ Project", self.new_project))
        context.addWidget(button("Sync to agents", self.sync_project, "sync_project"))
        context.addSpacing(12)
        context.addWidget(label("Task", True))
        self.task_combo = QComboBox()
        self.task_combo.setObjectName("global_task")
        self.task_combo.setMinimumWidth(170)
        self.task_combo.currentIndexChanged.connect(self.task_changed)
        context.addWidget(self.task_combo, 1)
        context.addWidget(button("+ Task", self.new_task))
        self.task_status = QComboBox()
        self.task_status.addItems(STATUSES)
        self.task_status.setObjectName("task_status")
        self.task_status.currentTextChanged.connect(self.status_changed)
        context.addWidget(self.task_status)
        layout.addLayout(context)
        navigation = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Workspace", "Monitor", "Timeline", "History"])
        self.mode.setObjectName("view_mode")
        self.mode.currentTextChanged.connect(self.change_mode)
        navigation.addWidget(self.mode)
        navigation.addWidget(button("Task notes", self.notes))
        navigation.addWidget(button("Compare", self.compare))
        navigation.addWidget(button("Diff / Tests", self.inspect_artifacts))
        navigation.addWidget(button("Export", self.export))
        self.handoff_mode = QComboBox()
        self.handoff_mode.setObjectName("handoff_mode")
        self.handoff_mode.addItems(["Assisted", "Manual"])
        saved_mode = str(self.core.get_setting("handoff.mode", "assisted")).title()
        self.handoff_mode.setCurrentText(saved_mode if saved_mode in ("Assisted", "Manual") else "Assisted")
        self.handoff_mode.setToolTip("Assisted: review a preview before sending. Manual: your Forward click sends original content and metadata directly. Automatic is OFF.")
        self.handoff_mode.currentTextChanged.connect(lambda value: self.core.set_setting("handoff.mode", value.lower()))
        navigation.addWidget(self.handoff_mode)
        self.flow_button = QToolButton()
        self.flow_button.setObjectName("collaboration_flow")
        self.flow_button.setText("Flow ▾")
        self.flow_button.setToolTip("Claude → Dot → Codex: two independent, explicit handoff steps")
        self.flow_button.setPopupMode(QToolButton.InstantPopup)
        flow_menu = QMenu(self.flow_button)
        flow_menu.aboutToShow.connect(lambda: self.populate_flow_menu(flow_menu))
        self.flow_button.setMenu(flow_menu)
        navigation.addWidget(self.flow_button)
        self.unfocus_button = button("← Three panels", lambda: self.focus_agent(None))
        self.unfocus_button.hide()
        navigation.addWidget(self.unfocus_button)
        navigation.addStretch()
        navigation.addWidget(button("Stop current task…", self.stop_task, "stop"))
        layout.addLayout(navigation)
        self.stack = QStackedWidget()
        self.splitter = QSplitter(Qt.Horizontal)
        self.panels = {agent: AgentPanel(agent, self) for agent in AGENTS}
        for panel in self.panels.values():
            self.splitter.addWidget(panel)
        self.splitter.setChildrenCollapsible(False)
        self.stack.addWidget(self.splitter)
        self.timeline = QTreeWidget()
        self.timeline.setHeaderLabels(["Time", "Agent", "Event", "Status", "Summary"])
        self.timeline.setAlternatingRowColors(True)
        self.timeline.itemDoubleClicked.connect(lambda item: self.show_detail("Event detail", item.data(0, Qt.UserRole)))
        self.stack.addWidget(self.timeline)
        self.history_page = self.build_history()
        self.stack.addWidget(self.history_page)
        layout.addWidget(self.stack, 1)
        self.footer = label("Ready · Agents connect only when requested · Per-user data", True)
        layout.addWidget(self.footer)
        # High-DPI secondary screens can have less logical space than the
        # three-column content. Keep every control reachable by scrolling,
        # instead of forcing the native window below the screen boundary.
        root.setMinimumSize(1070, 710)
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setObjectName("workspace_viewport")
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.NoFrame)
        self.workspace_scroll.setWidget(root)
        self.setCentralWidget(self.workspace_scroll)
        fullscreen = QAction("Fullscreen", self)
        fullscreen.setShortcut(QKeySequence("F11"))
        fullscreen.triggered.connect(lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen())
        self.addAction(fullscreen)
        escape = QAction("Return to three panels", self)
        escape.setShortcut(QKeySequence("Escape"))
        escape.triggered.connect(lambda: self.focus_agent(None))
        self.addAction(escape)
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

    def reload_context(self):
        self._loading = True
        try:
            project = self.core.current_project or {}
            task = self.core.current_task or {}
            self.project_combo.clear()
            self.project_combo.addItem("Select project…", None)
            projects = self.core.list_projects()
            for item in projects:
                self.project_combo.addItem(project_label(item, projects), identifier(item))
                self.project_combo.setItemData(self.project_combo.count()-1, plain(item), Qt.ToolTipRole)
            self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(identifier(project))))
            self.task_combo.clear()
            self.task_combo.addItem("Select task…", None)
            for item in self.core.list_tasks():
                if not project or item.get("project_id") == identifier(project):
                    self.task_combo.addItem(task_label(item, projects), identifier(item))
                    self.task_combo.setItemData(self.task_combo.count()-1, plain(item), Qt.ToolTipRole)
            self.task_combo.setCurrentIndex(max(0, self.task_combo.findData(identifier(task))))
            self.task_status.setCurrentText(task.get("status", "NEW"))
            self.task_status.setEnabled(bool(task))
            for agent, panel in self.panels.items():
                panel.clear_conversation()
                for message in self.core.messages(agent=agent):
                    if message.get("role") in ("user", "assistant"):
                        panel.add_message(message)
                for event in reversed(self.core.events(agent=agent, limit=100)):
                    if event.get("type") in ("tool_start", "tool_result", "command", "command_output", "file", "file_edit", "error", "test", "approval", "approval_request", "tool_approval"):
                        panel.add_event(event, historical=True)
                panel.cwd_label.setText(("Metadata only: " if agent == "dot" else "cwd: ") + (project.get("name", "None") if agent == "dot" else project.get(f"{agent}_cwd") or project.get("repo_path") or project.get("repo") or "Not selected"))
                panel.cwd_label.setToolTip(panel.cwd_label.text())
                panel.branch_label.setText("Branch: " + (task.get("branch") or project.get("active_branch") or "—"))
                self.refresh_agent(agent)
            if self.mode.currentText() == "Timeline":
                self.refresh_timeline()
            if self.mode.currentText() == "History":
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
        if self.mode.currentText() == "Monitor" and self._legacy_clock >= 10 and not self._legacy_busy and not self._close_pending:
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
                for agent in ("claude", "codex"):
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
            if event.get("task_id") and event.get("task_id") != current_task_id:
                continue
            if kind == "message_delta" and latest_delta.get(event.get("message_id")) != index:
                continue
            if panel and kind in ("approval_response", "approval_cancelled"):
                panel.resolve_pending_approval(event.get("request_id"))
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
            if self.mode.currentText() == "Timeline":
                self.add_timeline_event(event)
        error_panel=next((panel for panel in self.panels.values() if panel.connection_state=='Error'),None)
        self.footer.setText('Error · '+error_panel.agent+' · '+error_panel.notice.text() if error_panel else self.last_event)

    def new_project(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Create project")
        dialog.resize(640, 320)
        layout = QFormLayout(dialog)
        name, repo, branch, notes = QLineEdit(), QLineEdit(), QLineEdit(), QPlainTextEdit()
        name.setObjectName("project_name")
        repo.setObjectName("project_repo")
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(repo)
        row_layout.addWidget(button("Browse…", lambda: repo.setText(QFileDialog.getExistingDirectory(dialog, "Project directory") or repo.text())))
        layout.addRow("Name", name)
        layout.addRow("Repository / directory", row)
        layout.addRow("Default branch (optional)", branch)
        layout.addRow("Notes", notes)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addRow(actions)
        if dialog.exec() == QDialog.Accepted:
            if not name.text().strip() or not repo.text().strip():
                self.show_error("Project name and directory are required.")
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
            self.show_error("Create or select a project first.")
            return
        title, ok = QInputDialog.getText(self, "Create task", "Task title")
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
        drafts = [panel for panel in self.panels.values() if panel.input.toPlainText().strip() or panel.attachments]
        if drafts:
            answer = QMessageBox.question(self, "Unsent input", "Changing context clears unsent input and attachments. Continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return False
            for panel in drafts:
                panel.input.clear()
                panel.clear_attachments()
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
        if agent == self.focused_agent:
            agent = None
        self.focused_agent = agent
        for name, panel in self.panels.items():
            panel.setVisible(agent is None or name == agent)
        self.unfocus_button.setVisible(agent is not None)

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
            if self.handoff_mode.currentText() == "Manual":
                if self.panels[target].connection_state != "Connected":
                    self.show_error(f"{target.title()} is not connected. No handoff was sent.")
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
            reason = " · Blocked" if blocked else " · Connect target first" if state != "Connected" else " · No source response" if not messages else ""
            action = menu.addAction(f"Step {number}: latest {source.title()} → {target.title()}{reason}")
            action.setEnabled(bool(messages) and state == "Connected" and not blocked)
            if messages:
                action.triggered.connect(lambda checked=False, message=messages[-1], target=target: self.forward(message, target))
        menu.addSeparator()
        explanation = menu.addAction("Each step requires a user action · Automatic OFF")
        explanation.setEnabled(False)

    def stop_task(self):
        if QMessageBox.question(self, "Stop current task", "Request cancellation from all three adapters for the current task?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.run(lambda: self.core.stop_task(confirmed=True))

    def approve(self, event, approved):
        if approved:
            box = QMessageBox(QMessageBox.Question, "Backend tool approval", "", QMessageBox.Yes | QMessageBox.No, self)
            box.setTextFormat(Qt.PlainText)
            box.setText("Approve this specific backend request?")
            box.setDetailedText(plain(event))
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return
        request_id = event.get("request_id") or event.get("approval_id") or event.get("id")
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
        self.history_agent.addItems(["All agents", *AGENTS])
        self.history_agent.currentIndexChanged.connect(self.refresh_history)
        filters.addWidget(self.history_agent)
        self.history_status = QComboBox()
        self.history_status.addItems(["All statuses", *STATUSES])
        self.history_status.currentIndexChanged.connect(self.refresh_history)
        filters.addWidget(self.history_status)
        self.history_project = QCheckBox("Current project")
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
            self.history_agent.setCurrentText(agent)
        self.mode.setCurrentText("History")

    def refresh_history(self):
        if not hasattr(self, "history_table"):
            return
        self.history_table.clear()
        query = self.search.text().strip()
        filters = {}
        if self.history_agent.currentIndex():
            filters["agent"] = self.history_agent.currentText()
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
            self.run(lambda: self.core.select_task(identifier(row)), lambda _: (self.reload_context(), self.mode.setCurrentText("Workspace")))
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
        return f"Branch: {snapshot.get('branch') or '—'}  ·  Dirty: {snapshot.get('dirty', '—')}  ·  ↑{snapshot.get('ahead', '—')} ↓{snapshot.get('behind', '—')}"

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
        dialog.setWindowTitle("Settings")
        dialog.resize(800, 660)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        agent_page = QWidget()
        agent_layout = QVBoxLayout(agent_page)
        agent_layout.addWidget(label("Backend settings take effect on the next connection. Model and effort options come from the connected backend.", True))
        fields = {}
        for agent in AGENTS:
            form = QFormLayout()
            form.addRow(label(agent.upper()))
            diag = self.core.diagnostics(agent)
            saved = self.core.get_setting("agent." + agent, {}) or {}
            enabled = QCheckBox("Enabled")
            enabled.setObjectName(f"default_enabled_{agent}")
            enabled.setChecked(saved.get("enabled", True))
            executable = QLineEdit(saved.get("executable", diag.get("executable", "")))
            executable.setObjectName(f"executable_{agent}")
            timeout = QSpinBox()
            timeout.setObjectName(f"timeout_{agent}")
            timeout.setRange(5, 3600)
            timeout.setValue(int(saved.get("timeout", 120)))
            model, effort, project = QComboBox(), QComboBox(), QComboBox()
            model.setObjectName(f"default_model_{agent}")
            effort.setObjectName(f"default_effort_{agent}")
            project.setObjectName(f"default_project_{agent}")
            model.addItem("Default backend model", None)
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
                effort.addItem("Backend default / Unsupported", None)
                if self.core.capabilities(agent).get("supports_effort"):
                    for choice in self.core.list_efforts(agent, model.currentData()):
                        value = choice if isinstance(choice, str) else choice.get("reasoningEffort") or choice.get("effort") or choice.get("value")
                        if value:
                            effort.addItem(str(value), value)
                effort.setEnabled(effort.count() > 1)
                effort.setCurrentIndex(max(0, effort.findData(saved.get("default_effort"))))
            model.currentIndexChanged.connect(set_efforts)
            set_efforts()
            project.addItem("Current workspace project", None)
            for item in self.core.list_projects():
                project.addItem(project_label(item, self.core.list_projects()), identifier(item))
            project.setCurrentIndex(max(0, project.findData(saved.get("default_project"))))
            form.addRow("", enabled)
            form.addRow("Backend", label(diag.get("backend", "Unknown"), True))
            form.addRow("Executable", executable)
            form.addRow("Timeout (seconds)", timeout)
            form.addRow("Default model", model)
            form.addRow("Default effort", effort)
            form.addRow("Default project", project)
            form.addRow("Streaming", label("Enabled when backend supports streaming (required)", True))
            form.addRow("Raw log", label("Safety-filtered audit always enabled (required)", True))
            agent_layout.addLayout(form)
            fields[agent] = (saved, enabled, executable, timeout, model, effort, project)
        agent_scroll = QScrollArea()
        agent_scroll.setWidgetResizable(True)
        agent_scroll.setWidget(agent_page)
        tabs.addTab(agent_scroll, "Agents")
        for name, text in (
            ("Projects", "Use the project selector to choose a working directory. Sync sets Claude and Codex cwd; dot receives metadata only. Git integration is read only."),
            ("Logs", "Raw JSONL and structured events are retained locally. Safety filtering redacts credentials and excludes hidden reasoning before persistence. Open per-agent logs from each panel."),
            ("Permissions", "Original backend permission and sandbox settings remain authoritative. Tool approval requires an explicit user action. Automatic approval and sandbox bypass are not available."),
            ("Advanced", "Automatic orchestration: OFF\nNo agents connect automatically at startup. Unsupported capabilities remain unavailable. Use Diagnostics for executable, backend, session, cwd, last event and last error."),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(label(text))
            page_layout.addStretch()
            tabs.addTab(page, name)
        paths = QWidget()
        paths_form = QFormLayout(paths)
        paths_form.addRow("Application data", label(str(getattr(self.core, "data_dir", "Per-user app data")), True))
        legacy_root = QLineEdit(self.core.get_setting("legacy.root", r"C:\Users\ryant\Desktop\AI-Collab-Monitor"))
        paths_form.addRow("Legacy Monitor root", legacy_root)
        paths_form.addRow(label("Monitor reads the existing four log files incrementally. It does not write, reset or control the original Monitor sessions.", True))
        tabs.addTab(paths, "Paths")
        appearance = QWidget()
        appearance_layout = QVBoxLayout(appearance)
        topmost = QCheckBox("Always on top")
        topmost.setChecked(self.core.get_setting("ui.always_on_top", False))
        appearance_layout.addWidget(topmost)
        appearance_layout.addWidget(label("F11 toggles fullscreen. Double-click an agent heading to focus it. Window position and size are restored across launches.", True))
        appearance_layout.addStretch()
        tabs.addTab(appearance, "Appearance")
        retention = QWidget()
        retention_form = QFormLayout(retention)
        days, size = QSpinBox(), QSpinBox()
        days.setRange(1, 3650)
        size.setRange(1, 1024)
        days.setValue(int(self.core.get_setting("retention.days", 90)))
        size.setValue(int(self.core.get_setting("retention.max_mb", 20)))
        archive = QCheckBox("Archive rotated logs")
        archive.setChecked(self.core.get_setting("retention.archive", True))
        retention_form.addRow("Retention days", days)
        retention_form.addRow("Maximum raw log size (MB)", size)
        retention_form.addRow(archive)
        tabs.addTab(retention, "Retention")
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() == QDialog.Accepted:
            for agent, (saved, enabled, executable, timeout, model, effort, project) in fields.items():
                values = dict(saved, enabled=enabled.isChecked(), executable=executable.text().strip(), timeout=timeout.value(), default_project=project.currentData())
                if model.isEnabled():
                    values["default_model"] = model.currentData()
                if effort.isEnabled():
                    values["default_effort"] = effort.currentData()
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
                    QTimer.singleShot(100, ready_to_close)
                    return
                self._close_pending = False
                self.close()
            def cancelled(_):
                QTimer.singleShot(0, ready_to_close)
            def failed(_):
                self._close_pending = False
            self.run(lambda: self.core.stop_task(confirmed=True), cancelled, on_error=failed)
            event.ignore()
            return
        self.core.set_setting("ui.geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.timer.stop()
        self._closed = True
        event.accept()
