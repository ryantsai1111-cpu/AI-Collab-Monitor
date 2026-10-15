"""Native desktop workspace. All backend interaction passes through WorkspaceCore.

Qt workers isolate backend handshakes and requests from the GUI thread. This module
never spawns a shell, reads credentials, or creates an agent session on startup.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from .presentation import (session_identity, session_display, local_session_displays,
                           project_label, task_label, compact)
from . import approvals
from .orchestrator import Orchestrator
from .monitor import AgentRail, MonitorDashboard, collect_snapshot
from .theme import (CODE_BLOCK_BG, CODE_INLINE_BG, CODE_INLINE_FG, EVENT_COLOR, HEADING_COLOR, MUTED_COLOR,
                    STATE_COLORS, STATE_IDLE, build_style, console_palette)

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QUrl, QByteArray
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QKeySequence, QPixmap, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextFormat)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton, QTreeWidget, QTabBar,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

# Same folder as run.py: the monitor lives inside the repository, not on the Desktop.
LEGACY_MONITOR_ROOT = str(Path(__file__).resolve().parents[1] / "AI-Collab-Monitor")
AGENTS = ("claude", "dot", "codex", "local")
STATUSES = ("NEW", "PLANNING", "REVIEWING", "READY", "IMPLEMENTING", "VERIFYING",
            "WAITING_USER", "BLOCKED", "DONE", "FAILED", "CANCELLED")
ROLE_NAMES = {"claude": "Claude", "dot": "G8毛", "codex": "Codex", "local": "Hermes"}
ROLE_LABELS = {"claude": "協作 agent", "dot": "轉接／複核", "codex": "協作 agent", "local": "Hermes agent"}
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


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]|[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Shown inline in a conversation. Everything else stays in the timeline, raw events and logs.
TRANSCRIPT_EVENTS = ("tool_start", "tool_result", "tool", "command", "command_output", "file", "file_edit", "diff",
                     "test", "error", "handoff", "stop", "recovery", "approval", "approval_request", "tool_approval")
APPROVAL_EVENTS = ("approval", "approval_request", "tool_approval")
EVENT_LABELS = {"tool_start": "工具", "tool_result": "工具結果", "tool": "工具", "command": "指令", "command_output": "輸出",
                "file": "檔案", "file_edit": "編輯", "diff": "差異", "test": "測試", "error": "錯誤", "handoff": "交接",
                "stop": "停止", "recovery": "復原", "approval": "核准", "approval_request": "核准", "tool_approval": "核准"}


def chat_markdown(text):
    """Keep the author's line breaks: outside code fences a single newline becomes a hard break."""
    lines, fenced, result = text.split("\n"), False, []
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        following = lines[index + 1] if index + 1 < len(lines) else ""
        soft = not fenced and line.strip() and following.strip() and not line.lstrip().startswith(("```", "~~~", "|", "#"))
        result.append(line.rstrip() + "  " if soft else line)
    return "\n".join(result)


class MessageBody(QTextBrowser):
    """Read-only rendered message that grows to fit its content instead of scrolling inside the transcript."""
    def __init__(self):
        super().__init__()
        self.setObjectName("message_body")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.document().setDocumentMargin(2)

    def loadResource(self, kind, name):
        return None  # never load images or any other resource a message refers to

    def fit(self):
        width = self.viewport().width()
        if width > 0:
            self.document().setTextWidth(width)
        self.setFixedHeight(int(self.document().size().height()) + 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def wheelEvent(self, event):
        event.ignore()  # the transcript scrolls, not the message

    def render(self, text, markdown):
        if not markdown:
            self.setPlainText(text)
        else:
            # Raw HTML in a message is shown literally, never interpreted.
            self.document().setMarkdown(chat_markdown(text), QTextDocument.MarkdownDialectGitHub | QTextDocument.MarkdownNoHTML)
            block = self.document().begin()
            while block.isValid():
                cursor = QTextCursor(block)
                if block.blockFormat().hasProperty(QTextFormat.BlockCodeFence) or block.blockFormat().hasProperty(QTextFormat.BlockCodeLanguage):
                    shaded = block.blockFormat()
                    shaded.setBackground(QColor(CODE_BLOCK_BG))
                    shaded.setLeftMargin(8)
                    shaded.setRightMargin(8)
                    cursor.setBlockFormat(shaded)
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                    mono = QTextCharFormat()
                    mono.setFontFamilies(["Cascadia Mono", "Consolas"])
                    mono.setForeground(QColor(EVENT_COLOR))
                    cursor.mergeCharFormat(mono)
                else:
                    if block.textList() is None:
                        spaced = block.blockFormat()
                        spaced.setBottomMargin(7)
                        cursor.setBlockFormat(spaced)
                    part = block.begin()
                    while not part.atEnd():
                        fragment = part.fragment()
                        if fragment.isValid() and fragment.charFormat().fontFixedPitch():
                            cursor.setPosition(fragment.position())
                            cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.KeepAnchor)
                            inline = QTextCharFormat()
                            inline.setBackground(QColor(CODE_INLINE_BG))
                            inline.setForeground(QColor(CODE_INLINE_FG))
                            inline.setFontFamilies(["Cascadia Mono", "Consolas"])
                            cursor.mergeCharFormat(inline)
                        part += 1
                block = block.next()
        self.fit()


