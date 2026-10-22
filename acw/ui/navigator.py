"""Session navigator."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from ..theme import HEADING_COLOR, MUTED_COLOR, SPACE

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .widgets import button, label


def _normalize_dir(path):
    return os.path.normcase(os.path.normpath(str(Path(path).resolve())))


def _same_dir(a, b):
    """Compare directory spellings using the host filesystem's path semantics."""
    return _normalize_dir(a) == _normalize_dir(b)


class SessionNavigator(QWidget):
    """Sidebar list of locally saved Claude desktop and Codex conversations, grouped by repository.

    Showing the sidebar or selecting an agent loads uncached provider metadata in the
    background when the sidebar is visible. Hidden selections defer loading until shown.
    Rename and archive stay in workspace settings; source apps' files are never written."""
    SOURCES = (("Claude", "claude"), ("Codex", "codex"))

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.sessions = {agent: None for _, agent in self.SOURCES}
        self.collapsed = set()
        self.loading = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE['sm'])
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
        actions.setSpacing(SPACE['sm'])
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
        from ..desktop_sessions import group_by_project
        agent, query = self.agent, self.search.text().casefold().strip()
        selected = (self.selected() or {}).get("id")
        if agent not in self.sessions:
            return
        current = (self.window.core.agent_task(self._agent) or {}).get(self._agent + "_session")
        directory = (self.window.core.agent_project(self._agent) or {}).get('repo_path')
        self.nav_all_projects.setEnabled(bool(directory))
        rows = self.sessions[agent] or []
        if directory and not self.nav_all_projects.isChecked():
            bound_directory = _normalize_dir(directory)
            rows = [row for row in rows if _normalize_dir(row['cwd']) == bound_directory]
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
                    child.setForeground(0, QColor('#ececea' if self.window.theme_name == 'desktop' else HEADING_COLOR))
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
