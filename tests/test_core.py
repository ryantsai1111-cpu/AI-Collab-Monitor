"""Core acceptance tests: all adapters are explicit synthetic doubles, all I/O isolated."""
import json
import os
import base64
import struct
import tempfile
import threading
import time
import unittest
import zipfile
import zlib
from unittest.mock import patch
from pathlib import Path
from tests.workspace_fixtures import TranscriptFixtureCore as WorkspaceCore
from acw.adapters.base import Adapter,Capabilities

class SyntheticAdapter(Adapter):
    """TEST DOUBLE; never used by run.py or claimed as live backend evidence."""
    def __init__(self,agent):
        super().__init__(lambda *args,**kwargs:None)
        self.agent=agent
        self.capabilities=Capabilities(supports_model_selection=True,supports_effort=True,supports_sessions=True,
            supports_tools=True,supports_project=True,supports_cancel=True,supports_streaming=True,supports_history=True,
            models=['synthetic-model'],efforts=['synthetic-effort'])
        self.sent=[]
        self.calls=[]
    def connect(self): self.calls.append('connect');self.set_state('Connected')
    def disconnect(self): self.calls.append('disconnect');self.set_state('Disconnected')
    def create_session(self):
        self.session_id=self.agent+'-synthetic-session-'+str(len(self.calls))
        self.calls.append('create_session');self.emit('session',session_id=self.session_id)
        return self.session_id
    def resume_session(self,session_id):
        self.session_id=session_id;self.calls.append('resume_session');return session_id
    def send_message(self,content,**kwargs): self.sent.append(content);return 'synthetic-send-result'
    def stop(self): self.calls.append('stop');return 'synthetic-cancel'
    def set_project(self,path,metadata=None): self.cwd=path;self.metadata=metadata

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='acw-core-tests-')
        self.root=Path(self.temp.name)
        self.repo=self.root/'isolated-repo';self.repo.mkdir()
        self.adapters={a:SyntheticAdapter(a) for a in ('claude','dot','codex')}
        self.clock=[1000.0]
        self.core=WorkspaceCore(self.root/'data',self.adapters,clock=lambda:self.clock[0])
        self.core.git_snapshot=lambda project_id=None:{'branch':'synthetic-branch','diff':'','status':'','log':''}
        self.project=self.core.create_project('Isolated Test Project',self.repo)
        self.core.select_project(self.project['id'])
        self.task=self.core.create_task('Synthetic Task')
    def tearDown(self):
        if not self.core._closed:self.core.close()
        self.temp.cleanup()
    def connected(self,agent):
        self.core.connect(agent);return self.core.create_session(agent)
    def response(self,agent='claude',text='A'):
        self.core.ingest_event(agent,'message_start')
        self.core.ingest_event(agent,'message_delta',content=text)
        event=self.core.ingest_event(agent,'message_end')
        return event['message_id']
    def test_idle_checkpoint_flushes_wal_after_five_minutes(self):
        self.core.store.db.execute('PRAGMA wal_autocheckpoint=0')
        # Make the main file timestamp deterministic without sleeping for filesystem resolution.
        os.utime(self.core.store.db_path, (1, 1))
        before = self.core.store.db_path.stat().st_mtime_ns
        for index in range(30):
            self.response(text=f'checkpoint fixture {index}: ' + 'x' * 2048)
        wal = Path(str(self.core.store.db_path) + '-wal')
        self.assertGreater(wal.stat().st_size, 0)
        self.clock[0] += 300
        self.assertIsNone(self.core.maybe_checkpoint())
        self.clock[0] += 1
        result = self.core.maybe_checkpoint()
        self.assertEqual(0, result[0])
        self.assertGreater(result[1], 0)
        self.assertEqual(result[1], result[2])
        self.assertGreater(self.core.store.db_path.stat().st_mtime_ns, before)
        self.assertEqual('wal', self.core.store.db.execute('PRAGMA journal_mode').fetchone()[0])
        with patch.object(self.core.store, 'checkpoint') as checkpoint:
            self.core.poll_requests()
            checkpoint.assert_not_called()

    def test_busy_adapter_defers_checkpoint_until_idle_poll(self):
        self.clock[0] += 301
        self.adapters['claude'].state = 'Busy'
        with patch.object(self.core.store, 'checkpoint', return_value=(0, 2, 2)) as checkpoint:
            self.core.poll_requests()
            checkpoint.assert_not_called()
            self.adapters['claude'].state = 'Connected'
            self.core.poll_requests()
            checkpoint.assert_called_once_with('PASSIVE')

    def test_unsuccessful_checkpoint_does_not_advance_interval(self):
        self.clock[0] += 301
        for result in ((1, 2, 0), (0, 2, 1)):
            with patch.object(self.core.store, 'checkpoint', return_value=result) as checkpoint:
                self.core.maybe_checkpoint()
                self.core.maybe_checkpoint()
                self.assertEqual(2, checkpoint.call_count)
        with patch.object(self.core.store, 'checkpoint', side_effect=RuntimeError('fixture failure')), \
                self.assertLogs('acw.store', level='WARNING') as logs:
            self.core.maybe_checkpoint()
        self.assertIn('Periodic WAL checkpoint failed', logs.output[0])
        with patch.object(self.core.store, 'checkpoint', return_value=(0, 0, 0)) as checkpoint:
            self.core.maybe_checkpoint()
            checkpoint.assert_called_once_with('PASSIVE')

    def test_checkpoint_rejects_invalid_mode_and_close_logs_failure(self):
        with self.assertRaises(ValueError):
            self.core.store.checkpoint('PASSIVE); DROP TABLE messages; --')
        with patch.object(self.core.store, 'checkpoint', side_effect=RuntimeError('fixture failure')) as checkpoint, \
                self.assertLogs('acw.store', level='WARNING') as logs:
            self.core.close()
        checkpoint.assert_called_once_with('TRUNCATE')
        self.assertTrue(self.core.store._closed)
        self.assertIn('WAL checkpoint on close failed', logs.output[0])

    def test_no_automatic_connections_or_resends(self):
        self.assertTrue(all(not adapter.calls for adapter in self.adapters.values()))
        self.core.close()
        self.core=WorkspaceCore(self.root/'data',self.adapters)
        self.assertTrue(all(not adapter.calls for adapter in self.adapters.values()))
        self.assertEqual(self.task['id'],self.core.current_task['id'])
        self.assertEqual(self.project['id'],self.core.current_project['id'])
    def test_project_sync_is_cwd_for_filesystem_agents_metadata_only_for_dot(self):
        self.core.sync_project()
        self.assertEqual(str(self.repo),self.adapters['claude'].cwd)
        self.assertEqual(str(self.repo),self.adapters['codex'].cwd)
        self.assertEqual('',self.adapters['dot'].cwd)
        self.assertEqual(self.task['id'],self.adapters['dot'].metadata['task_id'])
        self.assertEqual('synthetic-branch',self.adapters['dot'].metadata['branch'])
    def test_switching_project_with_draft_requires_confirmation(self):
        second=self.core.create_project('Second',self.repo)
        with self.assertRaises(PermissionError):self.core.select_project(second['id'],drafts={'claude':'unsent'})
        self.assertEqual(self.project['id'],self.core.current_project_id)
        self.core.select_project(second['id'],drafts={'claude':'unsent'},confirmed=True)
        self.assertIsNone(self.core.current_task)
    def test_busy_project_or_task_switch_is_rejected(self):
        self.adapters['claude'].state='Busy'
        second=self.core.create_project('Second',self.repo)
        with self.assertRaises(RuntimeError):self.core.select_project(second['id'])
    def test_sessions_map_persist_rename_and_require_explicit_resume(self):
        sid=self.connected('claude')
        self.core.rename_session('claude',sid,'Design review')
        self.core.send_message('claude','ordinary prompt')
        self.assertEqual(sid,self.core.current_task['claude_session'])
        self.assertEqual('Design review',self.core.sessions('claude')[0]['title'])
        other=self.core.create_task('Another isolated task')
        with self.assertRaises(RuntimeError):self.core.send_message('claude','must not use old session')
        self.core.select_task(self.task['id'])
        self.adapters['claude'].session_id=''
        with self.assertRaises(RuntimeError):self.core.send_message('claude','must explicitly resume')
        self.core.resume_session('claude',sid)
        self.core.send_message('claude','resumed ordinary prompt')
        self.assertEqual(2,len(self.adapters['claude'].sent))
    def test_prompt_and_notes_do_not_force_format_or_transmit_notes(self):
        self.connected('claude')
        self.core.update_task(self.task['id'],notes='PRIVATE LOCAL NOTE')
        content='Free-form request without tags\n中文可保留。'
        self.core.send_message('claude',content)
        self.assertEqual([content],self.adapters['claude'].sent)
        self.assertEqual(content,self.core.messages(agent='claude')[0]['content'])
    def test_streaming_queues_incremental_sanitized_content(self):
        self.connected('claude')
        self.core.drain_events()
        self.core.ingest_event('claude','message_start')
        self.core.ingest_event('claude','message_delta',content='first ')
        self.core.ingest_event('claude','message_delta',content='second')
        events=self.core.drain_events()
        self.assertEqual(['','first ','first second'],[event['full_content'] for event in events])
        self.assertEqual('streaming',self.core.messages(agent='claude')[-1]['status'])
        self.core.ingest_event('claude','message_end')
        self.assertEqual('complete',self.core.messages(agent='claude')[-1]['status'])
    def test_interrupt_recovery_retains_partial_and_never_resends(self):
        sid=self.connected('codex')
        self.core.ingest_event('codex','message_start')
        self.core.ingest_event('codex','message_delta',content='partial safe answer\n')
        self.core.close()
        adapters={a:SyntheticAdapter(a) for a in ('claude','dot','codex')}
        self.core=WorkspaceCore(self.root/'data',adapters)
        self.assertEqual(sid,self.core.current_task['codex_session'])
        message=self.core.messages(agent='codex')[-1]
        self.assertEqual('partial safe answer\n',message['content'])
        self.assertEqual('interrupted',message['status'])
        self.assertTrue(all(not adapter.calls for adapter in adapters.values()))
        self.assertTrue(any(event['type']=='recovery' for event in self.core.events()))
    def test_handoff_preserves_source_separate_note_and_metadata(self):
        self.connected('claude');self.connected('codex')
        original='A\nExact original content: 中文 / symbols < >'
        message_id=self.response(text=original)
        preview=self.core.prepare_handoff(message_id,'codex','Additional context')
        self.assertEqual(original,preview['source_message'])
        self.assertEqual('Additional context',preview['annotation'])
        self.assertEqual(self.task['id'],preview['metadata']['task_id'])
        self.assertIn(original,preview['handoff_message'])
        self.assertFalse(self.adapters['codex'].sent)
        # Caller editing the returned dict cannot silently rewrite approved original.
        preview['handoff_message']='tampered text'
        self.core.send_handoff(preview)
        self.assertIn(original,self.adapters['codex'].sent[-1])
        self.assertNotIn('tampered text',self.adapters['codex'].sent[-1])
        self.assertEqual('sent',self.core.handoffs()[0]['status'])
        with self.assertRaises(ValueError):self.core.send_handoff(preview)
    def test_failed_handoff_is_not_reported_sent(self):
        message_id=self.response()
        preview=self.core.prepare_handoff(message_id,'dot')
        with self.assertRaises(RuntimeError):self.core.send_handoff(preview)
        self.assertEqual('failed',self.core.handoffs()[0]['status'])
    def test_history_fulltext_and_filters(self):
        self.core.update_task(self.task['id'],status='VERIFYING')
        self.response(text='needle response')
        self.core.ingest_event('codex','command',command='pytest needle.py',cwd=str(self.repo),output='2 passed',exit_code=0)
        self.core.ingest_event('codex','file',path='needle.py',content='file changed')
        self.core.ingest_event('codex','error',content='needle error')
        found=self.core.search('needle',project_id=self.project['id'],status='VERIFYING',branch='synthetic-branch',error=True)
        self.assertTrue(any(row['kind']=='messages' for row in found))
        self.assertEqual(1,len(self.core.list_tasks(agent='codex',status='VERIFYING',error=True)))
        self.assertEqual([],self.core.search('needle',status='DONE'))
        self.assertEqual(1,len(self.core.list_tasks(date_from='2000-01-01',date_to='2099-01-01')))
    def test_task_cannot_self_approve_or_enable_orchestration(self):
        with self.assertRaises(ValueError):self.core.update_task(self.task['id'],status='APPROVED')
        with self.assertRaises(ValueError):self.core.set_setting('automatic_orchestration',True)
    def test_stop_is_adapter_only_and_global_requires_confirmation(self):
        self.connected('claude');self.connected('codex')
        self.adapters['codex'].state='Busy'
        with self.assertRaises(PermissionError):self.core.stop_task()
        self.core.stop_task(confirmed=True)
        self.assertIn('stop',self.adapters['codex'].calls)
        self.assertNotIn('stop',self.adapters['claude'].calls)
    def test_unsupported_capabilities_reject_actions(self):
        self.connected('dot')
        self.adapters['dot'].capabilities=Capabilities()
        with self.assertRaises(NotImplementedError):self.core.send_message('dot','hello',model='invented')
        with self.assertRaises(NotImplementedError):self.core.send_message('dot','hello',effort='invented')
        with self.assertRaises(NotImplementedError):self.core.stop('dot')
        with self.assertRaises(NotImplementedError):self.core.create_session('dot')
    def test_artifact_reads_are_project_scoped_and_redacted(self):
        file=self.repo/'report.md';file.write_text('password=SYNTHETIC_REPORT_SECRET\nsafe',encoding='utf-8')
        artifact=self.core.add_artifact('report','report',path=file)
        self.assertNotIn('SYNTHETIC_REPORT_SECRET',artifact['content'])
        self.assertIn('safe',artifact['content'])
        outside=self.root/'outside.txt';outside.write_text('do not read',encoding='utf-8')
        with self.assertRaises(PermissionError):self.core.add_artifact('report','outside',path=outside)
        with self.assertRaises(PermissionError):self.core.project_file('../outside.txt')
        with self.assertRaises(PermissionError):self.core.safe_artifact_path(self.repo/'auth.json')
    def test_exports_include_records_artifacts_and_escape_html(self):
        self.response(text='<script>example</script> normal text')
        self.core.ingest_event('codex','diff',diff='diff --git a/a b/a\n+new')
        self.core.ingest_event('codex','test',command='pytest',passed=2,failed=0,exit_code=0)
        self.core.prepare_handoff(self.core.messages(agent='claude')[0]['id'],'codex')
        for format in ('md','json','html','zip'):
            path=self.core.export_task(self.task['id'],format,self.root/('task.'+format))
            self.assertGreater(path.stat().st_size,100)
        data=json.loads((self.root/'task.json').read_text(encoding='utf-8'))
        self.assertEqual(2,len(data['artifacts']))
        self.assertEqual(1,len(data['handoffs']))
        exported_html=(self.root/'task.html').read_text(encoding='utf-8')
        self.assertNotIn('<script>example</script>',exported_html)
        self.assertIn('&lt;script&gt;',exported_html)
        with zipfile.ZipFile(self.root/'task.zip') as archive:self.assertIn('task.json',archive.namelist())
    def test_raw_rotates_without_breaking_saved_event_references(self):
        self.core.store.max_raw_bytes=900
        event=self.core.ingest_event('codex','system',content='first raw event')
        for index in range(12):self.core.ingest_event('codex','system',content='later '+str(index)+'x'*300)
        saved=self.core.store.get('events',{'id':event['id']})
        self.assertEqual(event['raw_ref'],saved['raw_ref'])
        raw=self.core.read_raw(saved['raw_ref'])
        self.assertEqual('first raw event',raw['content'])
        self.assertGreater(len(list(self.core.store.raw_dir.glob('*.jsonl*'))),1)

    def test_archive_retention_expiry_and_restart_references(self):
        self.core.store.max_raw_bytes=800
        first=self.core.ingest_event('codex','system',content='safe archived original')
        self.core.ingest_event('codex','system',content='second '+'z'*1000)
        path=self.core.store.data_dir/first['raw_ref'].rsplit(':',1)[0]
        archived=path.with_suffix('.jsonl.gz')
        self.assertTrue(archived.is_file())
        self.assertFalse(path.exists())
        self.assertEqual('safe archived original',self.core.read_raw(first['raw_ref'])['content'])
        unrelated=self.core.store.raw_dir/'user-notes.jsonl'
        unrelated.write_text('user owned content',encoding='utf-8')
        old=time.time()-40*86400
        os.utime(archived,(old,old));os.utime(unrelated,(old,old))
        self.core.store.archive_logs()
        self.assertFalse(archived.exists())
        self.assertTrue(unrelated.exists())
        with self.assertRaisesRegex(FileNotFoundError,'retention'):self.core.read_raw(first['raw_ref'])
        saved=self.core.store.get('events',{'id':first['id']})
        self.assertTrue(saved['raw_ref'].startswith('expired:'))
        self.core.close()
        self.core=WorkspaceCore(self.root/'data')
        with self.assertRaisesRegex(FileNotFoundError,'retention'):self.core.read_raw(first['raw_ref'])

    def test_archive_off_retains_uncompressed_segments(self):
        self.core.set_setting('retention.archive',False)
        self.core.store.max_raw_bytes=800
        first=self.core.ingest_event('codex','system',content='first noncompressed')
        self.core.ingest_event('codex','system',content='second '+'y'*1000)
        path=self.core.store.data_dir/first['raw_ref'].rsplit(':',1)[0]
        self.assertTrue(path.is_file())
        self.assertFalse(path.with_suffix('.jsonl.gz').exists())

    def test_live_partial_secret_prefix_never_reaches_wal(self):
        self.core.ingest_event('codex','message_start')
        secret='sk-proj-SYNTHETIC_SPLIT_PREFIX_CANARY0123456789'
        self.core.ingest_event('codex','message_delta',content=secret[:16])
        self.core.ingest_event('codex','message_delta',content=secret[16:])
        for path in self.core.data_dir.rglob('*'):
            if path.is_file():self.assertNotIn(b'SYNTHETIC_SPLIT',path.read_bytes())
        self.core.ingest_event('codex','message_end')
        self.assertNotIn('SYNTHETIC',self.core.messages(agent='codex')[-1]['content'])

    def test_handoff_annotation_updates_one_preview_without_source_rewrite(self):
        message_id=self.response(text='Preserve A')
        preview=self.core.prepare_handoff(message_id,'codex')
        updated=self.core.update_handoff_annotation(preview['id'],'New note')
        self.assertEqual('Preserve A',updated['source_message'])
        self.assertEqual('New note',updated['annotation'])
        self.assertEqual(1,len(self.core.handoffs()))

    def test_disabled_agent_cannot_connect_and_allowed_config_applies(self):
        self.core.set_setting('agent.claude',{'enabled':False})
        with self.assertRaises(RuntimeError):self.core.connect('claude')
        self.assertEqual([],self.adapters['claude'].calls)
        self.core.set_setting('agent.claude',{'enabled':True,'timeout':27})
        self.core.connect('claude')
        self.assertEqual(27,self.adapters['claude'].settings['timeout'])

    def test_default_project_only_applies_when_agent_has_no_selection(self):
        alternate=self.core.create_project('Saved default',self.repo)
        self.core.set_setting('agent.claude',{'default_project':alternate['id']})
        self.core.connect('claude')
        self.assertEqual(self.project['id'],self.core.current_project_id)
        self.core.current_project_id=None
        self.core.current_task_id=None
        self.core.connect('claude')
        self.assertIsNone(self.core.current_project_id)
        self.assertEqual(alternate['id'],self.core.agent_project('claude')['id'])
        self.assertEqual(alternate['id'],self.adapters['claude'].metadata['project_id'])

    def test_all_known_secret_split_indices_stay_out_of_database_and_raw(self):
        secret='sk-proj-SYNTHETIC_SPLIT_ALL_CANARY01234567890'
        for split in range(1,len(secret)):
            self.core.ingest_event('codex','message_start')
            self.core.ingest_event('codex','message_delta',content=secret[:split])
            self.core.ingest_event('codex','message_delta',content=secret[split:])
            self.core.ingest_event('codex','message_end')
        for path in self.core.data_dir.rglob('*'):
            if path.is_file():self.assertNotIn(b'SYNTHETIC_SPLIT_ALL',path.read_bytes())
    def test_parallel_agent_events_remain_isolated(self):
        errors=[]
        def produce(agent):
            try:
                for index in range(25):self.core.ingest_event(agent,'command',command=agent+'-'+str(index),exit_code=0)
            except Exception as exc:errors.append(exc)
        threads=[threading.Thread(target=produce,args=(agent,)) for agent in self.adapters]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual([],errors)
        for agent in self.adapters:self.assertEqual(25,len(self.core.messages(agent=agent)))
    def test_legacy_reader_redacts_cross_chunk_secret_and_never_writes_source(self):
        legacy=self.root/'legacy';logs=legacy/'logs';logs.mkdir(parents=True)
        logfile=logs/'claude.log';logfile.write_text('password=',encoding='utf-8')
        self.assertEqual([],self.core.poll_legacy(legacy))
        with logfile.open('a',encoding='utf-8') as handle:handle.write('SYNTHETIC_LEGACY_SECRET\nhello\n')
        before=logfile.read_bytes()
        entries=self.core.poll_legacy(legacy)
        self.assertEqual(1,len(entries));self.assertNotIn('SYNTHETIC_LEGACY_SECRET',entries[0]['content'])
        self.assertIn('hello',entries[0]['content'])
        self.assertEqual(before,logfile.read_bytes())
        self.assertEqual([],self.core.poll_legacy(legacy))
    def test_legacy_reader_maps_hermes_log_to_local_panel(self):
        legacy=self.root/'legacy';logs=legacy/'logs';logs.mkdir(parents=True)
        (logs/'hermes.log').write_text('[TOOL] terminal {"command": "npm test"}\n',encoding='utf-8')
        (logs/'timeline.log').write_text('2026-10-15T14:00:00+08:00 | z1 | HERMES | RUN_STARTED | worktree=x\n',encoding='utf-8')
        entries=self.core.poll_legacy(legacy)
        self.assertEqual({'local','timeline'},{entry['agent'] for entry in entries})
        self.assertIn('[TOOL] terminal',next(e['content'] for e in entries if e['agent']=='local'))
        recorded={row['agent'] for row in self.core.store.query("SELECT agent FROM events WHERE type='legacy'")}
        self.assertEqual({'local','workspace'},recorded)
    def test_settings_secret_fields_are_redacted(self):
        self.core.set_setting('token','SYNTHETIC_SETTINGS_SECRET')
        self.assertNotIn('SYNTHETIC_SETTINGS_SECRET',str(self.core.get_setting('token')))
        self.core.set_setting('retention.max_mb',2)
        self.assertEqual(2*1024*1024,self.core.store.max_raw_bytes)

    @staticmethod
    def png_fixture(extra_chunks=()):
        def chunk(kind,payload):
            return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
        return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+
                b''.join(chunk(kind,payload) for kind,payload in extra_chunks)+
                chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b''))

    def test_patch_and_every_export_reject_credential_destinations(self):
        credential=self.root/'auth.json'
        credential.write_text('SYNTHETIC_EXISTING_CREDENTIAL_FILE',encoding='utf-8')
        artifact=self.core.add_artifact('patch','safe change',content='+safe')
        for action in (lambda:self.core.save_patch('+safe',credential),
                       lambda:self.core.export_task(self.task['id'],'json',credential),
                       lambda:self.core.export_diagnostics(credential),
                       lambda:self.core.export_artifact(artifact['id'],credential)):
            with self.assertRaises(PermissionError):action()
        self.assertEqual('SYNTHETIC_EXISTING_CREDENTIAL_FILE',credential.read_text(encoding='utf-8'))
        for name in ('auth.json.','auth.json ','token','report.patch:token','NUL.patch'):
            with self.subTest(name=name),self.assertRaises(PermissionError):self.core.save_patch('+safe',self.root/name)
        with self.assertRaises(PermissionError):self.core.save_patch('+new',self.core.artifact_path(artifact['id']))
        self.assertEqual('+safe',self.core.artifact_path(artifact['id']).read_text(encoding='utf-8'))

    def test_safe_patch_save_redacts_and_does_not_create_arbitrary_directories(self):
        target=self.core.save_patch('+password=SYNTHETIC_PATCH_SECRET\n+ordinary',self.root/'change.patch')
        self.assertIn('+ordinary',target.read_text(encoding='utf-8'))
        self.assertNotIn('SYNTHETIC_PATCH_SECRET',target.read_text(encoding='utf-8'))
        with self.assertRaises(FileNotFoundError):self.core.save_patch('+change',self.root/'missing'/'change.patch')
        self.assertFalse((self.root/'missing').exists())
        with self.assertRaises(ValueError):self.core.save_patch('+change',self.repo/'source.py')

    def test_patch_jsonl_markdown_import_open_and_export(self):
        fixtures=[('change.patch','+password=SYNTHETIC_ARTIFACT_SECRET\n+safe','patch'),
                  ('notes.md','# Safe\npassword=SYNTHETIC_ARTIFACT_SECRET','markdown'),
                  ('events.jsonl',json.dumps({'type':'thinking','thinking':'SYNTHETIC_THOUGHT'})+'\n'+json.dumps({'role':'assistant','content':'safe reply','token':'SYNTHETIC_ARTIFACT_SECRET'})+'\n','jsonl')]
        for filename,text,kind in fixtures:
            source=self.repo/filename;source.write_text(text,encoding='utf-8')
            artifact=self.core.import_artifact(source)
            self.assertEqual(kind,artifact['type'])
            path=self.core.artifact_path(artifact['id'])
            self.assertTrue(path.is_relative_to(self.core.store.artifact_dir))
            self.assertNotIn('SYNTHETIC_ARTIFACT_SECRET',path.read_text(encoding='utf-8'))
            self.assertNotIn('SYNTHETIC_THOUGHT',path.read_text(encoding='utf-8'))
            source.write_text('source changed after import',encoding='utf-8')
            self.assertNotIn('source changed',path.read_text(encoding='utf-8'))
            exported=self.core.export_artifact(artifact['id'],self.root/filename)
            self.assertEqual(path.read_bytes(),exported.read_bytes())
        invalid=self.repo/'bad.jsonl';invalid.write_text('{broken json',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'line 1'):self.core.import_artifact(invalid)
        with self.assertRaises(ValueError):self.core.artifact_path('missing-artifact')

    def test_screenshot_is_explicit_scoped_verified_and_in_zip(self):
        image=self.repo/'screen.png';data=self.png_fixture();image.write_bytes(data)
        with self.assertRaises(PermissionError):self.core.import_artifact(image)
        artifact=self.core.import_artifact(image,user_selected=True)
        self.assertEqual((1,1),(artifact['metadata']['width'],artifact['metadata']['height']))
        self.assertEqual('not performed',artifact['metadata']['pixel_redaction'])
        self.assertTrue(artifact['metadata']['user_selected'])
        self.assertEqual(data,self.core.artifact_path(artifact['id']).read_bytes())
        with self.assertRaises(PermissionError):self.core.export_artifact(artifact['id'],self.root/'export.png')
        exported=self.core.export_artifact(artifact['id'],self.root/'export.png',screenshot_reviewed=True)
        self.assertEqual(data,exported.read_bytes())
        excluded=self.core.export_task(self.task['id'],'zip',self.root/'without-image.zip')
        with zipfile.ZipFile(excluded) as archive:
            self.assertFalse(any(name.endswith('.png') for name in archive.namelist()))
            self.assertIn('image bytes were excluded',archive.read('SCREENSHOT-SECURITY.txt').decode())
        bundle=self.core.export_task(self.task['id'],'zip',self.root/'with-image.zip',include_screenshots=True)
        with zipfile.ZipFile(bundle) as archive:
            name='artifacts/'+artifact['id']+'.png'
            self.assertEqual(data,archive.read(name))
            self.assertIn('not automatically redacted',archive.read('SCREENSHOT-SECURITY.txt').decode())
        outside=self.root/'outside.png';outside.write_bytes(data)
        with self.assertRaises(PermissionError):self.core.import_artifact(outside,user_selected=True)

    def test_screenshot_rejects_fake_extension_bad_crc_and_sensitive_metadata(self):
        image=self.repo/'screen.png'
        for invalid in (b'not an image',self.png_fixture()+b'trailing hidden payload',
                        self.png_fixture().replace(b'IDAT',b'IDAX'),
                        self.png_fixture([(b'tEXt',b'Comment\0password=SYNTHETIC_IMAGE_META_SECRET')]),
                        self.png_fixture([(b'iTXt',b'Comment\0\x01\x00\0\0'+zlib.compress(b'password=SYNTHETIC_COMPRESSED_META_SECRET'))]),
                        self.png_fixture([(b'zTXt',b'Comment\0\x00'+zlib.compress(b'ordinary text'))]),
                        self.png_fixture([(b'eXIf',b'arbitrary hidden metadata')]),
                        self.png_fixture([(b'zzZZ',b'unknown ancillary payload')])):
            image.write_bytes(invalid)
            with self.assertRaises(ValueError):self.core.import_artifact(image,user_selected=True)
        self.assertEqual([],self.core.artifacts())

    def test_real_jpeg_fixture_signature_dimensions_and_export(self):
        # One black pixel encoded by Windows System.Drawing; no external file dependency.
        encoded='/9j/4AAQSkZJRgABAQEAeAB4AAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD8qqKKKAP/2Q=='
        source=self.repo/'screen.jpeg';source.write_bytes(base64.b64decode(encoded))
        artifact=self.core.import_artifact(source,user_selected=True)
        self.assertEqual('image/jpeg',artifact['metadata']['mime_type'])
        self.assertEqual(1,artifact['metadata']['width'])
        self.assertEqual(source.read_bytes(),self.core.export_artifact(artifact['id'],self.root/'out.jpg',screenshot_reviewed=True).read_bytes())
        source.write_bytes(source.read_bytes()[:2]+b'\xff\xfe\x00\x06note'+source.read_bytes()[2:])
        with self.assertRaisesRegex(ValueError,'APP/COM metadata'):self.core.import_artifact(source,user_selected=True)

    def test_export_and_managed_writes_reject_linked_ancestors(self):
        from acw.security import safe_export_path
        original=Path.is_symlink
        def synthetic_link(path):
            return path==self.root or original(path)
        with patch.object(Path,'is_symlink',synthetic_link):
            with self.assertRaises(PermissionError):safe_export_path(self.root/'change.patch')
            with self.assertRaises(PermissionError):self.core.add_artifact('patch','managed',content='+safe')

    def test_diff_snapshot_preserves_native_errors_and_unborn_notice(self):
        failure={'command':'git diff HEAD','cwd':str(self.repo),'stdout':'','stderr':'fatal: missing HEAD password=SYNTHETIC_GIT_SECRET','exit_code':128,'changed_files':[]}
        with patch('acw.inspection.git_diff',return_value=failure):result=self.core.diff_snapshot()
        self.assertEqual(128,result['exit_code'])
        self.assertIn('missing HEAD',result['stderr'])
        self.assertNotIn('SYNTHETIC_GIT_SECRET',result['stderr'])
        unborn={'command':'git diff --cached','cwd':str(self.repo),'stdout':'+new','stderr':'','exit_code':0,
                'changed_files':['new.txt'],'unborn':True,'notice':'No HEAD yet; staged additions shown','scope':'staged and unstaged','components':[]}
        with patch('acw.inspection.git_diff',return_value=unborn):result=self.core.diff_snapshot()
        self.assertEqual('+new',result['diff'])
        self.assertTrue(result['unborn'])
        self.assertEqual(unborn['notice'],result['notice'])

    def test_git_snapshot_keeps_diff_and_log_status(self):
        with patch('acw.inspection.git_snapshot',return_value={'branch':'test','error':'','ahead':None,'behind':None}), \
             patch('acw.inspection.git_diff',return_value={'stdout':'','stderr':'diff error','exit_code':128}), \
             patch('acw.inspection.git_read',return_value={'stdout':'','stderr':'log error','exit_code':128}):
            result=WorkspaceCore.git_snapshot(self.core)
        self.assertEqual(128,result['diff_exit_code'])
        self.assertEqual('diff error',result['diff_error'])
        self.assertEqual('log error',result['log_result']['stderr'])
        self.assertIsNone(result['ahead'])

    def test_native_session_import_never_connects_resumes_or_changes_task_mapping(self):
        original=dict(self.core.current_task)
        native={'id':'native-synthetic-session','name':'Discovered native session','cwd':str(self.repo),'source':'native','token':'SYNTHETIC_NATIVE_SECRET'}
        row=self.core.import_session('claude',native)
        self.assertEqual('native-synthetic-session',row['id'])
        self.assertIsNone(row['task_id'])
        self.assertTrue(row['metadata']['imported_native'])
        self.assertEqual(original,self.core.current_task)
        self.assertEqual([],self.adapters['claude'].calls)
        self.assertEqual('',self.adapters['claude'].session_id)
        self.assertNotIn('SYNTHETIC_NATIVE_SECRET',json.dumps(row))
        self.assertEqual(row,self.core.import_session('claude',native))
        self.assertEqual(1,len(self.core.sessions('claude')))

    def test_discovery_is_explicit_and_read_only(self):
        calls=[]
        self.adapters['claude'].list_sessions=lambda **kwargs:calls.append(kwargs) or [{'id':'native'}]
        self.assertEqual([],calls)
        self.assertEqual([{'id':'native'}],self.core.discover_sessions('claude',limit=20,offset=3))
        self.assertEqual([{'native':True,'limit':20,'offset':3}],calls)
        self.assertEqual([],self.core.sessions('claude'))
        self.assertEqual('',self.core.current_task['claude_session'])

    def test_task_project_file_and_command_full_text_search(self):
        self.core.update_project(self.project['id'],notes='project-specific-needle')
        self.core.update_task(self.task['id'],notes='task-specific-needle')
        self.core.ingest_event('codex','file',path='unique-filename-needle.py',content='changed')
        self.core.ingest_event('codex','command',command='python unique-command-needle.py',exit_code=0)
        self.core.add_artifact('markdown','artifact-specific-needle',content='body')
        expectations={'project-specific-needle':'projects','task-specific-needle':'tasks','unique-filename-needle':'events',
                      'unique-command-needle':'messages','artifact-specific-needle':'artifacts'}
        for text,kind in expectations.items():
            with self.subTest(text=text):self.assertTrue(any(row['kind']==kind for row in self.core.search(text)))

    def test_tool_and_safe_raw_content_survive_persistence_with_secret_redaction(self):
        payload={'type':'ordinary_result','result':{'text':'preserve exact safe text','exit_code':0}}
        event=self.core.ingest_event('codex','raw',raw=payload)
        self.assertEqual(payload,self.core.read_raw(event['raw_ref'])['raw'])
        self.core.ingest_event('claude','tool_start',tool='synthetic-tool',arguments={'path':'note.txt','token':'SYNTHETIC_TOOL_SECRET'},started='2026-01-01T00:00:00Z')
        self.core.ingest_event('claude','tool_result',tool='synthetic-tool',result='safe result',status='complete',duration=0.25)
        messages=self.core.messages(agent='claude')
        self.assertEqual(['tool','tool'],[message['role'] for message in messages])
        self.assertNotIn('SYNTHETIC_TOOL_SECRET',json.dumps(messages))
        self.assertEqual(0.25,messages[-1]['metadata']['duration'])
        self.assertEqual('safe result',messages[-1]['metadata']['result'])

    def native_history_fixture(self):
        calls=[]
        adapter=self.adapters['claude']
        record={'id':'native-history-fixture','cwd':str(self.repo),'source':'native'}
        adapter.list_sessions=lambda **kwargs:[record]
        adapter.native_history_capability=lambda:{'supported':True,'available':True,'read_only':True,'source':'synthetic helper'}
        def history(session_id,**kwargs):
            calls.append((session_id,kwargs))
            return [{'role':'assistant','content':'NATIVE_MEMORY_ONLY_CANARY','token':'SYNTHETIC_NATIVE_SECRET'},
                    {'type':'thinking','thinking':'SYNTHETIC_NATIVE_REASONING'}]
        adapter.get_history=history
        return calls,record

    def test_native_history_requires_explicit_discovery_and_never_persists_or_maps(self):
        calls,record=self.native_history_fixture()
        original=dict(self.core.current_task)
        with self.assertRaises(PermissionError):self.core.native_history('claude',record['id'])
        self.assertEqual([],calls)
        self.assertTrue(self.core.native_history_capability('claude')['supported'])
        self.assertEqual([],calls)
        self.core.discover_sessions('claude')
        self.assertEqual([],calls)
        before=len(self.core.events())
        result=self.core.native_history('claude',record['id'],limit=50,offset=2)
        self.assertEqual([(record['id'],{'native':True,'limit':50,'offset':2})],calls)
        self.assertNotIn('SYNTHETIC_NATIVE_SECRET',json.dumps(result))
        self.assertNotIn('SYNTHETIC_NATIVE_REASONING',json.dumps(result))
        self.assertIn('NATIVE_MEMORY_ONLY_CANARY',json.dumps(result))
        self.assertEqual(original,self.core.current_task)
        self.assertEqual([],self.core.sessions('claude'))
        self.assertEqual([],self.core.messages(agent='claude'))
        self.assertEqual(before,len(self.core.events()))
        self.assertEqual([],self.adapters['claude'].calls)
        for path in self.core.data_dir.rglob('*'):
            if path.is_file():self.assertNotIn(b'NATIVE_MEMORY_ONLY_CANARY',path.read_bytes())

    def test_native_history_rejects_unknown_and_mismatched_project_before_reader(self):
        calls,record=self.native_history_fixture()
        self.core.discover_sessions('claude')
        with self.assertRaises(PermissionError):self.core.native_history('claude','undiscovered-session')
        record['cwd']=str(self.root)
        self.core.discover_sessions('claude')
        with self.assertRaisesRegex(PermissionError,'does not belong'):self.core.native_history('claude',record['id'])
        record['cwd']=str(self.repo)
        self.core.discover_sessions('claude')
        alternate=self.core.create_project('Different project identity',self.repo)
        self.core.select_project(alternate['id'])
        with self.assertRaisesRegex(PermissionError,'Discover native sessions'):self.core.native_history('claude',record['id'])
        self.assertEqual([],calls)

    def test_native_history_propagates_backend_errors_without_recording_transcript(self):
        calls,record=self.native_history_fixture()
        self.core.discover_sessions('claude')
        def missing(*args,**kwargs):raise FileNotFoundError('Official SDK: transcript no longer exists')
        self.adapters['claude'].get_history=missing
        with self.assertRaisesRegex(FileNotFoundError,'transcript no longer exists'):self.core.native_history('claude',record['id'])
        def sensitive(*args,**kwargs):raise RuntimeError('Backend failure password=SYNTHETIC_ERROR_SECRET')
        self.adapters['claude'].get_history=sensitive
        with self.assertRaises(RuntimeError) as caught:self.core.native_history('claude',record['id'])
        self.assertNotIn('SYNTHETIC_ERROR_SECRET',str(caught.exception))
        self.assertEqual([],self.core.messages(agent='claude'))

    def test_native_history_unavailable_helper_and_project_change_are_not_silent(self):
        calls,record=self.native_history_fixture()
        self.core.discover_sessions('claude')
        self.adapters['claude'].native_history_capability=lambda:{'supported':False,'available':False,'reason':'Official SDK helper unavailable'}
        self.assertFalse(self.core.native_history_capability('claude')['supported'])
        with self.assertRaisesRegex(NotImplementedError,'Official SDK helper unavailable'):self.core.native_history('claude',record['id'])
        self.assertEqual([],calls)
        self.adapters['claude'].native_history_capability=lambda:{'supported':True,'available':True}
        alternate=self.core.create_project('Switched during preview',self.repo)
        def switch(*args,**kwargs):
            self.core.select_project(alternate['id'])
            return [{'content':'NATIVE_DISCARDED_PREVIEW'}]
        self.adapters['claude'].get_history=switch
        with self.assertRaisesRegex(PermissionError,'preview discarded'):self.core.native_history('claude',record['id'])
        self.assertEqual([],self.core.messages(agent='claude'))