class MessageCard(QFrame):
    """Rendered response plus explicit actions; the stored source text is never rewritten."""
    def __init__(self, message, panel):
        super().__init__()
        self.message = dict(message)
        self.panel = panel
        role = message.get("role", "assistant")
        self.role = role
        self.setObjectName("message_user" if role == "user" else "message")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 7) if role == "user" else layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(3)
        self.body = MessageBody()
        self.body.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 14px;")
        layout.addWidget(self.body)
        footer = QHBoxLayout()
        footer.setSpacing(2)
        stamp = str(message.get("timestamp", ""))
        try:
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
        except ValueError:
            stamp = stamp[11:16] if "T" in stamp else stamp
        self.heading = label(("你" if role == "user" else panel.window.role_names.get(panel.agent, role)) + " · " + stamp, True)
        self.heading.setObjectName("message_meta")
        self.heading.setWordWrap(False)
        footer.addWidget(self.heading)
        footer.addStretch()
        if role == "assistant" and panel.agent != "dot":
            self.forward_button = QToolButton()
            self.forward_button.setObjectName("ghost")
            self.forward_button.setText("轉交")
            self.forward_button.setPopupMode(QToolButton.InstantPopup)
            targets = QMenu(self.forward_button)
            def populate_targets():
                targets.clear()
                for target in panel.window.agents:
                    if target != panel.agent:
                        targets.addAction(panel.window.role_names[target], lambda checked=False, target=target: panel.window.forward(self.message, target))
            populate_targets()
            targets.aboutToShow.connect(populate_targets)
            self.forward_button.setMenu(targets)
            footer.addWidget(self.forward_button)
        menu_button = QToolButton()
        menu_button.setObjectName("ghost")
        menu_button.setText("⋯")
        menu_button.setToolTip("複製、原始事件與轉交")
        menu_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(menu_button)
        menu.addAction("Copy", lambda: self.copy(False))
        menu.addAction("複製含中繼資料", lambda: self.copy(True))
        menu.addAction("檢視原始事件", lambda: panel.window.open_raw(self.message))
        if role == "assistant" and panel.agent != "dot":
            menu.addSeparator()
            forward_actions = []
            def populate_more_targets():
                for action in forward_actions:
                    menu.removeAction(action)
                    action.deleteLater()
                forward_actions.clear()
                for target in panel.window.agents:
                    if target != panel.agent:
                        forward_actions.append(menu.addAction(f"轉交給 {panel.window.role_names[target]}…", lambda checked=False, target=target: panel.window.forward(self.message, target)))
            populate_more_targets()
            menu.aboutToShow.connect(populate_more_targets)
        menu_button.setMenu(menu)
        footer.addWidget(menu_button)
        layout.addLayout(footer)
        self.update_content(message.get("content", ""))

    def update_content(self, content):
        self.message["content"] = content
        cursor = self.body.textCursor()
        start, end = cursor.anchor(), cursor.position()
        display = plain(content)
        if not display and self.message.get('agent') == 'dot':
            display = '〔此訊息沒有文字內容；附件或其他非文字內容尚未支援顯示〕'
        self.body.render(display, self.role == "assistant")
        size = len(self.body.toPlainText())
        cursor = self.body.textCursor()
        cursor.setPosition(min(start, size))
        cursor.setPosition(min(end, size), QTextCursor.KeepAnchor)
        self.body.setTextCursor(cursor)

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
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(2)
        kind = event.get("type", "event")
        self.kind = kind
        summary = (event.get("command") or event.get("tool") or event.get("summary") or event.get("name")
                   or (event.get("content") if kind == "error" else "") or event.get("status", ""))
        if event.get("imported") and event.get("tool") and event.get("summary") and not event.get("command"):
            summary = f"{event['tool']} · {event['summary']}"
        request = approvals.describe(event.get("details")) if kind in APPROVAL_EVENTS else None
        if request:
            summary = request["tool"] + " · " + (request["command"] or request["path"] or "")
        summary = ANSI_ESCAPE.sub("", str(summary)).strip()
        self.toggle = QToolButton()
        self.toggle.setText(f"{EVENT_LABELS.get(kind, kind.replace('_', ' '))}  {(summary.splitlines() or [''])[0][:100]}")
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.RightArrow)
        # A long command must not widen the transcript past its viewport.
        self.toggle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.toggle.setToolTip(summary[:600])
        self.toggle.setCheckable(True)
        self.toggle.setStyleSheet(f"text-align: left; border: none; background: transparent; padding: 3px 2px; color: {'#ff9a90' if kind == 'error' else EVENT_COLOR};")
        layout.addWidget(self.toggle)
        detail = dict(event)
        if "output" in detail and (detail.get("output_stream") == "combined" or not ("stdout" in detail or "stderr" in detail)):
            detail["output_stream"] = "Combined output supplied by backend; stdout/stderr separation unavailable."
        if request:
            # The command or file as the backend will run it, not a JSON dump of it.
            readable = request["command"] or request["path"] or plain(event.get("details") or {})
            self.body = QPlainTextEdit(ANSI_ESCAPE.sub("", request["tool"] + "\n\n" + readable))
        elif kind == "error" and isinstance(event.get("content"), str):
            self.body = QPlainTextEdit(ANSI_ESCAPE.sub("", event["content"]).strip())
        else:
            self.body = QPlainTextEdit(ANSI_ESCAPE.sub("", plain(detail)))
        self.body.setReadOnly(True)
        self.body.setFont(QFont("Consolas", 9))
        self.body.setMaximumHeight(300)
        self.body.hide()
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self.set_expanded)
        self.approval_actions = []
        self.historical = historical
        self.approval_resolved = False
        if kind in APPROVAL_EVENTS:
            self.setObjectName("event_approval")
            actions = QHBoxLayout()
            actions.addStretch()
            self.approval_actions = [button("Deny", lambda: window.approve(event, False)),
                                     button("核准", lambda: window.approve(event, True, confirm=False))]
            key = approvals.rule_key(request)
            if key:
                always = button("一律允許 " + approvals.rule_label(key), lambda: window.allow_always(event, key))
                always.setToolTip("這次連線期間，同一個程式或工具不再詢問；危險操作仍會問")
                self.approval_actions.append(always)
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


