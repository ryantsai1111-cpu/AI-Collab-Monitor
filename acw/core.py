"""UI-independent workspace orchestration. No adapter is connected on startup."""
from __future__ import annotations
import html
import json
import queue
import shutil
import threading
import zipfile
from pathlib import Path
from .security import sanitize, safe_file, is_secret_path, is_hidden_reasoning, safe_export_path, verify_screenshot, reject_link_ancestors
from .store import Store, now, uid

AGENTS = ('claude','dot','codex','local')
TASK_STATUSES = ('NEW','PLANNING','REVIEWING','READY','IMPLEMENTING','VERIFYING','WAITING_USER','BLOCKED','DONE','FAILED','CANCELLED')
ARTIFACT_TYPES = {'diff','patch','test','test log','report','screenshot','jsonl','markdown'}
ARTIFACT_SUFFIXES={'diff':'.diff','patch':'.patch','test':'.log','test log':'.log','report':'.txt','jsonl':'.jsonl','markdown':'.md'}

class WorkspaceCore:
    def __init__(self,data_dir,adapters=None):
        self.store=Store(data_dir)
        self.data_dir=self.store.data_dir
        self.adapters={}
        self._lock=threading.RLock()
        self._queue=queue.Queue()
        self._contexts={}
        self._streams={}
        self._closed=False
        self._legacy_readers={}
        self._native_discovery={}
        self.current_project_id=self.store.get_setting('current_project_id')
        self.current_task_id=self.store.get_setting('current_task_id')
        self._recover()
        for agent,adapter in (adapters or {}).items():
            self.set_adapter(agent,adapter)
        self.store.max_raw_bytes=max(1024,int(float(self.get_setting('retention.max_mb',self.get_setting('logs.max_size',10*1024*1024)/1024/1024))*1024*1024))
        self.store.retention_days=max(1,int(self.get_setting('retention.days',self.get_setting('logs.retention_days',30))))
        self.store.archive_enabled=bool(self.get_setting('retention.archive',True))
        self.store.archive_logs()

    @property
    def current_project(self):
        return self.get_project(self.current_project_id) if self.current_project_id else None

    @property
    def current_task(self):
        return self.get_task(self.current_task_id) if self.current_task_id else None

    def _recover(self):
        for message in self.store.query("SELECT id,task_id,agent,session_id FROM messages WHERE status='streaming'"):
            self.store.update('messages',{'id':message['id']},{'status':'interrupted'})
            self._record('recovery',message['agent'],task_id=message['task_id'],session_id=message['session_id'],
                         content='Previous stream interrupted; history restored. Prompt was not resent.')
        for handoff in self.store.query("SELECT id FROM handoffs WHERE status='sending'"):
            self.store.update('handoffs',{'id':handoff['id']},{'status':'delivery_unknown'})

    def set_adapter(self,agent,adapter):
        self._check_agent(agent)
        adapter.emit=self.make_emitter(agent)
        self.adapters[agent]=adapter
        return adapter

    def make_emitter(self,agent):
        self._check_agent(agent)
        def emit(kind,**payload):
            if not self._closed:
                return self.ingest_event(agent,kind,**payload)
        return emit

    @staticmethod
    def _check_agent(agent):
        if agent not in AGENTS: raise ValueError('Unknown agent')

    def _adapter(self,agent):
        self._check_agent(agent)
        if agent not in self.adapters: raise RuntimeError(f'{agent}: backend is unavailable')
        return self.adapters[agent]

    def connect(self,agent):
        adapter=self._adapter(agent)
        settings=self.get_setting('agent.'+agent,{})
        if not settings.get('enabled',True): raise RuntimeError(f'{agent}: disabled in Settings')
        if agent=='local' and hasattr(adapter,'local_harness'):
            if adapter.state in ('Connected','Busy','Connecting'):
                raise RuntimeError('請先中斷本地模型連線，再套用設定')
            from .adapters.local import make_local_adapter
            defaults={key:adapter.settings[key] for key in ('codex_executable','claude_executable','attachment_roots') if key in adapter.settings}
            replacement=make_local_adapter(self.make_emitter(agent),**dict(defaults,**settings))
            if replacement.local_harness==adapter.local_harness:
                replacement.session_id=adapter.session_id
                if hasattr(adapter,'_resume'): replacement._resume=adapter._resume
            if adapter._process:
                adapter.disconnect()
            adapter=self.set_adapter(agent,replacement)
        if not self.current_project and settings.get('default_project'):
            self.select_project(settings['default_project'])
        if settings.get('executable'): adapter.executable=settings['executable']
        if settings.get('timeout'): adapter.settings['timeout']=float(settings['timeout'])
        if self.current_project: self._apply_project(agent,self.current_project)
        return adapter.connect()

    def disconnect(self,agent):
        return self._adapter(agent).disconnect()

    def capabilities(self,agent):
        adapter=self.adapters.get(agent)
        if not adapter:
            return {key:False for key in ('supports_model_selection','supports_effort','supports_sessions','supports_files',
                    'supports_tools','supports_project','supports_cancel','supports_streaming','supports_history','supports_approval')}
        cap=adapter.capabilities
        return sanitize(cap.to_dict() if hasattr(cap,'to_dict') else dict(cap))

    def list_models(self,agent): return sanitize(self._adapter(agent).list_models())
    def list_efforts(self,agent,model=None): return sanitize(self._adapter(agent).list_efforts(model))

    def diagnostics(self,agent=None):
        if agent:
            adapter=self.adapters.get(agent)
            result=adapter.diagnostics() if adapter else {'agent':agent,'state':'Offline','last_error':'Adapter unavailable'}
            recent=self.events(agent=agent,limit=1)
            result['last_event']=recent[0]['timestamp'] if recent else ''
            return sanitize(result)
        return {'data_dir':str(self.data_dir),'project':self.current_project,'task':self.current_task,
                'agents':{a:self.diagnostics(a) for a in AGENTS},'automatic_orchestration':'OFF',
                  'raw_policy':'Secret redaction and hidden reasoning exclusion override raw fidelity.'}

    def attachment_capability(self,agent,model=None):
        return sanitize(self._adapter(agent).attachment_capability(model))

    def create_project(self,name,repo_path,**metadata):
        repo=Path(repo_path).expanduser().resolve()
        if not repo.is_dir(): raise ValueError('Project directory does not exist')
        if not str(name).strip(): raise ValueError('Project name is required')
        project=dict(id=metadata.pop('id',uid('project-')),name=name,repo_path=str(repo),created_at=now(),
                     default_branch=metadata.pop('default_branch',''),active_branch=metadata.pop('active_branch',''),
                     claude_cwd=str(repo),codex_cwd=str(repo),local_cwd=str(repo),dot_metadata='',notes=metadata.pop('notes',''),metadata=metadata)
        self.store.insert('projects',project)
        return self.get_project(project['id'])

    def list_projects(self): return self.store.query('SELECT * FROM projects ORDER BY name')
    def get_project(self,project_id): return self.store.get('projects',{'id':project_id})

    def update_project(self,project_id,**fields):
        if not fields.keys()<={'name','default_branch','active_branch','notes','metadata'}: raise ValueError('Unsupported project field')
        self.store.update('projects',{'id':project_id},fields)
        return self.get_project(project_id)

    def _assert_idle(self):
        busy=[a for a,v in self.adapters.items() if getattr(v,'state','')=='Busy']
        if busy: raise RuntimeError('Stop or wait for active agents before changing task/project: '+', '.join(busy))

    def select_project(self,project_id,sync=True,*,drafts=None,confirmed=False):
        project=self.get_project(project_id)
        if not project: raise ValueError('Unknown project')
        if project_id!=self.current_project_id:
            self._assert_idle()
            if drafts and any(str(v).strip() for v in drafts.values()) and not confirmed:
                raise PermissionError('Confirm discarding unsent drafts before changing project')
            self.current_project_id=project_id
            self.set_setting('current_project_id',project_id)
            task=self.current_task
            if task and task['project_id']!=project_id:
                self.current_task_id=None
                self.set_setting('current_task_id',None)
            self._contexts.clear()
            self._record('project_changed',project_id=project_id,content=project['name'])
        if sync: self.sync_project()
        return project

    def _project_metadata(self,project):
        task=self.current_task
        branch=self.git_snapshot(project['id']).get('branch') or project['active_branch']
        return {'project_id':project['id'],'project_name':project['name'],'repo_name':Path(project['repo_path']).name,
                'branch':branch,'task_id':task['id'] if task else None,'task_title':task['title'] if task else None}

    def _apply_project(self,agent,project):
        path='' if agent=='dot' else project[f'{agent}_cwd'] or project['repo_path']
        self._adapter(agent).set_project(path,self._project_metadata(project))

    def sync_project(self):
        project=self.current_project
        if not project: raise ValueError('Select a project first')
        for agent in self.adapters: self._apply_project(agent,project)
        self._record('project_synced',content=project['name'],metadata=self._project_metadata(project))

    def create_task(self,title,project_id=None,**metadata):
        project=self.get_project(project_id or self.current_project_id)
        if not project: raise ValueError('Select a project before creating a task')
        if not str(title).strip(): raise ValueError('Task title is required')
        status=metadata.pop('status','NEW')
        if status not in TASK_STATUSES: raise ValueError('Invalid task status')
        task=dict(id=metadata.pop('task_id',uid('task-')),title=title,project_id=project['id'],repo=project['repo_path'],
                  branch=metadata.pop('branch',self.git_snapshot(project['id']).get('branch','')),created_at=now(),updated_at=now(),
                  status=status,created_by=metadata.pop('created_by','user'),current_owner=metadata.pop('current_owner','user'),
                  notes=metadata.pop('notes',''),metadata=metadata)
        self.store.insert('tasks',task)
        self.select_task(task['id'])
        return self.get_task(task['id'])

    def get_task(self,task_id): return self.store.get('tasks',{'id':task_id})

    def list_tasks(self,project_id=None,agent=None,status=None,date_from=None,date_to=None,branch=None,error=False,search=None):
        clauses,values=[],[]
        for key,value in [('project_id',project_id),('status',status),('branch',branch)]:
            if value is not None: clauses.append(f't.{key}=?'); values.append(value)
        if agent:
            self._check_agent(agent)
            clauses.append('EXISTS (SELECT 1 FROM messages m WHERE m.task_id=t.id AND m.agent=?)'); values.append(agent)
        if date_from: clauses.append('t.created_at>=?'); values.append(date_from)
        if date_to: clauses.append('t.created_at<=?'); values.append(date_to+'T23:59:59.999+00:00' if len(date_to)==10 else date_to)
        if error: clauses.append("EXISTS (SELECT 1 FROM events e WHERE e.task_id=t.id AND e.type='error')")
        if search:
            clauses.append('(t.title LIKE ? OR t.notes LIKE ? OR t.id LIKE ?)'); values.extend(['%'+search+'%']*3)
        return self.store.query('SELECT t.* FROM tasks t'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY t.created_at DESC',values)

    def select_task(self,task_id):
        task=self.get_task(task_id)
        if not task: raise ValueError('Unknown task')
        if task_id!=self.current_task_id:
            self._assert_idle()
            self.current_project_id=task['project_id']
            self.current_task_id=task_id
            self.set_setting('current_project_id',task['project_id'])
            self.set_setting('current_task_id',task_id)
            self._contexts.clear()
            self._record('task_changed',task_id=task_id,content=task['title'])
        return task

    def update_task(self,task_id,**fields):
        if not fields.keys()<={'title','status','notes','current_owner','branch','metadata'}: raise ValueError('Unsupported task field')
        if 'status' in fields and fields['status'] not in TASK_STATUSES: raise ValueError('Invalid task status; workspace cannot assign APPROVED')
        fields['updated_at']=now()
        self.store.update('tasks',{'id':task_id},fields)
        return self.get_task(task_id)

    def sessions(self,agent=None):
        return self.store.query('SELECT * FROM sessions'+(' WHERE agent=?' if agent else '')+' ORDER BY updated_at DESC',(agent,) if agent else ())

    def list_sessions(self,agent): return sanitize(self._adapter(agent).list_sessions())

    def discover_sessions(self,agent,limit=100,offset=0):
        """Explicit operator action only; discovers metadata without mapping or resuming."""
        adapter=self._adapter(agent)
        project=self.current_project
        if not project: raise ValueError('Select a project before native session discovery')
        directory=str(Path(project['repo_path']).resolve())
        if not getattr(adapter,'cwd','') or Path(adapter.cwd).resolve()!=Path(directory):
            raise PermissionError('Sync the selected project before native session discovery')
        if agent=='claude':
            records=sanitize(adapter.list_sessions(native=True,limit=limit,offset=offset))
        else:
            records=sanitize(adapter.list_sessions())
        if self.current_project_id!=project['id'] or Path(adapter.cwd).resolve()!=Path(directory):
            raise PermissionError('Project changed during native discovery; discover again in the selected project')
        with self._lock:
            existing=self._native_discovery.get(agent)
            if not existing or existing['project_id']!=project['id'] or offset==0:
                existing={'project_id':project['id'],'cwd':directory,'sessions':{}}
                self._native_discovery[agent]=existing
            for record in records:
                if not isinstance(record,dict): continue
                session_id=record.get('id') or record.get('session_id')
                if isinstance(session_id,str) and session_id:
                    existing['sessions'][session_id]=dict(record)
        return records

    def native_history_capability(self,agent):
        """Probe only the adapter's public helper capability, never discover/read sessions."""
        adapter=self._adapter(agent)
        probe=getattr(adapter,'native_history_capability',None)
        if not callable(probe):
            return {'supported':False,'available':False,'read_only':True,'detail':'Native history preview Unsupported by this backend'}
        try:
            result=sanitize(probe())
        except Exception as exc:
            return {'supported':False,'available':False,'read_only':True,'detail':sanitize(str(exc))}
        if not isinstance(result,dict):
            return {'supported':False,'available':False,'read_only':True,'detail':'Native history capability response is unavailable'}
        result['supported']=bool(result.get('supported') and result.get('available',True))
        result['detail']=str(result.get('detail') or result.get('reason') or ('Official read-only native history helper available' if result['supported'] else 'Native history preview unavailable'))
        return result

    def native_history(self,agent,session_id,limit=200,offset=0):
        """Explicit selected native preview, never persisted or mapped into workspace tasks."""
        adapter=self._adapter(agent)
        project=self.current_project
        if not project: raise ValueError('Select a project before viewing native history')
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=500:
            raise ValueError('Native history page limit must be between 1 and 500')
        if isinstance(offset,bool) or not isinstance(offset,int) or not 0<=offset<=10000:
            raise ValueError('Native history page offset must be between 0 and 10000')
        directory=Path(project['repo_path']).resolve()
        cache=self._native_discovery.get(agent)
        if not cache or cache['project_id']!=project['id'] or Path(cache['cwd'])!=directory:
            raise PermissionError('Discover native sessions in the current project before viewing history')
        record=cache['sessions'].get(session_id)
        if not record:
            raise PermissionError('Explicitly select a discovered session before viewing native history')
        if not record.get('cwd') or Path(record['cwd']).resolve()!=directory:
            raise PermissionError('Discovered native session does not belong to the current project')
        if not getattr(adapter,'cwd','') or Path(adapter.cwd).resolve()!=directory:
            raise PermissionError('Adapter working directory differs from the current project')
        capability=self.native_history_capability(agent)
        if not capability['supported']: raise NotImplementedError(capability['detail'])
        try:
            result=adapter.get_history(session_id,native=True,limit=limit,offset=offset)
        except Exception as exc:
            # Preserve useful backend exception types/details while excluding secrets.
            cleaned=sanitize(str(exc))
            if cleaned==str(exc): raise
            raise RuntimeError(cleaned) from None
        if self.current_project_id!=project['id'] or Path(adapter.cwd).resolve()!=directory:
            raise PermissionError('Project changed during native history read; preview discarded')
        return sanitize(result)

    def import_session(self,agent,native_record):
        """Register selected native metadata locally; never contact the agent or change a task."""
        self._check_agent(agent)
        if not isinstance(native_record,dict): raise ValueError('Native session metadata must be an object')
        record=sanitize(native_record)
        session_id=record.get('id') or record.get('session_id')
        if not isinstance(session_id,str) or not session_id.strip() or len(session_id)>512 or any(ord(c)<32 for c in session_id):
            raise ValueError('Invalid native session identifier')
        identity={'agent':agent,'id':session_id}
        existing=self.store.get('sessions',identity)
        if existing: return existing
        metadata={key:record[key] for key in ('source','branch','createdAt','updatedAt','created_at','updated_at','modelProvider') if key in record}
        metadata.update(imported_native=True,read_only=True)
        cwd=str(record.get('cwd') or record.get('projectPath') or record.get('directory') or '')
        project=self.current_project
        project_id=project['id'] if project and cwd and Path(cwd).resolve()==Path(project['repo_path']).resolve() else None
        title=str(record.get('title') or record.get('name') or record.get('summary') or record.get('firstPrompt') or record.get('preview') or '')
        self.store.insert('sessions',dict(identity,task_id=None,project_id=project_id,title=title,cwd=cwd,
            created_at=now(),updated_at=now(),metadata=metadata))
        self._record('session_imported',agent,task_id=None,session_id=session_id,content='Native session metadata imported; explicit Resume is still required.')
        return self.store.get('sessions',identity)

    def desktop_sessions(self):
        """Explicit picker read of the Claude desktop app's local session list (metadata only)."""
        from .desktop_sessions import list_desktop_sessions
        return sanitize(list_desktop_sessions())

    def _project_for_directory(self,directory):
        directory=Path(directory)
        if not directory.is_dir(): raise ValueError('此對話的資料夾已不存在：'+str(directory))
        directory=directory.resolve()
        for project in self.list_projects():
            try:
                if Path(project['repo_path']).resolve()==directory: return project
            except OSError: continue
        return self.create_project(directory.name or str(directory),directory)

    def open_desktop_project(self,directory,title='新對話'):
        """Select (or create) the project for a desktop folder and start a fresh task in it."""
        self._assert_idle()
        project=self._project_for_directory(directory)
        self.select_project(project['id'])
        task=self.create_task(title)
        return {'project_id':project['id'],'task_id':task['id']}

    def open_desktop_session(self,record,history_limit=200):
        """Map one explicitly chosen desktop session to a project and task, with its visible history.

        Never contacts the agent: resuming stays a separate explicit call."""
        from .desktop_sessions import read_transcript, _valid_id
        if not isinstance(record,dict): raise ValueError('Desktop session metadata must be an object')
        session_id=str(record.get('id') or '').lower()
        if not _valid_id(session_id): raise ValueError('Invalid Claude session identifier')
        self._assert_idle()
        project=self._project_for_directory(str(record.get('cwd') or ''))
        self.select_project(project['id'])
        title=sanitize(str(record.get('title') or session_id))[:200]
        task=next((t for t in self.list_tasks(project_id=project['id']) if t.get('claude_session')==session_id),None)
        if task: self.select_task(task['id'])
        else: task=self.create_task(title)
        identity={'agent':'claude','id':session_id}
        fields=dict(task_id=task['id'],project_id=project['id'],title=title,cwd=project['repo_path'],updated_at=now())
        if self.store.get('sessions',identity): self.store.update('sessions',identity,fields)
        else: self.store.insert('sessions',dict(identity,**fields,created_at=now(),metadata={'source':'claude-desktop','imported_native':True}))
        self.store.update('tasks',{'id':task['id']},{'claude_session':session_id,'updated_at':now()})
        self._contexts.clear()
        known={(m['role'],str(m['content']).strip()) for m in self.messages(task['id'],'claude')}
        imported=0
        for message in read_transcript(session_id,history_limit):
            content=sanitize(message['content'])
            message_id='desktop-'+session_id+'-'+message['id']
            if not message['id'] or is_hidden_reasoning(content) or (message['role'],str(content).strip()) in known: continue
            if self.store.get('messages',{'id':message_id}): continue
            self.store.insert('messages',dict(id=message_id,task_id=task['id'],agent='claude',session_id=session_id,
                role=message['role'],content=content,timestamp=message['timestamp'] or now(),status='complete',
                metadata={'source':'claude-desktop','imported':True}))
            imported+=1
        self._record('session_imported','claude',task_id=task['id'],session_id=session_id,
                     content=f'Claude desktop session opened; {imported} visible messages imported. Resume is a separate action.')
        return {'project_id':project['id'],'task_id':task['id'],'session_id':session_id,'imported':imported}

    def _context(self,agent):
        if agent not in self._contexts:
            task=self.current_task or {}
            self._contexts[agent]={'task_id':task.get('id'),'project_id':task.get('project_id',self.current_project_id),
                                   'session_id':task.get(agent+'_session','')}
        return self._contexts[agent]

    def _map_session(self,agent,session_id):
        if not session_id: return
        context=self._context(agent)
        context['session_id']=session_id
        task=self.get_task(context['task_id']) if context.get('task_id') else None
        project=self.get_project(context['project_id']) if context.get('project_id') else None
        identity={'agent':agent,'id':session_id}
        fields={'task_id':task['id'] if task else None,'project_id':project['id'] if project else None,
                'cwd':getattr(self.adapters.get(agent),'cwd',''),'updated_at':now()}
        if agent=='local' and hasattr(self.adapters.get(agent),'local_harness'):
            existing=self.store.get('sessions',identity) or {}
            fields['metadata']=dict(existing.get('metadata') or {},local_harness=self.adapters[agent].local_harness)
        if self.store.get('sessions',identity): self.store.update('sessions',identity,fields)
        else: self.store.insert('sessions',dict(identity,**fields,title=session_id,created_at=now()))
        if task: self.store.update('tasks',{'id':task['id']},{agent+'_session':session_id,'updated_at':now()})

    def create_session(self,agent):
        self._require_task()
        adapter=self._adapter(agent)
        if not self.capabilities(agent).get('supports_sessions'): raise NotImplementedError(f'{agent}: sessions Unsupported')
        if getattr(adapter,'state','')=='Busy': raise RuntimeError('Wait for the active turn before creating a session')
        self._contexts[agent]={'task_id':self.current_task_id,'project_id':self.current_project_id,'session_id':''}
        self._apply_project(agent,self.current_project)
        result=adapter.create_session()
        sid=result.get('id',result.get('session_id','')) if isinstance(result,dict) else result
        if isinstance(sid,str) and sid: self._map_session(agent,sid)
        return result

    def resume_session(self,agent,session_id):
        self._require_task()
        adapter=self._adapter(agent)
        if not self.capabilities(agent).get('supports_sessions'): raise NotImplementedError(f'{agent}: sessions Unsupported')
        if getattr(adapter,'state','')=='Busy': raise RuntimeError('Wait for the active turn before resuming a session')
        saved=self.store.get('sessions',{'agent':agent,'id':session_id})
        if agent=='local' and saved and hasattr(adapter,'local_harness'):
            if (saved.get('metadata') or {}).get('local_harness',adapter.local_harness)!=adapter.local_harness:
                raise ValueError('此本地對話使用不同 Harness；請切回原 Harness 或建立新對話')
        if saved and agent!='dot':
            project=self.current_project
            expected=project.get(agent+'_cwd') or project['repo_path']
            if saved.get('cwd') and Path(saved['cwd']).resolve()!=Path(expected).resolve():
                raise ValueError('此對話屬於不同工作目錄：'+saved['cwd']+'。請先選擇該專案與任務，再按 Resume；本次沒有恢復 session。')
        self._contexts[agent]={'task_id':self.current_task_id,'project_id':self.current_project_id,'session_id':session_id}
        self._apply_project(agent,self.current_project)
        result=adapter.resume_session(session_id)
        self._map_session(agent,session_id)
        self._record('session_changed',agent,content='Resumed '+session_id)
        return result

    def rename_session(self,agent,session_id,title):
        if not self.store.get('sessions',{'agent':agent,'id':session_id}): raise ValueError('Unknown session')
        self.store.update('sessions',{'agent':agent,'id':session_id},{'title':title,'updated_at':now()})

    def _require_task(self):
        if not self.current_task: raise ValueError('Select or create a task first')

    def send_message(self,agent,content,model=None,effort=None,attachments=None):
        self._require_task()
        adapter=self._adapter(agent)
        if getattr(adapter,'state','Disconnected')!='Connected': raise RuntimeError(f'{agent}: connect backend and wait until ready before sending')
        if not str(content).strip() and not attachments: raise ValueError('Message is empty')
        caps=self.capabilities(agent)
        defaults=self.get_setting('agent.'+agent,{})
        model=model or (defaults.get('default_model') if caps.get('supports_model_selection') else None)
        effort=effort or (defaults.get('default_effort') if caps.get('supports_effort') else None)
        if model and not caps.get('supports_model_selection'): raise NotImplementedError('Model selection Unsupported')
        if effort and not caps.get('supports_effort'): raise NotImplementedError('Effort selection Unsupported')
        if attachments:
            if not caps.get('supports_files'): raise NotImplementedError('Attachments Unsupported')
            attachments=[str(self.safe_artifact_path(path)) for path in attachments]
        task=self.current_task
        mapped=task.get(agent+'_session','')
        active=getattr(adapter,'session_id','')
        if mapped and active!=mapped: raise RuntimeError('Resume the mapped session before sending to this task')
        if active and not mapped: raise RuntimeError('Create or explicitly resume a session for this task before sending')
        self._contexts[agent]={'task_id':task['id'],'project_id':task['project_id'],'session_id':mapped}
        self._apply_project(agent,self.current_project)
        message_id=uid('msg-')
        self._contexts[agent]['outbound_message_id']=message_id
        self.store.insert('messages',dict(id=message_id,task_id=task['id'],agent=agent,session_id=mapped,role='user',
                                         content=content,timestamp=now(),metadata={'attachments':attachments or []}))
        self._record('prompt_sent',agent,message_id=message_id,content=content,model=model,effort=effort)
        try: return adapter.send_message(content,model=model,effort=effort,attachments=attachments)
        except Exception as exc:
            self.store.update('messages',{'id':message_id},{'status':'failed'})
            self._record('error',agent,content=str(exc))
            raise

    def stop(self,agent):
        if not self.capabilities(agent).get('supports_cancel'): raise NotImplementedError(f'{agent}: Stop Unsupported')
        result=self._adapter(agent).stop()
        self._record('stop',agent,content='Cancellation requested through backend adapter')
        return result

    def stop_task(self,confirmed=False):
        if not confirmed: raise PermissionError('Confirm Stop Current Task first')
        results={}
        for agent,adapter in self.adapters.items():
            if getattr(adapter,'state','')=='Busy':
                try: results[agent]=self.stop(agent)
                except Exception as exc: results[agent]=sanitize(str(exc))
        return results

    def approve(self,agent,request_id,approved):
        if not self.capabilities(agent).get('supports_approval'): raise NotImplementedError('Tool approval Unsupported')
        self._record('approval_response',agent,request_id=request_id,approved=bool(approved))
        return self._adapter(agent).approve(request_id,bool(approved))

    def _record(self,kind,agent='workspace',**payload):
        event_type=kind
        context=self._context(agent) if agent in AGENTS else {'task_id':self.current_task_id,'session_id':''}
        clean=sanitize(payload)
        for reserved in ('id','type','agent','timestamp'):
            if reserved in clean: clean['backend_'+reserved]=clean.pop(reserved)
        event=dict(id=uid('event-'),type=event_type,agent=agent,task_id=clean.pop('task_id',context.get('task_id')),
                   session_id=clean.pop('session_id',context.get('session_id','')),timestamp=now(),**clean)
        audit=dict(event)
        if event_type in ('message_start','message_delta'):
            audit.pop('content',None); audit.pop('full_content',None); audit.pop('delta',None)
            audit['redaction']='Streaming fragment omitted; completed message is stored after whole-message secret filtering.'
        audit['redacted']=sanitize(payload)!=payload or 'redaction' in audit or any(marker in json.dumps(audit,ensure_ascii=False) for marker in ('[REDACTED]','[OMITTED:'))
        raw_ref=self.store.append_raw(agent,audit)
        event['raw_ref']=raw_ref
        summary=str(clean.get('content',clean.get('summary',clean.get('command',clean.get('state','')))))[:600]
        persisted_payload={k:v for k,v in audit.items() if k not in ('id','type','agent','task_id','session_id','timestamp')}
        self.store.insert('events',dict(id=event['id'],task_id=event['task_id'],agent=agent,session_id=event['session_id'],
            type=event_type,status=str(clean.get('status','')),timestamp=event['timestamp'],summary='' if event_type in ('message_start','message_delta') else summary,
            raw_ref=raw_ref,payload=persisted_payload))
        self._queue.put(event)
        return event

    def ingest_event(self,agent,kind,**payload):
        event_type=kind
        self._check_agent(agent)
        with self._lock:
            if is_hidden_reasoning({'type':event_type}): return self._record('redaction',agent,content='Hidden reasoning event excluded')
            if event_type=='session': self._map_session(agent,str(payload.get('session_id') or payload.get('id') or ''))
            if event_type=='send_ack' and agent=='dot':
                message_id=self._context(agent).get('outbound_message_id')
                if message_id:
                    self.store.update('messages',{'id':message_id},{'metadata':{'native_id':payload.get('native_id',''),'source':'manual send receipt'}})
            if event_type=='message_snapshot':
                context=self._context(agent)
                if not context.get('task_id'): raise ValueError('Select a task before reading Dot history')
                native_id=str(payload.get('native_id',''))
                existing=next((x for x in self.messages(task_id=context['task_id'],agent=agent)
                    if x.get('session_id')==context.get('session_id') and (x.get('metadata') or {}).get('native_id')==native_id),None)
                message_id=existing['id'] if existing else uid('msg-')
                payload['message_id']=message_id
                event=self._record(event_type,agent,**payload)
                values=dict(content=payload.get('content',''),role=payload.get('role','event'),status='complete',
                    raw_ref=event['raw_ref'],metadata={'native_id':native_id,'native_timestamp':payload.get('native_timestamp',''),'source':'manual snapshot; not streaming'})
                if existing: self.store.update('messages',{'id':message_id},values)
                else: self.store.insert('messages',dict(id=message_id,task_id=context['task_id'],agent=agent,
                    session_id=context.get('session_id',''),timestamp=now(),**values))
                return event
            if event_type in ('message_start','message_delta','message_end'):
                if event_type=='message_start' or agent not in self._streams:
                    context=self._context(agent)
                    message_id=uid('msg-')
                    self._streams[agent]={'id':message_id,'text':''}
                    self.store.insert('messages',dict(id=message_id,task_id=context.get('task_id'),agent=agent,
                        session_id=context.get('session_id',''),role='assistant',content='',timestamp=now(),status='streaming'))
                stream=self._streams[agent]
                content=str(payload.get('content',payload.get('delta','')) or '')
                if event_type=='message_delta': stream['text']+=content
                elif content: stream['text']=content
                clean_content=sanitize(stream['text'])
                payload['full_content']=clean_content
                payload['message_id']=stream['id']
                payload['content']=clean_content
                payload.pop('delta',None)
                status=('interrupted' if payload.get('status') in ('interrupted','cancelled') else 'complete') if event_type=='message_end' else 'streaming'
                event=self._record(event_type,agent,**payload)
                # Preserve complete lines while holding the unfinished line in memory:
                # a credential can cross arbitrary chunk boundaries, including its identifying prefix.
                persistent_content=clean_content if event_type=='message_end' else sanitize(stream['text'][:stream['text'].rfind('\n')+1])
                self.store.update('messages',{'id':stream['id']},{'content':persistent_content,'status':status,'raw_ref':event['raw_ref'],
                                                               'session_id':self._context(agent).get('session_id','')})
                if event_type=='message_end': self._streams.pop(agent,None)
                return event
            if event_type=='event' and payload.get('event_type')=='command_output':
                payload={'event_type':'command_output','summary':'Streaming command fragment omitted; completed command output retained.',
                         'redaction':'Command output fragments are not persisted independently.'}
            if event_type=='raw':
                original=payload.get('raw',payload)
                cleaned=sanitize(original)
                raw_type=str(original.get('type',original.get('method',''))) if isinstance(original,dict) else ''
                if any(word in raw_type.lower() for word in ('delta','partial','stream_event')):
                    payload={'raw':{'redaction':'Raw streaming fragment omitted; sanitized completed message retained.'},'redacted':True}
                else: payload={'raw':cleaned,'redacted':original!=cleaned}
            event=self._record(event_type,agent,**payload)
            if event_type in ('command','tool_start','tool_result','file','diff','test','error','system'):
                content=payload.get('content') or payload.get('command') or payload.get('summary') or json.dumps(sanitize(payload),ensure_ascii=False)
                role={'tool_start':'tool','tool_result':'tool','diff':'file','test':'event'}.get(event_type,event_type)
                context=self._context(agent)
                self.store.insert('messages',dict(id=uid('msg-'),task_id=context.get('task_id'),agent=agent,
                    session_id=context.get('session_id',''),role=role,content=content,timestamp=event['timestamp'],raw_ref=event['raw_ref'],metadata=payload))
            if event_type in ('diff','test'):
                self.add_artifact(event_type,payload.get('name',event_type),content=json.dumps(sanitize(payload),ensure_ascii=False),agent=agent,task_id=event['task_id'])
            return event

    def drain_events(self,limit=2000):
        events=[]
        for _ in range(limit):
            try: events.append(self._queue.get_nowait())
            except queue.Empty: break
        return events

    def messages(self,task_id=None,agent=None):
        task_id=task_id or self.current_task_id
        clauses,values=[],[]
        if task_id: clauses.append('task_id=?'); values.append(task_id)
        if agent: clauses.append('agent=?'); values.append(agent)
        return self.store.query('SELECT * FROM messages'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY timestamp,rowid',values)

    def events(self,task_id=None,agent=None,limit=1000):
        task_id=task_id or self.current_task_id
        clauses,values=[],[]
        if task_id: clauses.append('task_id=?'); values.append(task_id)
        if agent: clauses.append('agent=?'); values.append(agent)
        values.append(max(1,min(int(limit),100000)))
        return self.store.query('SELECT * FROM events'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY timestamp DESC,rowid DESC LIMIT ?',values)

    def get_history(self,agent,session_id=None):
        if session_id: return self.store.query('SELECT * FROM messages WHERE agent=? AND session_id=? ORDER BY timestamp,rowid',(agent,session_id))
        return self.messages(agent=agent)

    def search(self,text,project_id=None,agent=None,status=None,date_from=None,date_to=None,branch=None,error=False):
        tasks=self.list_tasks(project_id=project_id,agent=agent,status=status,date_from=date_from,date_to=date_to,branch=branch,error=error)
        allowed={task['id'] for task in tasks}
        term='%'+str(text)+'%'
        results=[]
        for table,columns in [('messages',['content']),('events',['summary','payload']),('tasks',['title','notes','id']),
                              ('projects',['name','repo_path','notes']),('artifacts',['name','content'])]:
            rows=self.store.query(f'SELECT * FROM {table} WHERE '+' OR '.join(f'{c} LIKE ?' for c in columns),[term]*len(columns))
            for row in rows:
                task_id=row.get('task_id',row.get('id') if table=='tasks' else None)
                if task_id and task_id not in allowed: continue
                if table=='projects' and project_id and row['id']!=project_id: continue
                if agent and table in ('messages','events','artifacts') and row.get('agent')!=agent: continue
                results.append({'kind':table,'record':row,'task_id':task_id,'content':row.get('content',row.get('summary',row.get('title',row.get('name',''))))})
        return results

    def prepare_handoff(self,source_message_id,target_agent,annotation=''):
        self._check_agent(target_agent)
        source=self.store.get('messages',{'id':source_message_id})
        if not source: raise ValueError('Source message does not exist')
        if source['role']!='assistant': raise ValueError('Select an assistant response for handoff')
        if source['status']!='complete': raise ValueError('Wait for a complete response before handoff')
        task=self.get_task(source['task_id'])
        project=self.get_project(task['project_id'])
        timestamp=now()
        metadata={'source_agent':source['agent'],'target_agent':target_agent,'task_id':task['id'],'project_id':project['id'],
                  'project':project['name'],'branch':task['branch'],'timestamp':timestamp,'source_session':source['session_id']}
        original=source['content']
        annotation=sanitize(annotation)
        envelope='Handoff metadata:\n'+json.dumps(metadata,ensure_ascii=False,indent=2)+'\n\nOriginal content:\n'+original
        if annotation: envelope+='\n\nAdditional note:\n'+annotation
        preview=dict(id=uid('handoff-'),task_id=task['id'],source_agent=source['agent'],target_agent=target_agent,
                     source_message_id=source['id'],source_session=source['session_id'],source_message=original,
                     handoff_message=envelope,content=envelope,annotation=annotation,timestamp=timestamp,
                     project_id=project['id'],branch=task['branch'],status='prepared',metadata=metadata)
        self.store.insert('handoffs',preview)
        return sanitize(preview)

    def send_handoff(self,preview):
        handoff_id=preview if isinstance(preview,str) else preview['id']
        record=self.store.get('handoffs',{'id':handoff_id})
        if not record: raise ValueError('Handoff preview does not exist')
        if record['status']!='prepared': raise ValueError('This handoff has already been attempted; prepare a new preview to retry')
        if record['task_id']!=self.current_task_id: raise ValueError('Select the handoff task before sending')
        self.store.update('handoffs',{'id':handoff_id},{'status':'sending'})
        try: result=self.send_message(record['target_agent'],record['handoff_message'])
        except Exception:
            self.store.update('handoffs',{'id':handoff_id},{'status':'failed'})
            raise
        self.store.update('handoffs',{'id':handoff_id},{'status':'sent'})
        self._record('handoff',record['target_agent'],handoff_id=handoff_id,source_agent=record['source_agent'],content=record['handoff_message'])
        return result

    def update_handoff_annotation(self,handoff_id,annotation):
        record=self.store.get('handoffs',{'id':handoff_id})
        if not record or record['status']!='prepared': raise ValueError('Only a prepared handoff can be annotated')
        annotation=sanitize(annotation)
        envelope='Handoff metadata:\n'+json.dumps(record['metadata'],ensure_ascii=False,indent=2)+'\n\nOriginal content:\n'+record['source_message']
        if annotation: envelope+='\n\nAdditional note:\n'+annotation
        self.store.update('handoffs',{'id':handoff_id},{'annotation':annotation,'handoff_message':envelope,'content':envelope})
        return self.store.get('handoffs',{'id':handoff_id})

    def handoffs(self,task_id=None):
        return self.store.query('SELECT * FROM handoffs WHERE task_id=? ORDER BY timestamp',(task_id or self.current_task_id,))

    def get_setting(self,key,default=None): return self.store.get_setting(key,default)

    def set_setting(self,key,value):
        if key in ('automatic','automatic_orchestration','automation.enabled') and value: raise ValueError('Automatic orchestration is outside v1 and remains OFF')
        self.store.set_setting(key,value)
        if key=='logs.max_size': self.store.max_raw_bytes=max(1024,int(value))
        if key=='logs.retention_days': self.store.retention_days=max(1,int(value))
        if key=='retention.days': self.store.retention_days=max(1,int(value))
        if key=='retention.max_mb': self.store.max_raw_bytes=max(1024,int(float(value)*1024*1024))
        if key=='retention.archive':
            self.store.archive_enabled=bool(value)
            self.store.archive_logs()

    def safe_artifact_path(self,path):
        roots=[self.store.artifact_dir]
        if self.current_project: roots.append(self.current_project['repo_path'])
        return safe_file(path,roots)

    def open_path(self,path):
        candidate=Path(path).expanduser().resolve()
        allowed=[self.store.artifact_dir,self.store.raw_dir]
        if self.current_project: allowed.append(Path(self.current_project['repo_path']).resolve())
        if is_secret_path(candidate) or not any(candidate.is_relative_to(root) for root in allowed):
            raise PermissionError('Path is outside project, artifacts, and logs')
        if not candidate.exists(): raise FileNotFoundError(candidate)
        return candidate

    def _export_target(self,path,allowed_suffixes=None):
        target=safe_export_path(path,allowed_suffixes=allowed_suffixes)
        if target==self.store.db_path or any(target.is_relative_to(root) for root in (self.store.raw_dir,self.store.artifact_dir)):
            raise PermissionError('Export cannot overwrite managed database, raw logs, or artifact storage')
        return target

    def save_patch(self,diff_text,target_path):
        target=self._export_target(target_path,{'.patch','.diff'})
        target.write_text(sanitize(str(diff_text)),encoding='utf-8')
        return target

    @staticmethod
    def _artifact_text(kind,content):
        if kind=='jsonl':
            lines=[]
            for number,line in enumerate(str(content).splitlines(),1):
                if not line.strip(): continue
                try: value=json.loads(line)
                except json.JSONDecodeError as exc: raise ValueError(f'Invalid JSONL at line {number}') from exc
                lines.append(json.dumps(sanitize(value),ensure_ascii=False))
            return '\n'.join(lines)+('\n' if lines else '')
        return sanitize(str(content))

    def import_artifact(self,path,kind=None,name=None,agent='',task_id=None,*,user_selected=False):
        suffix=Path(path).suffix.lower()
        inferred={'.diff':'diff','.patch':'patch','.log':'test log','.md':'markdown','.markdown':'markdown','.jsonl':'jsonl',
                  '.txt':'report','.png':'screenshot','.jpg':'screenshot','.jpeg':'screenshot'}
        kind=kind or inferred.get(suffix)
        if kind is None: raise ValueError('Choose a supported artifact type')
        return self.add_artifact(kind,name or Path(path).name,path=path,agent=agent,task_id=task_id,user_selected=user_selected)

    def add_artifact(self,kind,name,path=None,content='',agent='',task_id=None,*,user_selected=False):
        if kind not in ARTIFACT_TYPES: raise ValueError('Unsupported artifact type')
        if agent: self._check_agent(agent)
        task_id=task_id or self.current_task_id
        if task_id and not self.get_task(task_id): raise ValueError('Unknown artifact task')
        artifact_id=uid('artifact-')
        metadata={}
        binary=None
        if path:
            source=self.safe_artifact_path(path)
            if kind=='screenshot':
                if not user_selected: raise PermissionError('Screenshot import requires explicit user selection')
                binary=source.read_bytes()
                metadata=verify_screenshot(binary,source.suffix)
                metadata['user_selected']=True
                suffix='.png' if metadata['mime_type']=='image/png' else '.jpg'
                content=''
            else:
                try: content=source.read_text(encoding='utf-8-sig')
                except UnicodeDecodeError as exc: raise ValueError('Text artifacts must be UTF-8') from exc
        elif kind=='screenshot': raise ValueError('Screenshot must be an explicitly selected project image file')
        if binary is None:
            content=self._artifact_text(kind,content)
            suffix=ARTIFACT_SUFFIXES[kind]
            metadata={'text_redacted':True,'encoding':'utf-8'}
        copied_path=self.store.artifact_dir/(artifact_id+suffix)
        reject_link_ancestors(copied_path)
        if not copied_path.resolve().is_relative_to(self.data_dir): raise PermissionError('Managed artifact path escaped the workspace')
        if binary is not None: copied_path.write_bytes(binary)
        else: copied_path.write_text(content,encoding='utf-8')
        artifact=dict(id=artifact_id,task_id=task_id,agent=agent,type=kind,name=name,path=str(copied_path),
                      content=content,timestamp=now(),metadata=metadata)
        self.store.insert('artifacts',artifact)
        return self.store.get('artifacts',{'id':artifact_id})

    def artifact_path(self,artifact_id):
        artifact=self.store.get('artifacts',{'id':artifact_id})
        if not artifact: raise ValueError('Unknown artifact')
        path=artifact.get('path')
        if not path and artifact['type']!='screenshot':
            # Lazy materialization upgrades older text-only records without reading source files.
            path=self.store.artifact_dir/(artifact_id+ARTIFACT_SUFFIXES[artifact['type']])
            reject_link_ancestors(path)
            Path(path).write_text(self._artifact_text(artifact['type'],artifact['content']),encoding='utf-8')
            self.store.update('artifacts',{'id':artifact_id},{'path':str(path)})
        reject_link_ancestors(path)
        if not Path(path).resolve().is_relative_to(self.data_dir): raise PermissionError('Managed artifact path escaped the workspace')
        path=safe_file(path,[self.store.artifact_dir])
        if artifact['type']=='screenshot': verify_screenshot(path.read_bytes(),path.suffix)
        return path

    def export_artifact(self,artifact_id,target_path,*,screenshot_reviewed=False):
        artifact=self.store.get('artifacts',{'id':artifact_id})
        if not artifact: raise ValueError('Unknown artifact')
        if artifact['type']=='screenshot':
            if not screenshot_reviewed: raise PermissionError('Review the image for sensitive visible content before exporting screenshot bytes')
            source=self.artifact_path(artifact_id)
            image=source.read_bytes()
            info=verify_screenshot(image,source.suffix)
            target=self._export_target(target_path,{'.png'} if info['mime_type']=='image/png' else {'.jpg','.jpeg'})
            target.write_bytes(image)
        else:
            expected=ARTIFACT_SUFFIXES[artifact['type']]
            target=self._export_target(target_path,{expected,'.txt'} if artifact['type']!='jsonl' else {'.jsonl'})
            target.write_text(self._artifact_text(artifact['type'],artifact['content']),encoding='utf-8')
        return target

    def artifacts(self,task_id=None):
        return self.store.query('SELECT * FROM artifacts WHERE task_id=? ORDER BY timestamp',(task_id or self.current_task_id,))

    def git_snapshot(self,project_id=None):
        from .inspection import git_snapshot,git_diff,git_read
        project=self.get_project(project_id or self.current_project_id)
        result={'branch':'','dirty':False,'ahead':None,'behind':None,'status':'','diff':'','log':'','is_git':False,'error':''}
        if not project: return result
        try:
            result.update(git_snapshot(project['repo_path']))
            result['is_git']=not bool(result['error'])
            diff_result=git_diff(project['repo_path'])
            log_result=git_read(project['repo_path'],'log','-8','--format=%h %s')
            result.update(diff=diff_result.get('stdout',''),diff_result=diff_result,diff_error=diff_result.get('stderr',''),
                          diff_exit_code=diff_result.get('exit_code'),log=log_result.get('stdout',''),log_result=log_result)
        except Exception as exc: result['error']=str(exc)
        return sanitize(result)

    def diff_snapshot(self,project_id=None):
        from .inspection import git_diff
        project=self.get_project(project_id or self.current_project_id)
        if not project:
            return {'stdout':'','diff':'','stderr':'Select a project first','exit_code':None,'changed_files':[]}
        try: result=git_diff(project['repo_path'])
        except Exception as exc:
            result={'command':'git diff','cwd':project['repo_path'],'stdout':'','stderr':str(exc),'exit_code':None,'changed_files':[]}
        result['diff']=result.get('stdout','')
        return sanitize(result)

    def git_status(self,project_id=None): return self.git_snapshot(project_id)['status']
    def git_diff(self,project_id=None): return self.git_snapshot(project_id)['diff']
    def git_log(self,project_id=None): return self.git_snapshot(project_id)['log']

    def poll_legacy(self,root=None):
        from .inspection import LegacyReader
        root=root or self.get_setting('legacy.root','')
        if not root: return []
        key=str(Path(root).resolve())
        if key not in self._legacy_readers: self._legacy_readers[key]={'reader':LegacyReader(key),'tails':{},'contents':{}}
        state=self._legacy_readers[key]
        results=[]
        for entry in state['reader'].poll():
            agent=entry['agent']
            text=state['tails'].get(agent,'')+entry['content']
            # A trailing partial line stays in memory to prevent split credential leaks.
            split=text.rfind('\n')
            if split<0:
                state['tails'][agent]=text[-1024*1024:]
                continue
            complete,text=text[:split+1],text[split+1:]
            state['tails'][agent]=text
            clean=sanitize(complete)
            state['contents'][agent]=(state['contents'].get(agent,'')+clean)[-1024*1024:]
            event=self._record('legacy',agent if agent in AGENTS else 'workspace',task_id=None,content=clean,source=entry['source'])
            results.append(dict(entry,content=state['contents'][agent],raw_ref=event['raw_ref']))
        return results

    def logs_path(self,agent=None):
        if agent: self._check_agent(agent)
        return self.store.raw_dir

    def project_file(self,relative_path):
        if not self.current_project: raise ValueError('Select a project first')
        return self.safe_artifact_path(Path(self.current_project['repo_path'])/relative_path)

    def read_raw(self,reference): return self.store.read_raw(reference)

    def export_task(self,task_id,format,target_path,*,include_screenshots=False):
        task=self.get_task(task_id)
        if not task: raise ValueError('Unknown task')
        format=format.lower().lstrip('.')
        suffixes={'markdown':{'.md','.markdown'},'md':{'.md','.markdown'},'json':{'.json'},'html':{'.html','.htm'},'zip':{'.zip'}}
        if format not in suffixes: raise ValueError('Export format must be Markdown, JSON, HTML, or ZIP')
        target=self._export_target(target_path,suffixes[format])
        artifacts=self.artifacts(task_id)
        images=[]
        if format=='zip' and include_screenshots:
            for artifact in artifacts:
                if artifact['type']!='screenshot': continue
                if not artifact['metadata'].get('user_selected'):
                    raise PermissionError('Screenshot was not explicitly selected for artifact import')
                path=self.artifact_path(artifact['id'])
                data=path.read_bytes()
                verify_screenshot(data,path.suffix)
                images.append(('artifacts/'+artifact['id']+path.suffix,data))
        bundle=sanitize({'export_version':1,'task':task,'project':self.get_project(task['project_id']),
                  'sessions':self.store.query('SELECT * FROM sessions WHERE task_id=?',(task_id,)),
                  'messages':self.messages(task_id),'events':self.events(task_id,limit=100000),'handoffs':self.handoffs(task_id),
                  'artifacts':artifacts,'screenshots_included':bool(images),
                  'security':'Recognizable text credentials and hidden reasoning are excluded. Raw may be redacted. Screenshot bytes require explicit export review; included pixels are not automatically redacted.'})
        markdown=self._markdown(bundle)
        if format in ('markdown','md'): target.write_text(markdown,encoding='utf-8')
        elif format=='json': target.write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
        elif format=='html':
            target.write_text('<!doctype html><meta charset="utf-8"><title>Task export</title><style>body{font:15px system-ui;max-width:1100px;margin:2rem auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><pre>'+html.escape(markdown)+'</pre>',encoding='utf-8')
        elif format=='zip':
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('task.json',json.dumps(bundle,ensure_ascii=False,indent=2))
                archive.writestr('task.md',markdown)
                archive.writestr('task.html','<!doctype html><meta charset="utf-8"><pre>'+html.escape(markdown)+'</pre>')
                for artifact in bundle['artifacts']:
                    if artifact['type']!='screenshot':
                        archive.writestr('artifacts/'+artifact['id']+ARTIFACT_SUFFIXES[artifact['type']],artifact['content'])
                for name,data in images: archive.writestr(name,data)
                if images:
                    archive.writestr('SCREENSHOT-SECURITY.txt','These images were explicitly imported by the user. Image pixels are not automatically redacted. Verify their visible contents before sharing this archive.')
                elif any(artifact['type']=='screenshot' for artifact in artifacts):
                    archive.writestr('SCREENSHOT-SECURITY.txt','Screenshot metadata is listed, but image bytes were excluded because this export did not explicitly confirm screenshot review.')
        else: raise ValueError('Export format must be Markdown, JSON, HTML, or ZIP')
        return target

    @staticmethod
    def _markdown(bundle):
        task=bundle['task']
        parts=[f"# {task['title']}",json.dumps(task,ensure_ascii=False,indent=2),'## Conversations']
        for msg in bundle['messages']: parts.extend([f"### {msg['agent']} · {msg['role']} · {msg['timestamp']}",msg['content']])
        for title,key in [('Events','events'),('Handoffs','handoffs'),('Artifacts / Diff / Tests','artifacts')]:
            parts.extend(['## '+title,json.dumps(bundle[key],ensure_ascii=False,indent=2)])
        return '\n\n'.join(parts)+'\n'

    def export_diagnostics(self,target_path):
        target=self._export_target(target_path,{'.zip'})
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('diagnostics.json',json.dumps(sanitize(self.diagnostics()),ensure_ascii=False,indent=2))
            archive.writestr('events.json',json.dumps(self.events(limit=500),ensure_ascii=False,indent=2))
            archive.writestr('README.txt','Diagnostic allowlist: runtime metadata and sanitized events only. No backend auth/config files collected.')
        return target

    def close(self):
        self._closed=True
        self.store.close()

