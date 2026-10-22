"""Shared helpers and conversation widgets."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from .. import approvals
from ..theme import CODE_BLOCK_BG, CODE_INLINE_BG, CODE_INLINE_FG, EVENT_COLOR, MUTED_COLOR

from PySide6.QtCore import Qt, Signal, QObject, QRunnable
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


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


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]|[\x00-\x08\x0b\x0c\x0e-\x1f]")



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