class ActivityGroup(QFrame):
    """Consecutive tool activity folded into one line, like the desktop apps do."""
    CATEGORIES = (("指令", ("command", "command_output")), ("檔案變更", ("file", "file_edit", "diff")),
                  ("測試", ("test",)), ("錯誤", ("error",)))

    def __init__(self):
        super().__init__()
        self.setObjectName("activity")
        self.cards = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(0)
        self.toggle = QToolButton()
        self.toggle.setObjectName("activity_toggle")
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setCheckable(True)
        self.toggle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.toggle.toggled.connect(self.set_expanded)
        layout.addWidget(self.toggle)
        self.inner = QWidget()
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(10, 0, 0, 2)
        self.inner_layout.setSpacing(0)
        self.inner.hide()
        layout.addWidget(self.inner)

    def add(self, card):
        self.cards.append(card)
        self.inner_layout.addWidget(card)
        counts, other = [], len(self.cards)
        for title, kinds in self.CATEGORIES:
            number = sum(card.kind in kinds for card in self.cards)
            other -= number
            if number:
                counts.append(f"{title} {number}")
        if other:
            counts.append(f"工具 {other}")
        self.toggle.setText(" · ".join(counts))
        failed = any(card.kind == "error" for card in self.cards)
        self.toggle.setStyleSheet(f"text-align: left; border: none; background: transparent; padding: 4px 2px; color: {'#ff9a90' if failed else MUTED_COLOR};")

    def set_expanded(self, expanded):
        self.inner.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.updateGeometry()


