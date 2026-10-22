"""Artifact review panel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .widgets import button, identifier, label
from .dialogs import ScreenshotReviewDialog


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
