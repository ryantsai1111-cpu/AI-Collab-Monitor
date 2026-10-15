"""Render synthetic Monitor evidence with system fonts; never connects to a backend."""
import os
import argparse
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from test_orchestrator import WindowRunTests
from test_orchestrator import Scripted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lead', choices=('claude', 'codex'), default='claude')
    parser.add_argument('--same-provider', action='store_true')
    options = parser.parse_args()
    lead = options.lead
    worker = 'claude' if lead == 'codex' else 'codex'
    app = QApplication.instance() or QApplication([])
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'msjh.ttc', 'msjhbd.ttc', 'seguisym.ttf', 'consola.ttf', 'consolab.ttf'):
        path = Path('C:/Windows/Fonts') / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Microsoft JhengHei UI', 9))
    app.setStyle('Fusion')
    fixture = WindowRunTests()
    fixture.setUp()
    window = fixture.window
    window.sync_timer.stop()
    try:
        fixture.core.store.update('projects', {'id': fixture.core.current_project_id}, {'name': 'AI-Collab-Workspace · 離線示範'})
        fixture.core.store.update('tasks', {'id': fixture.core.current_task_id}, {'title': '獨立協作與 Monitor 優化'})
        if options.same_provider:
            selected = []
            for name in ('Claude / Lead', 'Claude / Builder'):
                agent = window.add_agent_instance('claude', name, project_id=fixture.core.current_project_id)
                adapter = Scripted(agent, [])
                adapter.core = fixture.core
                adapter.state = 'Connected'
                fixture.core.set_adapter(agent, adapter)
                fixture.core.select_agent_task(agent, fixture.core.current_task_id)
                selected.append(agent)
            lead, worker = selected
        fixture.core.adapters[lead].replies = ['VERDICT: PLAN_READY\nFollow the task and verify the implementation.']
        fixture.core.adapters[worker].replies = []
        fixture.adapters['dot'].state = fixture.adapters['local'].state = 'Disconnected'
        window.run_auto_collab('讓每個 agent 在自己的 session 工作，由本次選定的主導者派工，檢查實作與測試後決定是否完成。', 3, lead=lead, implementer=worker)
        window.run_timer.stop()
        window.reload_context()
        window.panels[worker].pending_approval_events['fixture'] = {'id': 'fixture'}
        window.orchestrator.tick()
        window.run_status.setText(window.orchestrator.status())
        window.refresh_monitor()
        window.sidebar.hide()
        window.show()
        output = Path('evidence/monitor')
        output.mkdir(parents=True, exist_ok=True)
        for name, width, height in (('wide', 1500, 1060), ('narrow', 650, 960)):
            window.resize(width, height)
            if name == 'narrow':
                window.sidebar.show()
            for _ in range(6):
                app.processEvents()
            prefix = 'instances-' if options.same_provider else 'codex-lead-' if lead == 'codex' else ''
            path = output / (prefix + name + '.png')
            window.grab().save(str(path))
            print(path.resolve())
        window.panels[worker].pending_approval_events.clear()
        window.stop_auto_collab()
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