class AgentPanel(QFrame):
    def __init__(self, agent, window):
        super().__init__()
        self.agent, self.window = agent, window
        self.provider = window.core.provider(agent)
        self.capabilities = {}
        self.cards = {}
        self.approvals = {}
        self.pending_approval_events = {}
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
        from .adapters.dot import DISCLOSURE
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
        color = STATE_COLORS.get(state, STATE_IDLE)
        self.state.setStyleSheet(f"color: {color};")
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
                self.notice.setText(error)
                self.notice.setToolTip(error)

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
        self.send_button.setText('新對話並傳送' if legacy else BUTTON_LABELS['Send'])
        feedback = '傳送失敗：' + self.send_error if self.send_error else ''
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
        if self.agent == 'dot' and self.connection_state == 'Error':
            error=getattr(self.window.core.adapters.get('dot'),'last_error','')
            if error: self.notice.setText(error);self.notice.setToolTip(error)

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
        if self.agent == 'dot':
            if self.window.orchestrator and self.window.orchestrator.active:
                self.window.show_error('請先結束自動協作，再傳送持續對話訊息。');return
            if not self.dot_consent('send'): return
        self.send_error = ''
        self.set_state("Busy")
        self.input.clear()
        self.clear_attachments()
        def failed(message):
            from .security import sanitize
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
            self.window.core.prepare_conversation(self.agent, fresh=bool(legacy))
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
        self.window, self.task_id = window, task_id or identifier(window.view_task() or {})
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
        task = self.window.core.get_task(self.task_id) or {}
        project = self.window.core.get_project(task.get('project_id')) or {}
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


