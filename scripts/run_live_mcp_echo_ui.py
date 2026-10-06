"""Explicitly authorized official MCP echo through the real Workspace UI.
Human-only native approval. Session-only STDIO; no persistent settings/services.
"""
from pathlib import Path
import datetime,json,sys,tempfile,time,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow,EventCard
from acw.adapters.claude import ClaudeAdapter
from acw.security import sanitize

FIXED='ACW_MCP_ACCEPTANCE_OK';TOOL='mcp__acw_acceptance__echo'
OUT=ROOT/'evidence/live-mcp-echo-ui';OUT.mkdir(exist_ok=True)
BASE=Path(tempfile.mkdtemp(prefix='mcp-echo-',dir=ROOT/'tests'));REPO=BASE/'repo';REPO.mkdir()
NODE=r'C:\Users\ryant\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
FIXTURE=ROOT/'tools/claude-session-sdk/acceptance-echo.mjs'
PROMPT='Please call the available acw_acceptance echo MCP tool once with text '+FIXED+'. It returns only that exact fixed test string and has no side effects. Report the actual result naturally. This is an isolated acceptance test. Do not use any other tools or connectors, filesystem, shell, network tools, settings, login, or subagents. Any native approval must be handled by the human user.'
app=QApplication([]);core=WorkspaceCore(BASE/'data');core.set_setting('legacy.root',str(BASE/'no-legacy'))
adapter=core.set_adapter('claude',ClaudeAdapter(core.make_emitter('claude'),executable=r'C:\Users\ryant\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.286\635c1867224a\claude.exe',timeout=45,
 session_mcp_servers={'acw_acceptance':{'command':NODE,'args':[str(FIXTURE)],'type':'stdio'}}))
project=core.create_project('OFFICIAL MCP ECHO - ISOLATED',REPO);core.select_project(project['id']);core.create_task('Human approved native MCP echo')
window=MainWindow(core);window.setWindowTitle('AI Collaboration Workspace - OFFICIAL MCP ECHO - ISOLATED');window.show()
report={'status':'RUNNING','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Actual Workspace UI and official Claude CLI with existing permissions, one authorized local STDIO echo fixture, no automatic grant/allow rule/permission mode/permanent configuration change','data':str(BASE/'data'),'repo':str(REPO),'prompt':PROMPT,'approval_requests':[],'checks':{},'fixture':str(FIXTURE)}
stage='connect';busy=False;done=False;seen=set();start=time.monotonic()
def save(): (OUT/'result.json').write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8')
def finish(status,reason):
 global done
 if done:return
 done=True;timer.stop();window.poll_events();report.update(status=status,reason=reason,session=adapter.session_id,diagnostics=core.diagnostics('claude'))
 (OUT/'public-events.json').write_text(json.dumps(sanitize([e for e in core.events(agent='claude',limit=10000) if e['type'] not in ('raw','message_delta')]),ensure_ascii=False,indent=2),encoding='utf-8')
 (OUT/'messages.json').write_text(json.dumps(sanitize(core.messages(agent='claude')),ensure_ascii=False,indent=2),encoding='utf-8')
 window.grab().save(str(OUT/'window.png'))
 try:
  if adapter.state=='Busy':adapter.stop()
  original_process=adapter._process
  adapter.disconnect();report['official_process_exited']=original_process is None or original_process.poll() is not None
 except Exception as exc:report['cleanup_error']=str(sanitize(str(exc)));report['official_process_exited']=False
 save();print(status+' '+reason,flush=True)
 for panel in window.panels.values():panel.set_state('Disconnected')
 window.close();QTimer.singleShot(100,app.quit)
def tick():
 global stage,busy
 try:
  window.poll_events();panel=window.panels['claude']
  for rid,event in panel.pending_approval_events.items():
   if rid not in seen:
    seen.add(rid);report['approval_requests'].append({'id':rid,'request':event})
    QTest.mouseDClick(panel.title,Qt.LeftButton)
    for card in panel.findChildren(EventCard):
     if rid in card.body.toPlainText():
      panel.scroll.ensureWidgetVisible(card.toggle)
      if not card.toggle.isChecked():QTest.mouseClick(card.toggle,Qt.LeftButton)
      panel.scroll.ensureWidgetVisible(card)
    save();window.grab().save(str(OUT/'pending-human.png'));print('PENDING HUMAN APPROVAL '+rid+'; tool='+TOOL+' fixed text only; no grant issued by test',flush=True)
  if adapter.state in ('Error','Offline'):finish('BLOCKED',adapter.last_error);return
  if time.monotonic()-start>(900 if report['approval_requests'] else 180):finish('BLOCKED','Native timeout/approval pending; no automatic grant or retry');return
  if stage=='connect':QTest.mouseClick(panel.connect_button,Qt.LeftButton);stage='new'
  elif stage=='new' and adapter.state=='Connected' and not window.workers:window.refresh_agent('claude');QTest.mouseClick(panel.new_button,Qt.LeftButton);stage='send'
  elif stage=='send' and adapter.session_id and not window.workers:
   window.reload_context();window.workspace_scroll.ensureWidgetVisible(panel.send_button);panel.input.setPlainText(PROMPT);QTest.mouseClick(panel.send_button,Qt.LeftButton);stage='result'
  elif stage=='result':
   if adapter.state=='Busy':busy=True
   responses=[m for m in core.messages(agent='claude') if m['role']=='assistant' and m['status']=='complete']
   if busy and adapter.state=='Connected' and not window.workers and responses:
    stage='verify';timer.stop()
    events=core.events(agent='claude',limit=10000)
    native=[e for e in events if e['type'] in ('tool_start','tool_result') and e.get('payload',{}).get('name')==TOOL]
    starts=[e for e in native if e['type']=='tool_start'];results=[e for e in native if e['type']=='tool_result']
    approvals=[e for e in events if e['type']=='approval_response' and e.get('payload',{}).get('approved')]
    cards=[card for card in panel.findChildren(EventCard) if TOOL in card.body.toPlainText()]
    body='\n'.join(card.body.toPlainText() for card in cards)
    report['checks']={'exact_native_tool_once':len(starts)==1,'exact_fixed_arguments':len(starts)==1 and starts[0]['payload']['arguments']=={'text':FIXED},
     'native_result_fixed':len(results)==1 and FIXED in json.dumps(results[0]['payload']['result']),
     'native_result_completed':len(results)==1 and results[0]['status']=='completed',
     'original_approval_requested':len(report['approval_requests'])==1,
     'human_approval_recorded':len(approvals)==1,'actual_UI_tool_name':TOOL in body,'actual_UI_arguments':FIXED in body and 'arguments' in body,
     'actual_UI_result_status':FIXED in body and 'completed' in body,
     'no_other_connector_tools':all(e.get('payload',{}).get('name')==TOOL for e in events if e['type']=='tool_start'),
     'isolated_cwd':adapter.cwd==str(REPO)}
    for index,card in enumerate(cards):
     panel.scroll.ensureWidgetVisible(card.toggle)
     if not card.toggle.isChecked():QTest.mouseClick(card.toggle,Qt.LeftButton)
     panel.scroll.ensureWidgetVisible(card.body);QTest.qWait(100);window.grab().save(str(OUT/f'tool-card-{index}.png'))
    finish('PASS' if all(report['checks'].values()) else 'FAIL','Native echo, original human approval and actual Workspace tool cards checked')
 except Exception as exc:report['traceback']=traceback.format_exc();finish('BLOCKED',str(exc))
timer=QTimer();timer.timeout.connect(tick);timer.start(150);save();app.exec();core.close()
