"""Actual UI raw-event inspection for the completed MCP run; no new backend."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication,QPushButton,QTreeWidget,QPlainTextEdit
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow
OUT=ROOT/'evidence/live-mcp-echo-ui';report=json.loads((OUT/'result.json').read_text(encoding='utf-8'))
data=Path(report['data']).resolve();assert data.is_relative_to(ROOT/'tests') and data.parent.name.startswith('mcp-echo-')
app=QApplication([]);core=WorkspaceCore(data);window=MainWindow(core);window.show();QTest.qWait(150)
checks={};errors=[]
def inspect():
 dialog=app.activeModalWidget()
 try:
  index=dialog.findChild(QTreeWidget);text=dialog.findChild(QPlainTextEdit)
  for kind in ('tool_start','approval','tool_result'):
   match=next((index.topLevelItem(i) for i in range(index.topLevelItemCount())
    if index.topLevelItem(i).data(0,Qt.UserRole)['type']==kind
    and 'mcp__acw_acceptance__echo' in json.dumps(index.topLevelItem(i).data(0,Qt.UserRole))),None)
   assert match is not None,kind+' absent from saved original events'
   index.scrollToItem(match);QTest.mouseClick(index.viewport(),Qt.LeftButton,pos=index.visualItemRect(match).center());QTest.qWait(80)
   body=text.toPlainText();checks[kind]=text.isReadOnly() and 'mcp__acw_acceptance__echo' in body and 'ACW_MCP_ACCEPTANCE_OK' in body
   if kind=='tool_result':checks[kind]=checks[kind] and 'completed' in body
   dialog.grab().save(str(OUT/(kind+'-raw-ui.png')))
 except Exception as exc:errors.append(str(exc))
 finally:dialog.accept()
QTimer.singleShot(150,inspect)
raw_button=next(button for button in window.panels['claude'].findChildren(QPushButton) if button.text()=='Raw')
QTest.mouseClick(raw_button,Qt.LeftButton)
result={'status':'PASS' if all(checks.values()) and len(checks)==3 and not errors else 'FAIL','checks':checks,'errors':errors,'scope':'Actual saved native event selection through Workspace Raw UI; no reconnect, resend, fixture or agent process; overlaps original tool UI checks'}
(OUT/'saved-raw-ui.json').write_text(json.dumps(result,indent=2),encoding='utf-8');window.close();core.close();print(json.dumps(result))