class SessionNavigator(QWidget):
    """Sidebar list of locally saved Claude desktop and Codex conversations, grouped by repository.

    Nothing is read until this page is first shown. Rename and archive are kept in this
    workspace's own settings; the source apps' files are never written."""
    SOURCES = (("Claude", "claude"), ("Codex", "codex"))

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.sessions = {agent: None for _, agent in self.SOURCES}
        self.collapsed = set()
        self.loading = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._agent = window._preferred_agent
        self.empty = label("此 agent 沒有本機歷史對話", True)
        layout.addWidget(self.empty)
        self.nav_all_projects = QCheckBox("顯示全部專案")
        self.nav_all_projects.setObjectName("nav_all_projects")
        self.nav_all_projects.toggled.connect(self.fill)
        layout.addWidget(self.nav_all_projects)
        self.search = QLineEdit()
        self.search.setObjectName("nav_search")
        self.search.setPlaceholderText("搜尋對話或專案…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.fill)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setObjectName("nav_tree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(12)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.ElideRight)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(lambda point: self.menu.exec(self.tree.viewport().mapToGlobal(point)))
        self.tree.currentItemChanged.connect(lambda *_: self.selection_changed())
        self.tree.itemClicked.connect(self.toggle_group)
        self.tree.itemActivated.connect(lambda *_: self.open_selected(True))
        layout.addWidget(self.tree, 1)
        self.status = label("", True)
        self.status.setObjectName("nav_status")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.open_button = button("接續對話", lambda: self.open_selected(True), "primary")
        self.open_button.setToolTip("切換到該專案、載入紀錄並接續同一個對話（也可按兩下）")
        actions.addWidget(self.open_button, 1)
        self.more = QToolButton()
        self.more.setText("⋯")
        self.more.setAccessibleName("對話操作")
        self.more.setPopupMode(QToolButton.InstantPopup)
        self.menu = QMenu(self.more)
        self.load_action = self.menu.addAction("只載入紀錄", lambda: self.open_selected(False))
        self.new_action = self.menu.addAction("在此專案開新對話", self.new_conversation)
        self.menu.addSeparator()
        self.rename_action = self.menu.addAction("重新命名…", self.rename)
        self.archive_action = self.menu.addAction("封存", self.toggle_archive)
        self.menu.addSeparator()
        self.archived_action = self.menu.addAction("顯示已封存與系統對話")
        self.archived_action.setCheckable(True)
        self.archived_action.toggled.connect(self.fill)
        self.refresh_action = self.menu.addAction("重新整理", self.load)
        self.more.setMenu(self.menu)
        actions.addWidget(self.more)
        layout.addLayout(actions)
        self.selection_changed()

    @property
    def agent(self):
        return self.window.core.provider(self._agent)

    def set_agent(self, agent):
        if agent != self._agent:
            self.tree.clear()
        self._agent = agent
        supported = self.agent in self.sessions
        self.empty.setVisible(not supported)
        for widget in (self.search, self.tree, self.nav_all_projects, self.open_button, self.more):
            widget.setVisible(supported)
        if supported:
            if self.isVisible() and not self.window._loading:
                self.ensure_loaded()
            else:
                self.fill()
        else:
            self.tree.clear()
            self.status.setText("")
            self.selection_changed()

    def showEvent(self, event):
        super().showEvent(event)
        self.set_agent(self._agent)

    def ensure_loaded(self):
        if self.agent not in self.sessions:
            return
        if self.sessions[self.agent] is None:
            self.load()
        else:
            self.fill()

    def load(self):
        agent = self.agent
        if agent not in self.sessions or agent in self.loading:
            return
        self.loading.add(agent)
        self.status.setText("正在讀取對話清單…")
        def failed(error):
            self.loading.discard(agent)
            if self.agent == agent:
                self.status.setText("無法讀取對話清單：" + error)
        self.window.run(lambda: self.window.core.desktop_sessions(agent), lambda rows: self.set_sessions(agent, rows), on_error=failed)

    def set_sessions(self, agent, rows):
        self.loading.discard(agent)
        self.sessions[agent] = list(rows or [])
        if agent == self.agent:
            self.fill()

    @staticmethod
    def when(value):
        try:
            moment = datetime.fromisoformat(value).astimezone()
        except (TypeError, ValueError):
            return ""
        minutes = (datetime.now().astimezone() - moment).total_seconds() / 60
        if minutes < 1:
            return "剛剛"
        if minutes < 60:
            return f"{int(minutes)} 分"
        if minutes < 1440:
            return f"{int(minutes // 60)} 小時"
        if minutes < 10080:
            return f"{int(minutes // 1440)} 天"
        return moment.strftime("%m-%d")

    def title_of(self, session):
        if session["title"].startswith("（未命名"):
            return "未命名對話 " + self.when(session["created"] or session["last_activity"])
        return session["title"]

    def fill(self, *_):
        from .desktop_sessions import group_by_project
        agent, query = self.agent, self.search.text().casefold().strip()
        selected = (self.selected() or {}).get("id")
        if agent not in self.sessions:
            return
        current = (self.window.core.agent_task(self._agent) or {}).get(self._agent + "_session")
        directory = (self.window.core.agent_project(self._agent) or {}).get('repo_path')
        self.nav_all_projects.setEnabled(bool(directory))
        normalize = lambda path: os.path.normcase(os.path.normpath(str(Path(path).resolve())))
        rows = self.sessions[agent] or []
        if directory and not self.nav_all_projects.isChecked():
            rows = [row for row in rows if normalize(row['cwd']) == normalize(directory)]
        self.tree.clear()
        shown, focus = 0, None
        for group in group_by_project(rows):
            rows = [s for s in group["sessions"] if (self.archived_action.isChecked() or not (s["archived"] or s.get("system")))
                    and (not query or query in (s["title"] + " " + group["name"] + " " + s["cwd"]).casefold())]
            if not rows:
                continue
            key = rows[0].get("project_key") or group["cwd"]
            parent = QTreeWidgetItem(["", str(len(rows))])
            parent.setData(0, Qt.UserRole, {"kind": "project", "key": key, "name": group["name"], "agent": agent,
                                            "cwd": group["cwd"], "cwd_exists": group["cwd_exists"]})
            parent.setToolTip(0, group["cwd"])
            heading = parent.font(0)
            heading.setBold(True)
            parent.setFont(0, heading)
            parent.setForeground(1, QColor(MUTED_COLOR))
            self.tree.addTopLevelItem(parent)
            for session in rows:
                child = QTreeWidgetItem([self.title_of(session) + ("（已封存）" if session["archived"] else ""),
                                         self.when(session["last_activity"])])
                child.setData(0, Qt.UserRole, dict(session, kind="session"))
                child.setToolTip(0, session["title"] + "\n" + session["cwd"] + ("" if session["cwd_exists"] else "\n資料夾已不存在"))
                child.setForeground(1, QColor(MUTED_COLOR))
                if not session["cwd_exists"] or session["archived"]:
                    child.setForeground(0, QColor(MUTED_COLOR))
                if session["id"] == current:
                    font = child.font(0)
                    font.setBold(True)
                    child.setFont(0, font)
                    child.setForeground(0, QColor(HEADING_COLOR))
                parent.addChild(child)
                if session["id"] == (selected or current):
                    focus = child
            parent.setExpanded(bool(query) or key not in self.collapsed)
            self.label_group(parent)
            shown += len(rows)
        if focus is not None:
            self.tree.setCurrentItem(focus)
        if self.sessions[agent] is None:
            self.status.setText("")
        else:
            self.status.setText(f"{shown} 個對話" if self.sessions[agent] else "這台電腦上沒有找到本機對話")
        self.selection_changed()

    @staticmethod
    def label_group(item):
        item.setText(0, ("▾ " if item.isExpanded() else "▸ ") + item.data(0, Qt.UserRole)["name"])

    def toggle_group(self, item, _column=0):
        record = item.data(0, Qt.UserRole) or {}
        if record.get("kind") != "project":
            return
        item.setExpanded(not item.isExpanded())
        (self.collapsed.discard if item.isExpanded() else self.collapsed.add)(record["key"])
        self.label_group(item)

    def selected(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def selection_changed(self):
        record = self.selected() or {}
        session = record.get("kind") == "session"
        usable = self.agent in self.sessions and bool(record.get("cwd_exists")) and self.window.mode.currentData() != "Monitor"
        self.open_button.setEnabled(usable and session)
        self.load_action.setEnabled(usable and session)
        self.new_action.setEnabled(usable)
        self.rename_action.setEnabled(session)
        self.archive_action.setEnabled(session)
        self.archive_action.setText("取消封存" if record.get("archived") else "封存")

    def open_selected(self, resume):
        record = self.selected() or {}
        if record.get("kind") == "session" and self.open_button.isEnabled():
            self.window.open_desktop_session(dict(record, agent=self._agent), resume)

    def new_conversation(self):
        record = self.selected() or {}
        if self.new_action.isEnabled():
            self.window.new_desktop_conversation(record["cwd"], self._agent)

    def _override(self, record, **changes):
        agent = record.get("agent", self.agent)
        def done(_):
            self.window.reload_context()
            self.load()
        self.window.run(lambda: self.window.core.set_desktop_override(agent, record["id"], **changes), done)

    def rename(self):
        record = self.selected() or {}
        if record.get("kind") != "session":
            return
        title, ok = QInputDialog.getText(self, "重新命名對話", "名稱（留空則恢復原名；只影響這個程式）", text=record["title"])
        if ok:
            self._override(record, title=title.strip())

    def toggle_archive(self):
        record = self.selected() or {}
        if record.get("kind") == "session":
            self._override(record, archived=not record.get("archived"))


class HandoffDialog(QDialog):
    def __init__(self, window, message, target):
        super().__init__(window)
        self.window, self.message, self.target = window, message, target
        self.setWindowTitle("Handoff preview — original content preserved")
        self.resize(760, 630)
        self.preview = window.core.prepare_handoff(identifier(message), target)
        layout = QVBoxLayout(self)
        layout.addWidget(label(f"{self.window.role_names.get(message.get('agent'), message.get('agent', ''))} → {self.window.role_names[target]}", False))
        task = window.core.get_task(self.preview['task_id']) or {}
        project = window.core.get_project(self.preview['project_id']) or {}
        projects = window.core.list_projects()
        layout.addWidget(label(f"任務：{task_label(task, projects)}\n專案：{project_label(project, projects)}\nBranch: {task.get('branch', '')}", True))
        target_task = window.core.agent_task(target) or {}
        target_project = window.core.agent_project(target) or {}
        layout.addWidget(label(f"接收任務：{task_label(target_task, projects)}\n接收專案：{project_label(target_project, projects)}", True))
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
            layout.addWidget(label(f"{self.window.role_names[target]} 尚未連線。此預覽尚未傳送。", True))
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
        QApplication.instance().setPalette(console_palette())
        self.setStyleSheet(build_style("hacker"))
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
        self.workspace_views = QTabBar()
        self.workspace_views.setObjectName('workspace_views')
        self.workspace_views.setAccessibleName('工作台與協作總覽')
        self.workspace_views.setDrawBase(False)
        self.workspace_views.addTab('工作台')
        self.workspace_views.addTab('協作總覽')
        self.workspace_views.currentChanged.connect(self.select_workspace_view)
        self.workspace_views.tabBarClicked.connect(self.select_workspace_view)
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
                               ("設定…", self.settings),
                               ("診斷…", self.diagnostics), ("停止全部 Agent…", self.stop_task)):
            menu.addAction(text, callback)
        workspace_menu.setMenu(menu)
        heading.addWidget(workspace_menu)
        layout.addLayout(heading)
        self.orchestrator = None
        self.run_bar = QFrame()
        self.run_bar.setObjectName("run_bar")
        run_row = QHBoxLayout(self.run_bar)
        run_row.setContentsMargins(12, 6, 8, 6)
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
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(8)
        self.sidebar_agent_title = label(self.role_names[self._preferred_agent])
        self.sidebar_agent_title.setObjectName('console_section')
        side.addWidget(self.sidebar_agent_title)
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
        records.setSpacing(8)
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
        content_layout.setSpacing(8)
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
        chat_layout.setSpacing(10)
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
        self._monitor_clock = 0.0
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
        # Follow conversations that the desktop apps keep writing to while they are shown here.
        self._sync_stamp, self._sync_floor, self._syncing = {}, {}, set()
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.sync_local_conversations)
        self.sync_timer.start(3000)
        QTimer.singleShot(0, self, self.update_workspace_layout)
        self.refresh_monitor()

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
            self.sidebar_agent_title.setText(self.role_names[agent] + ' · ' + ROLE_LABELS[self.core.provider(agent)] + '\n' + state)
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
                panel._restoring_view = True
                panel.clear_conversation()
                shown = TRANSCRIPT_EVENTS
                transcript_messages=self.core.dot_conversation_messages(limit=panel.dot_visible_limit) if agent=="dot" else self.core.messages(agent=agent)
                history = [(str((message.get("metadata") or {}).get("native_timestamp") or message.get("timestamp") or ""), 0, message) for message in transcript_messages
                           if message.get("role") in ("user", "assistant")]
                history += [(str(event.get("timestamp") or ""), 1, event) for event in reversed(self.core.events(agent=agent, limit=400))
                            if agent != "dot" and event.get("type") in shown]
                # Stable sort: equal timestamps keep messages before events, as before.
                for _, is_event, row in (history if agent == "dot" else sorted(history, key=lambda entry: entry[:2])):
                    if is_event:
                        pending_id = row.get("request_id") or (row.get("payload") or {}).get("request_id")
                        panel.add_event(row, historical=pending_id not in view.get("pending", {}))
                    else:
                        panel.add_message(row)
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
                panel.notice.setText(diag["last_error"])
                panel.notice.setToolTip(diag["last_error"])
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
        if self.details_toggle.isChecked():
            self.refresh_work_details()
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
        from .desktop_sessions import history_stamp
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
        from .adapters.dot import DISCLOSURE
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
        self.workspace_views.blockSignals(True)
        self.workspace_views.setCurrentIndex(1 if mode == 'Monitor' else 0)
        self.workspace_views.blockSignals(False)
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
        from .adapters.hermes import HermesAdapter
        values = self.hermes_field_values(fields)
        trigger.setEnabled(False)
        output.setText('檢查中…（只讀取 CLI help，不傳送訊息）')
        def probe():
            from .security import redact_text
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
        from .adapters.hermes import hermes_settings
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
        self.sync_timer.stop()
        self.run_timer.stop()
        if self.orchestrator and self.orchestrator.active:
            self.orchestrator.stop('工作區視窗已關閉')
        self._closed = True
        event.accept()
