"""Reopen only this isolated test's saved history; never connect or send."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow,EventCard
out=ROOT/'evidence/public-claude-docs-ui'
report=json.loads((out/'result.json').read_text(encoding='utf-8'))
data=Path(report['data']).resolve()
assert data.is_relative_to(ROOT/'tests') and data.parent.name.startswith('public-claude-docs-')
app=QApplication([]);core=WorkspaceCore(data);window=MainWindow(core);window.show();QTest.qWait(250)
panel=window.panels['claude'];QTest.mouseDClick(panel.title,Qt.LeftButton);QTest.qWait(200)
cards=panel.findChildren(EventCard)
hits=[card for card in cards if 'ToolSearch' in card.body.toPlainText()]
for index,card in enumerate(hits):
 panel.scroll.ensureWidgetVisible(card.toggle);QTest.qWait(100)
 if not card.toggle.isChecked():QTest.mouseClick(card.toggle,Qt.LeftButton)
 panel.scroll.ensureWidgetVisible(card.body);QTest.qWait(150)
 window.grab().save(str(out/f'discovery-card-{index}.png'))
panel.scroll.verticalScrollBar().setValue(panel.scroll.verticalScrollBar().maximum());QTest.qWait(150)
window.grab().save(str(out/'scope-response.png'))
report['history_UI_capture']={'toolsearch_cards':len(hits),'new_backend_connections':False,'new_prompts_sent':False,'source':'Saved actual native test events/history; offline reopen'}
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
window.close();core.close();print(json.dumps(report['history_UI_capture']))
