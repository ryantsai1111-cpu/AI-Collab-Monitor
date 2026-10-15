"""Render the real Qt workbench using synthetic, disconnected test data."""
import argparse
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from test_orchestrator import WindowRunTests
from acw.store import now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('task-a', 'task-b', 'a', 'b'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.stage in ('a', 'b'):
        args.stage = 'task-' + args.stage
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisym.ttf', 'msjh.ttc', 'msjhbd.ttc', 'consola.ttf', 'consolab.ttf'):
        path = Path('C:/Windows/Fonts') / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Microsoft JhengHei UI', 9))
    fixture = WindowRunTests()
    fixture.setUp()
    window, core = fixture.window, fixture.core
    window.sync_timer.stop()
    window.timer.stop()
    try:
        core.store.update('projects', {'id': core.current_project_id}, {'name': 'AI-Collab-Workspace'})
        core.store.update('tasks', {'id': core.current_task_id}, {'title': 'Monitor 工作台 · 離線 UI 示範'})
        for agent, adapter in fixture.adapters.items():
            adapter.state = 'Disconnected'
        messages = {
            'claude': [('user', '先討論 Monitor 的使用方式，現在不用派工。每個 Agent 都要保留自己的專案和 session。'),
                       ('assistant', '可以。你可以先在這裡討論需求，再按「自動協作」選擇主導者與實作者。\n\n### 每個視窗各自工作\n右側可查看各 Agent 的連線狀態、專案與對話。切換成員只會切換畫面，草稿與 session 仍留在原本的 Agent。\n\n需要同時看多個完整對話時，把上方布局切到「並排」。')],
            'codex': [('assistant', 'UI 實作與驗證會在這個 session 進行。\n\n- 保留既有草稿與附件\n- 確認核准不會跨 Agent\n- 驗證窄視窗與並排布局\n\n目前尚未啟動協作。')],
            'local': [('assistant', '這個 Agent 直接使用 Hermes CLI。\n\nProvider 與模型留空時沿用 Hermes 設定；按「連線」檢查 CLI 後即可使用。工具權限由 Hermes 管理，不透過 Workspace 核准。')],
        }
        for agent, values in messages.items():
            for index, (role, content) in enumerate(values):
                core.store.insert('messages', dict(id=f'workbench-{agent}-{index}', agent=agent,
                    task_id=core.current_task_id, session_id=core.current_task[agent + '_session'],
                    role=role, content=content, timestamp=now(), status='complete', metadata={}))
        window.reload_context()
        window.open_monitor_role('claude')
        window.panels['claude'].input.setPlainText('先幫我整理待辦，確定範圍後再開始協作。')
        window.refresh_monitor()
        window.show()
        output = args.output or Path('evidence/ui-redesign' if args.stage else 'evidence/monitor')
        output.mkdir(parents=True, exist_ok=True)
        for name, width, height, mode, sidebar in (
                ('workbench-focus', 1500, 1000, 'Focus', True),
                ('workbench-parallel', 1800, 1000, 'Three panes', True),
                ('workbench-narrow', 650, 900, 'Focus', False)):
            window.sidebar.setVisible(sidebar)
            window.resize(width, height)
            window.layout_mode.setCurrentIndex(window.layout_mode.findData(mode))
            for _ in range(10):
                app.processEvents()
                window.update_workspace_layout()
            suffix = 'focus' if mode == 'Focus' and sidebar else 'panes' if mode == 'Three panes' else 'narrow'
            path = output / ((args.stage + '-' + suffix if args.stage else name) + '.png')
            window.grab().save(str(path))
            print(path.resolve())
        if args.stage == 'task-b':
            window.sidebar.show()
            window.resize(1500, 1000)
            window.mode.setCurrentIndex(window.mode.findData('Monitor'))
            for _ in range(10):
                app.processEvents()
            path = output / 'task-b-monitor.png'
            window.grab().save(str(path))
            print(path.resolve())
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
