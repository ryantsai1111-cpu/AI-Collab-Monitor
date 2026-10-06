"""Actual isolated Qt window movement/restoration on existing physical screens."""
from pathlib import Path
import datetime
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'vendor'), str(ROOT)]
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow

app = QApplication([])
out = ROOT / 'evidence/multi-monitor-ui'
out.mkdir(exist_ok=True)
data = Path(tempfile.mkdtemp(prefix='multi-monitor-', dir=ROOT / 'tests'))
core = WorkspaceCore(data)
core.set_setting('legacy.root', str(data / 'no-legacy'))
report = {'observed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'scope': 'Actual source Qt window on existing displays, isolated SQLite, no backend connections or system display changes',
          'checks': {}, 'screens': []}
for i, screen in enumerate(app.screens()):
    window = MainWindow(core)
    window.show()
    QTest.qWait(250)
    window.windowHandle().setScreen(screen)
    rect = screen.availableGeometry()
    window.move(rect.topLeft())
    window.resize(rect.width() - 20, rect.height() - 40)
    QTest.qWait(600)
    actual = window.frameGeometry()
    report['checks'][f'screen_{i}_window_on_target'] = window.windowHandle().screen() == screen
    report['checks'][f'screen_{i}_fully_visible'] = rect.contains(actual)
    window.workspace_scroll.ensureWidgetVisible(window.panels['claude'].input)
    QTest.qWait(150)
    viewport = window.workspace_scroll.viewport()
    input_rect = window.panels['claude'].input.rect()
    input_center = window.panels['claude'].input.mapTo(viewport, input_rect.center())
    report['checks'][f'screen_{i}_input_reachable'] = viewport.rect().contains(input_center)
    report['screens'].append({'name': screen.name(), 'available': [rect.x(), rect.y(), rect.width(), rect.height()],
                             'frame': [actual.x(), actual.y(), actual.width(), actual.height()]})
    window.grab().save(str(out / f'screen-{i}.png'))
    window.close()
    QTest.qWait(200)
    restored = MainWindow(core)
    restored.show()
    QTest.qWait(500)
    report['checks'][f'screen_{i}_restore_target'] = restored.windowHandle().screen() == screen
    report['checks'][f'screen_{i}_no_backend_start'] = all(panel.connection_state != 'Connected' for panel in restored.panels.values())
    restored.close()
    QTest.qWait(100)
report['status'] = 'PASS' if len(app.screens()) >= 2 and all(report['checks'].values()) else 'FAIL'
(out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
