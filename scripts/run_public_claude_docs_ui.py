"""Opt-in official Claude Docs public-document scope check through actual UI.

No fixture/server/config changes; no automatic permission grants.
"""
from pathlib import Path
import datetime,json,sys,tempfile,time,traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow,EventCard
from acw.adapters.claude import ClaudeAdapter
from acw.security import sanitize

OUT=ROOT/'evidence/public-claude-docs-ui';OUT.mkdir(exist_ok=True)
BASE=Path(tempfile.mkdtemp(prefix='public-claude-docs-',dir=ROOT/'tests'))
REPO=ROOT/'tests/claude-tools-o2w_zsod/repo'
assert REPO.is_dir()
PROMPT='''This is an isolated, read-only acceptance check. The only target content is the public official page https://code.claude.com/docs/en/agent-sdk/mcp . First inspect the available description/schema of mcp__claude_ai_Claude_Docs__query using tool discovery only. Do not assume the connector is a public developer-documentation search service merely because it is named Claude Docs. Only invoke that tool if its description/schema explicitly supports reading publicly accessible developer documentation by public URL or public query without accessing user-owned/private documents. If its scope is user documents, unknown, or lacks public URL retrieval, do not invoke it; explain the precise scope/limitation naturally. If it supports the public page, read only that page and briefly describe its SDK MCP connection example. Do not use Google Drive, Notion, any other connector, WebFetch, web search, shell, filesystem, subagents, settings, login, or write tools. Do not create any document, server or service. Do not change permissions. Any backend permission request must remain for the human user to review.'''
app=QApplication([]);core=WorkspaceCore(BASE/'data')
core.set_setting('legacy.root',str(BASE/'no-legacy'))
adapter=core.set_adapter('claude',ClaudeAdapter(core.make_emitter('claude'),executable=r'C:\Users\ryant\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.286\635c1867224a\claude.exe',timeout=40))
project=core.create_project('PUBLIC CLAUDE DOCS - ISOLATED',REPO);core.select_project(project['id']);core.create_task('Official MCP public documentation scope and UI')
window=MainWindow(core);window.setWindowTitle('AI Collaboration Workspace - PUBLIC CLAUDE DOCS - ISOLATED');window.show()
report={'status':'RUNNING','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Existing official Claude Docs connector only; public-document scope must be established before content call; actual source Qt isolated data, no automatic grants','prompt':PROMPT,'data':str(BASE/'data'),'repo':str(REPO),'approval_requests':[],'checks':{}}
stage='connect';busy=False;done=False;seen=set();start=time.monotonic()
def save(): (OUT/'result.json').write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8')
def finish(status,reason):
 global done
 if done:return
 done=True;timer.stop();window.poll_events();report.update(status=status,reason=reason,session=adapter.session_id,diagnostics=core.diagnostics('claude'))
 events=[e for e in core.events(agent='claude',limit=10000) if e['type'] not in ('raw','message_delta')]
 (OUT/'public-events.json').write_text(json.dumps(sanitize(events),ensure_ascii=False,indent=2),encoding='utf-8')
 (OUT/'messages.json').write_text(json.dumps(sanitize(core.messages(agent='claude')),ensure_ascii=False,indent=2),encoding='utf-8')
 window.grab().save(str(OUT/'window.png'));save();print(status+' '+reason,flush=True)
 try:
  if adapter.state=='Busy':adapter.stop()
  adapter.disconnect()
 except Exception as exc:print('Cleanup: '+str(sanitize(str(exc))),flush=True)
 for panel in window.panels.values():panel.set_state('Disconnected')
 window.close();QTimer.singleShot(100,app.quit)
def tick():
 global stage,busy
 try:
  window.poll_events();panel=window.panels['claude']
  for rid,event in panel.pending_approval_events.items():
   if rid not in seen:
    seen.add(rid);report['approval_requests'].append({'id':rid,'request':event});window.grab().save(str(OUT/'pending-human.png'));save();print('PENDING HUMAN APPROVAL '+rid+'; no grant issued by test',flush=True)
  if adapter.state in ('Error','Offline'):finish('BLOCKED',adapter.last_error);return
  if time.monotonic()-start>(900 if report['approval_requests'] else 180):finish('BLOCKED','Timeout; no automatic approval/retry');return
  if stage=='connect':QTest.mouseClick(panel.connect_button,Qt.LeftButton);stage='new'
  elif stage=='new' and adapter.state=='Connected' and not window.workers:window.refresh_agent('claude');QTest.mouseClick(panel.new_button,Qt.LeftButton);stage='send'
  elif stage=='send' and adapter.session_id and not window.workers:
   window.reload_context();window.workspace_scroll.ensureWidgetVisible(panel.send_button);panel.input.setPlainText(PROMPT);QTest.mouseClick(panel.send_button,Qt.LeftButton);stage='result'
  elif stage=='result':
   if adapter.state=='Busy':busy=True
   responses=[m for m in core.messages(agent='claude') if m['role']=='assistant' and m['status']=='complete']
   if busy and adapter.state=='Connected' and not window.workers and responses:
    report['assistant_result']=responses[-1]['content']
    events=core.events(agent='claude',limit=10000);target=[e for e in events if e['type'] in ('tool_start','tool_result') and (e.get('payload',{}).get('name') or e.get('payload',{}).get('tool'))=='mcp__claude_ai_Claude_Docs__query']
    cards=panel.findChildren(EventCard);bodies='\n'.join(card.body.toPlainText() for card in cards)
    report['checks']={'official_UI_response':True,'target_MCP_tool_invoked':bool(target),'target_MCP_result':any(e['type']=='tool_result' for e in target),'target_tool_in_UI':'mcp__claude_ai_Claude_Docs__query' in bodies}
    # Invocation alone never proves public scope/content success. Final promotion
    # requires independent review of original public events and tool metadata.
    finish('REVIEW_REQUIRED' if target else 'BLOCKED','Review actual schema/scope and tool results; no automatic requirement promotion')
 except Exception as exc:report['traceback']=traceback.format_exc();finish('BLOCKED',str(exc))
timer=QTimer();timer.timeout.connect(tick);timer.start(150);save();app.exec();core.close()