class NativeSessionAvailabilityTests(unittest.TestCase):
    """Use the production Core and real isolated transcript files, not the routing double."""
    def setUp(self):
        from acw.core import WorkspaceCore as NativeCore
        from acw import desktop_sessions
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.claude_root = self.root / 'claude'
        self.codex_root = self.root / 'codex'
        self.claude_root.mkdir()
        self.codex_root.mkdir()
        for target, result in (('transcript_roots', [self.claude_root]), ('codex_roots', [self.codex_root])):
            guard = patch.object(desktop_sessions, target, return_value=result)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(desktop_sessions, '_HISTORY_FILES', {})
        guard.start()
        self.addCleanup(guard.stop)
        self.adapters = {agent: SyntheticAdapter(agent) for agent in ('claude', 'codex', 'local')}
        self.core = NativeCore(self.root / 'data', self.adapters)
        self.addCleanup(self.core.close)
        self.core.git_snapshot = lambda *a, **k: {'branch': 'fixture'}
        self.core.select_project(self.core.create_project('Fixture', self.root)['id'])
        self.task = self.core.create_task('Missing transcript fixture')
        self.sid = '12345678-1234-4234-8234-123456789abc'

    def test_session_available_uses_real_claude_and_codex_transcript_roots(self):
        for agent, root, relative in (
                ('claude', self.claude_root, 'project/' + self.sid + '.jsonl'),
                ('codex', self.codex_root, 'sessions/2026/10/16/rollout-fixture-' + self.sid + '.jsonl')):
            self.assertFalse(self.core.session_available(agent, self.sid))
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}\n', encoding='utf-8')
            self.assertTrue(self.core.session_available(agent, self.sid))
            path.unlink()
            self.assertFalse(self.core.session_available(agent, self.sid))
        self.assertTrue(self.core.session_available('local', 'opaque-hermes-id'))

    def test_missing_bound_session_is_cleared_without_resume_or_resend(self):
        self.core._set_task_session(self.task['id'], 'claude', self.sid)
        self.adapters['claude'].state = 'Connected'
        self.adapters['claude'].session_id = self.sid
        self.adapters['claude'].calls.clear()
        with self.assertRaisesRegex(ValueError, '此對話的紀錄已不存在（12345678），請開新對話'):
            self.core.prepare_conversation('claude')
        self.assertEqual('', self.core.agent_task('claude')['claude_session'])
        self.assertEqual(self.sid, self.core.missing_session('claude'))
        self.assertEqual([], self.adapters['claude'].calls)
        events = self.core.store.query("SELECT * FROM events WHERE type='session_missing'")
        self.assertEqual(1, len(events))
        self.assertIn('12345678', events[0]['summary'])
        with self.assertRaises(ValueError):
            self.core.prepare_conversation('claude')
        self.core.prepare_conversation('claude', fresh=True)
        self.assertIn('create_session', self.adapters['claude'].calls)
        self.assertIsNone(self.core.missing_session('claude'))

    def test_resume_and_open_saved_session_check_before_adapter_calls(self):
        self.core._set_task_session(self.task['id'], 'codex', self.sid)
        self.adapters['codex'].state = 'Connected'
        self.core.store.insert('sessions', dict(id=self.sid, agent='codex', task_id=self.task['id'],
            project_id=self.task['project_id'], cwd=str(self.root), created_at='2026-10-16', updated_at='2026-10-16'))
        for operation in (lambda: self.core.resume_session('codex', self.sid),
                          lambda: self.core.open_saved_conversation('codex', self.sid)):
            self.adapters['codex'].calls.clear()
            with self.assertRaisesRegex(ValueError, '紀錄已不存在'):
                operation()
            self.assertEqual([], self.adapters['codex'].calls)


if __name__=='__main__':unittest.main()
