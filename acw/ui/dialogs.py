"""Dialogs used by the workspace windows."""
from __future__ import annotations

from ..presentation import session_identity, session_display, local_session_displays, project_label, task_label
from .. import playbooks

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .widgets import button, identifier, label, plain


class PlaybookDialog(QDialog):
    """Edit persisted per-instance instructions without contacting any backend."""
    def __init__(self, core, agent, parent=None):
        super().__init__(parent)
        self.core, self.agent = core, agent
        self._loaded_data, self._loaded_index = None, -1
        self.setWindowTitle('角色腳本')
        self.resize(900, 780)
        layout = QVBoxLayout(self)
        layout.addWidget(label('角色腳本 · 切換 Agent 時會提示儲存未存修改。權限欄位記錄角色約定，實際操作仍由後端核准。', True))
        split = QSplitter()
        self.agents = QListWidget()
        self.agent_ids = list(core.agent_ids)
        self.agents.addItems([core.agent_name(key) for key in self.agent_ids])
        self.agents.setAccessibleName('角色腳本 Agent 清單')
        split.addWidget(self.agents)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_body = QWidget()
        form = QFormLayout(form_body)
        self.role = QLineEdit()
        self.role.setMaxLength(40)
        form.addRow('角色', self.role)
        self.markdown = {}
        for key, title in (('duties', '職責'), ('instructions', '派工指示'), ('report', '回報格式')):
            field = QPlainTextEdit()
            field.setMinimumHeight(90)
            field.setAccessibleName(title)
            self.markdown[key] = field
            form.addRow(title, field)
        self.limits = {}
        for key, title in (('run_budget', '執行預算（秒）'), ('max_turns', '工具回合上限'), ('timeout_seconds', '派工逾時（秒）')):
            field = QSpinBox()
            field.setRange(1, 2147483647)
            self.limits[key] = field
            form.addRow(title, field)
        self.limits_note = label('run_budget／max_turns：Hermes 請求未指定時的預設值；timeout_seconds：僅 Codex 生效。', True)
        self.limits_note.setWordWrap(True)
        form.addRow(self.limits_note)
        self.permissions = {}
        for key, title in (('commit', '允許 commit'), ('push', '允許 push（仍依任務授權）'), ('outside_card', '允許任務卡範圍外工作')):
            field = QCheckBox(title)
            self.permissions[key] = field
            form.addRow(field)
        scroll.setWidget(form_body)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([190, 670])
        layout.addWidget(split, 1)
        self.feedback = label('', True)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        buttons = QHBoxLayout()
        self.reset_button = button('還原預設', self.reset)
        buttons.addWidget(self.reset_button)
        buttons.addStretch()
        self.save_button = button('儲存', self.save)
        buttons.addWidget(self.save_button)
        buttons.addWidget(button('關閉', self.accept))
        layout.addLayout(buttons)
        for control in self.findChildren(QPushButton):
            control.setAutoDefault(False)
            control.setDefault(False)
        self.agents.currentRowChanged.connect(self.select_agent)
        self.agents.setCurrentRow(self.agent_ids.index(agent))

    def form_data(self):
        return dict(role=self.role.text(), **{key: field.toPlainText() for key, field in self.markdown.items()},
                    limits={key: field.value() for key, field in self.limits.items()},
                    permissions={key: field.isChecked() for key, field in self.permissions.items()})

    def select_agent(self, index):
        if index < 0: return
        if index != self._loaded_index and self._loaded_data is not None and self.form_data() != self._loaded_data:
            answer = QMessageBox.question(self, '未儲存的角色腳本', '要先儲存目前 Agent 的修改嗎？',
                                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Yes and not self.save()):
                previous = self.agents.blockSignals(True)
                self.agents.setCurrentRow(self._loaded_index)
                self.agents.blockSignals(previous)
                return
        self.agent = self.agent_ids[index]
        data = playbooks.load(self.core, self.agent)
        self.role.setText(data['role'])
        for key, field in self.markdown.items(): field.setPlainText(data[key])
        for key, field in self.limits.items(): field.setValue(data['limits'][key])
        for key, field in self.permissions.items(): field.setChecked(data['permissions'][key])
        self.feedback.setText('')
        self._loaded_data, self._loaded_index = data, index

    def refresh_owner(self):
        owner = self.parent()
        if owner and hasattr(owner, 'refresh_monitor'):
            owner.refresh_monitor()
            owner.update_context_title()

    def save(self):
        data = self.form_data()
        try:
            playbooks.save(self.core, self.agent, data)
            self._loaded_data = data
            self.refresh_owner()
            self.feedback.setText('已儲存角色腳本與 Markdown。')
            return True
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc))
            return False

    def reset(self):
        answer = QMessageBox.question(self, '還原角色腳本', '確定要還原預設並覆寫目前 Agent 的角色腳本嗎？',
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return False
        try:
            playbooks.reset(self.core, self.agent)
            self.select_agent(self.agents.currentRow())
            self.refresh_owner()
            self.feedback.setText('已還原並儲存預設。')
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc))


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
