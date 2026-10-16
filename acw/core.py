"""UI-independent workspace orchestration. No adapter is connected on startup."""
from __future__ import annotations
import html
import hashlib
import json
import logging
import time
import queue
import shutil
import threading
import zipfile
from contextlib import contextmanager, ExitStack
from functools import wraps
from pathlib import Path
from .security import sanitize, safe_file, is_secret_path, is_hidden_reasoning, safe_export_path, verify_screenshot, reject_link_ancestors
from .store import Store, now, uid
from .agents import load_instances, make_adapter
from .requests import RequestDispatcher

AGENTS = ('claude','dot','codex','local')
TASK_STATUSES = ('NEW','PLANNING','REVIEWING','READY','IMPLEMENTING','VERIFYING','WAITING_USER','BLOCKED','DONE','FAILED','CANCELLED')
ARTIFACT_TYPES = {'diff','patch','test','test log','report','screenshot','jsonl','markdown'}
ARTIFACT_SUFFIXES={'diff':'.diff','patch':'.patch','test':'.log','test log':'.log','report':'.txt','jsonl':'.jsonl','markdown':'.md'}

def _synchronized(method):
    @wraps(method)
    def guarded(self,*args,**kwargs):
        with self._lock: return method(self,*args,**kwargs)
    return guarded


def _agent_action(method):
    @wraps(method)
    def guarded(self,agent,*args,**kwargs):
        with self._agent_operation(agent): return method(self,agent,*args,**kwargs)
    return guarded


class WorkspaceCore:
    def __init__(self,data_dir,adapters=None,*,clock=time.monotonic):
        self.store=Store(data_dir)
        self.data_dir=self.store.data_dir
        self.adapters={}
        self._lock=threading.RLock()
        self._queue=queue.Queue()
        self._contexts={}
        self._operations={}
        self._active_requests={}
        self._session_reservations={}
        self._adapter_epochs={}
        self._operation_context=threading.local()
        self._dot_root_lock=threading.Lock()
        self._streams={}
        self._closed=False
        self._checkpoint_clock=clock
        self._last_checkpoint=clock()
        self._legacy_readers={}
        self._event_taps=[]
        self._native_discovery={}
        self.current_project_id=self.store.get_setting('current_project_id')
        self.current_task_id=self.store.get_setting('current_task_id')
        self._instances=load_instances(self.store.get_setting('agents.instances'))
        self._agent_selections={agent:self.store.get_setting('selection.'+agent) for agent in self.agent_ids
                                if self.store.get_setting('selection.'+agent) is not None}
        self._recover()
        self.requests=RequestDispatcher(self,Path(self.data_dir)/'requests')
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

    @property
    def agent_ids(self):
        return tuple(self._instances)

    def provider(self,agent):
        self._check_agent(agent)
        return self._instances[agent]['provider']

    def agent_name(self,agent):
        return self._instances.get(agent,{}).get('name',agent)

    @contextmanager
    def _native_session_operation(self,agent,session_id):
        """Prevent two instances from concurrently controlling one native session."""
        if not session_id:
            yield
            return
        def backend_family(instance):
            provider=self.provider(instance)
            return getattr(self.adapters.get(instance),'local_harness',provider) if provider=='local' else provider
        provider=backend_family(agent)
        key=(provider,session_id)
        with self._lock:
            owner=self._session_reservations.get(key)
            if owner is not None and owner!=agent:
                raise RuntimeError('This native session is in use by another Agent')
            for other,adapter in self.adapters.items():
                if other!=agent and backend_family(other)==provider and getattr(adapter,'session_id','')==session_id and adapter.state in ('Connected','Busy','Connecting','Stopping'):
                    raise RuntimeError('This native session is already connected in '+self.agent_name(other))
            self._session_reservations[key]=agent
        try:
            yield
        finally:
            with self._lock:
                if self._session_reservations.get(key)==agent: self._session_reservations.pop(key,None)

    @_synchronized
    def create_agent_instance(self,provider,name,*,project_id=None):
        """Register a disconnected instance with a snapshot of provider settings."""
        if self._closed: raise RuntimeError('Workspace is closed')
        if provider not in ('claude','codex','local'): raise ValueError('Unsupported agent provider')
        name=sanitize(str(name)).strip()
        if not name or len(name)>80 or any(ord(c)<32 for c in name): raise ValueError('Invalid agent name')
        if project_id and not self.get_project(project_id): raise ValueError('Unknown project')
        agent=uid('agent-')
        settings=dict(self.get_setting('agent.'+provider,{}) or {})
        prototype=self.adapters.get(provider)
        runtime=dict(settings)
        if prototype:
            runtime['executable']=settings.get('executable') or getattr(prototype,'executable','')
            for key in ('claude_executable','codex_executable','hermes_executable','attachment_roots'):
                if key in prototype.settings: runtime.setdefault(key,prototype.settings[key])
        settings.setdefault('attachment_roots',[str(self.store.artifact_dir)])
        runtime.setdefault('attachment_roots',settings['attachment_roots'])
        # Approval preferences and existing native bindings are intentionally not copied.
        self._instances[agent]={'id':agent,'provider':provider,'name':name}
        try:
            adapter=make_adapter(provider,self.make_emitter(agent),runtime)
        except Exception:
            self._instances.pop(agent)
            raise
        selection={'project_id':project_id,'task_id':None}
        self._agent_selections[agent]=selection
        self.set_adapter(agent,adapter)
        self.set_setting('agent.'+agent,settings)
        self.set_setting('selection.'+agent,selection)
        self.set_setting('agents.instances',[row for key,row in self._instances.items() if key not in AGENTS])
        self._record('agent_created',agent,content=name)
        return dict(self._instances[agent])

    def agent_project(self,agent):
        self._check_agent(agent)
        selection=self._agent_selections.get(agent)
        return self.get_project(selection['project_id']) if selection else self.current_project

    def agent_task(self,agent):
        self._check_agent(agent)
        selection=self._agent_selections.get(agent)
        if selection is None: return self.current_task
        return self.get_task(selection['task_id']) if selection.get('task_id') else None

    @_synchronized
    def enable_agent_independence(self):
        """Freeze legacy selections once, without reconnecting or modifying native sessions."""
        for agent in self.agent_ids:
            if agent in self._agent_selections: continue
            selection={'project_id':self.current_project_id,'task_id':self.current_task_id}
            self._agent_selections[agent]=selection
            self.set_setting('selection.'+agent,selection)

    @_synchronized
    def legacy_local_conversation(self,agent):
        """Identify an explicitly saved pre-Hermes binding without changing history."""
        if self.provider(agent)!='local' or getattr(self.adapters.get(agent),'local_harness','')!='hermes':
            return None
        task=self.agent_task(agent)
        session_id=(task or {}).get(agent+'_session')
        if not session_id: return None
        saved=self.store.get('sessions',{'agent':agent,'id':session_id})
        if not saved or saved.get('task_id')!=task['id'] or saved.get('project_id')!=task['project_id']:
            return None
        metadata=saved.get('metadata') or {}
        harness=metadata.get('local_harness') if isinstance(metadata,dict) else None
        if harness not in ('claude','codex'): return None
        return {'task_id':task['id'],'session_id':session_id,'harness':harness}

    def prepare_conversation(self,agent,*,fresh=False):
        """Explicit user action: obtain a conversation without requiring task-management UI."""
        self._assert_agent_idle(agent)
        if not self.agent_project(agent): raise ValueError('請先選擇此 Agent 的 Project')
        adapter=self._adapter(agent)
        if adapter.state!='Connected': raise RuntimeError('請先連線此 Agent')
        task=self.agent_task(agent)
        if fresh and (not self.capabilities(agent).get('supports_sessions') or self.capabilities(agent).get('supports_create_session') is False):
            raise NotImplementedError('This Agent cannot create a new session')
        if fresh or not task:
            task=self.create_agent_task(agent,'新對話 '+now()[:16].replace('T',' '))
        session_id=task.get(agent+'_session') or ''
        if session_id:
            if getattr(adapter,'session_id','')!=session_id: self.resume_session(agent,session_id)
        elif self.capabilities(agent).get('supports_sessions') and self.capabilities(agent).get('supports_create_session') is not False:
            self.create_session(agent)
        return self.agent_task(agent)

    def open_saved_conversation(self,agent,session_id):
        """Resume the selected saved conversation in its original local history container."""
        self._assert_agent_idle(agent)
        saved=self.store.get('sessions',{'agent':agent,'id':session_id})
        if not saved: raise ValueError('Unknown session')
        project=self.agent_project(agent)
        if not project: raise ValueError('請先選擇此 Agent 的 Project')
        expected=project.get(self.provider(agent)+'_cwd') or project['repo_path']
        if saved.get('project_id') and saved['project_id']!=project['id']:
            raise ValueError('此對話屬於其他 Project，請先切換此 Agent 的 Project')
        if saved.get('cwd') and Path(saved['cwd']).resolve()!=Path(expected).resolve():
            raise ValueError('此對話的工作目錄與目前 Project 不符')
        task=self.get_task(saved.get('task_id')) if saved.get('task_id') else None
        if task and task['project_id']!=project['id']: raise ValueError('Saved conversation project mismatch')
        if task: self.select_agent_task(agent,task['id'])
        else: self.create_agent_task(agent,saved.get('title') or '已保存的對話')
        return self.resume_session(agent,session_id)

    def _assert_agent_idle(self,agent):
        if agent in self._operations or getattr(self._adapter(agent),'state','') in ('Busy','Connecting') or agent in self._streams:
            raise RuntimeError('Wait for or stop this agent before changing its project or task: '+agent)

    @contextmanager
    def _idle_agent_operations(self,agents):
        # Reserve under the Core lock, but never hold it across adapter I/O or
        # reader joins. Callbacks retain their old context until reassociation.
        stack=ExitStack()
        try:
            with self._lock:
                if self._closed: raise RuntimeError('Workspace is closed')
                for agent in agents: self._assert_agent_idle(agent)
                for agent in agents: stack.enter_context(self._agent_operation(agent))
            yield
        finally: stack.close()

    def _select_agent_context(self,agent,project,task=None):
        with self._idle_agent_operations([agent]):
            self._apply_agent_context(agent,project,task)

    def _apply_agent_context(self,agent,project,task=None):
        adapter=self._adapter(agent)
        metadata=self._project_metadata(project,agent)
        metadata.update(task_id=task['id'] if task else None,task_title=task['title'] if task else None)
        path='' if agent=='dot' else project.get(self.provider(agent)+'_cwd') or project['repo_path']
        adapter.set_project(path,metadata)
        with self._lock:
            if self.adapters.get(agent) is not adapter: raise RuntimeError('Adapter changed during project selection')
            selection={'project_id':project['id'],'task_id':task['id'] if task else None}
            self._agent_selections[agent]=selection
            self.set_setting('selection.'+agent,selection)
            self._contexts.pop(agent,None)
            self._native_discovery.pop(agent,None)
            self._record('agent_context_changed',agent,project_id=project['id'],content=task['title'] if task else project['name'])

    def select_agent_project(self,agent,project_id):
        project=self.get_project(project_id)
        if not project: raise ValueError('Unknown project')
        self._select_agent_context(agent,project)
        return project

    def select_agent_task(self,agent,task_id):
        task=self.get_task(task_id)
        if not task: raise ValueError('Unknown task')
        self._select_agent_context(agent,self.get_project(task['project_id']),task)
        return task

    def create_agent_task(self,agent,title):
        with self._idle_agent_operations([agent]):
            project=self.agent_project(agent)
            if not project: raise ValueError('Select a project for this agent first')
            task=self.create_task(title,project['id'],select=False)
            self._apply_agent_context(agent,project,task)
            return task

    def _reset_shared_contexts(self):
        self._contexts={agent:context for agent,context in self._contexts.items() if agent in self._agent_selections}

    def _recover(self):
        for message in self.store.query("SELECT id,task_id,agent,session_id FROM messages WHERE status='streaming'"):
            self.store.update('messages',{'id':message['id']},{'status':'interrupted'})
            self._record('recovery',message['agent'],task_id=message['task_id'],session_id=message['session_id'],
                         content='Previous stream interrupted; history restored. Prompt was not resent.')
        for message in self.store.query("SELECT id FROM messages WHERE role='user' AND status IN ('pending','sending')"):
            self.store.update('messages',{'id':message['id']},{'status':'delivery_unknown'})
        for handoff in self.store.query("SELECT id FROM handoffs WHERE status='sending'"):
            self.store.update('handoffs',{'id':handoff['id']},{'status':'delivery_unknown'})

    @_synchronized
    def set_adapter(self,agent,adapter):
        self._check_agent(agent)
        stream=self._streams.pop(agent,None)
        if stream:
            # Keep only previously redacted complete lines; discard the old
            # raw tail instead of applying a new adapter's credential policy.
            self.store.update('messages',{'id':stream['id']},{'status':'interrupted'})
            self._record('recovery',agent,content='Adapter replaced; previous stream interrupted without replay')
        self._active_requests.pop(agent,None)
        self._adapter_epochs[agent]=self._adapter_epochs.get(agent,0)+1
        adapter.emit=self.make_emitter(agent)
        self.adapters[agent]=adapter
        return adapter

    def make_emitter(self,agent):
        self._check_agent(agent)
        epoch=self._adapter_epochs.get(agent,0)
        def emit(kind,**payload):
            with self._lock:
                if not self._closed and self._adapter_epochs.get(agent,0)==epoch:
                    return self.ingest_event(agent,kind,**payload)
        return emit

    def _check_agent(self,agent):
        if agent not in self._instances: raise ValueError('Unknown agent')

    def _adapter(self,agent):
        self._check_agent(agent)
        if agent not in self.adapters: raise RuntimeError(f'{agent}: backend is unavailable')
        return self.adapters[agent]

    def connect(self,agent):
        # Default-project selection uses the normal idle guard before reserving
        # this connection. Its own lock prevents close/selection mid-setup.
        with self._lock:
            if self._closed: raise RuntimeError('Workspace is closed')
            settings=self.get_setting('agent.'+agent,{})
            if not settings.get('enabled',True): raise RuntimeError(f'{agent}: disabled in Settings')
            default_project=settings.get('default_project') if not (agent=='dot' and self._context(agent).get('scope')=='dot_conversation') and not self.agent_project(agent) else None
        if default_project: self.select_agent_project(agent,default_project)
        return self._connect_reserved(agent)

    @_agent_action
    def _connect_reserved(self,agent):
        adapter=self._adapter(agent)
        settings=self.get_setting('agent.'+agent,{})
        if not settings.get('enabled',True): raise RuntimeError(f'{agent}: disabled in Settings')
        if self.provider(agent)=='local' and hasattr(adapter,'local_harness'):
            if adapter.state in ('Connected','Busy','Connecting'):
                raise RuntimeError('請先中斷 Hermes 連線，再套用設定')
            from .adapters.hermes import HermesAdapter
            defaults={key:adapter.settings[key] for key in ('hermes_executable','attachment_roots') if key in adapter.settings}
            replacement=HermesAdapter(self.make_emitter(agent),**dict(defaults,**settings))
            # Connect checks the provider independently of saved conversations.
            # Exact session restoration happens on explicit Open or Send.
            if getattr(adapter,'_process',None):
                adapter.disconnect()
            adapter=self.set_adapter(agent,replacement)
        if self.provider(agent)!='local' and (settings.get('executable') or (self.provider(agent)=='codex' and 'executable' in settings)):
            adapter.executable=settings['executable'] or ''
        if settings.get('timeout'): adapter.settings['timeout']=float(settings['timeout'])
        if agent=='dot' and settings.get('dot_id')==getattr(adapter,'target',None) and settings.get('expected_room_id'):
            adapter.settings['expected_room_id']=settings['expected_room_id']
        if self.agent_project(agent): self._apply_project(agent,self.agent_project(agent))
        return adapter.connect()

    @_agent_action
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
                'agents':{a:self.diagnostics(a) for a in self.agent_ids},'automatic_orchestration':'OFF',
                  'native_message_lookup':'indexed' if self.store.native_lookup_index else 'scoped_scan_fallback',
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
        busy=[a for a,v in self.adapters.items() if getattr(v,'state','') in ('Busy','Connecting') or a in self._operations or a in self._streams]
        if busy: raise RuntimeError('Stop or wait for active agents before changing task/project: '+', '.join(busy))

    def select_project(self,project_id,sync=True,*,drafts=None,confirmed=False):
        with self._idle_agent_operations([a for a in self.adapters if a not in self._agent_selections]):
            return self._select_reserved_project(project_id,sync,drafts=drafts,confirmed=confirmed)

    def _select_reserved_project(self,project_id,sync=True,*,drafts=None,confirmed=False):
        project=self.get_project(project_id)
        if not project: raise ValueError('Unknown project')
        changed=project_id!=self.current_project_id
        if changed and drafts and any(str(v).strip() for v in drafts.values()) and not confirmed:
            raise PermissionError('Confirm discarding unsent drafts before changing project')
        if sync:
            # Drain old adapter processes before changing shared context, so
            # shutdown diagnostics cannot be attributed to the new project.
            for agent,adapter in list(self.adapters.items()):
                if agent in self._agent_selections: continue
                selected=project
                if not selected: continue
                metadata=self._project_metadata(selected,agent)
                if agent not in self._agent_selections and changed:
                    metadata.update(task_id=None,task_title=None)
                path='' if agent=='dot' else selected.get(self.provider(agent)+'_cwd') or selected['repo_path']
                adapter.set_project(path,metadata)
                if self.adapters.get(agent) is not adapter: raise RuntimeError('Adapter changed during project synchronization')
        if changed:
            self.current_project_id=project_id
            self.set_setting('current_project_id',project_id)
            task=self.current_task
            if task and task['project_id']!=project_id:
                self.current_task_id=None
                self.set_setting('current_task_id',None)
            self._reset_shared_contexts()
            self._record('project_changed',project_id=project_id,content=project['name'])
        if sync: self._record('project_synced',content=project['name'],metadata=self._project_metadata(project))
        return project

    def _project_metadata(self,project,agent=None):
        task=self.agent_task(agent) if agent else self.current_task
        branch=self.git_snapshot(project['id']).get('branch') or project['active_branch']
        return {'project_id':project['id'],'project_name':project['name'],'repo_name':Path(project['repo_path']).name,
                'branch':branch,'task_id':task['id'] if task else None,'task_title':task['title'] if task else None}

    def _apply_project(self,agent,project):
        path='' if agent=='dot' else project.get(self.provider(agent)+'_cwd') or project['repo_path']
        self._adapter(agent).set_project(path,self._project_metadata(project,agent))

    def sync_project(self):
        with self._idle_agent_operations(list(self.adapters)):
            return self._sync_reserved_project()

    def _sync_reserved_project(self):
        project=self.current_project
        if not project: raise ValueError('Select a project first')
        for agent in self.adapters:
            selected=self.agent_project(agent)
            if selected: self._apply_project(agent,selected)
        self._record('project_synced',content=project['name'],metadata=self._project_metadata(project))

    @_synchronized
    def create_task(self,title,project_id=None,*,select=True,**metadata):
        if select:
            for agent in self.adapters:
                if agent not in self._agent_selections: self._assert_agent_idle(agent)
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
        if select: self.select_task(task['id'])
        return self.get_task(task['id'])

    def get_task(self,task_id):
        task=self.store.get('tasks',{'id':task_id})
        if task:
            for agent,session in (task.get('metadata') or {}).get('agent_sessions',{}).items():
                if agent in self._instances and agent not in AGENTS: task[agent+'_session']=session
        return task

    @_synchronized
    def _set_task_session(self,task_id,agent,session_id):
        self._check_agent(agent)
        if agent in AGENTS:
            fields={agent+'_session':session_id}
        else:
            task=self.get_task(task_id)
            metadata=dict(task.get('metadata') or {})
            sessions=dict(metadata.get('agent_sessions') or {})
            sessions[agent]=session_id
            metadata['agent_sessions']=sessions
            fields={'metadata':metadata}
        self.store.update('tasks',{'id':task_id},dict(fields,updated_at=now()))

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

    @_synchronized
    def select_task(self,task_id):
        task=self.get_task(task_id)
        if not task: raise ValueError('Unknown task')
        if task_id!=self.current_task_id:
            for agent in self.adapters:
                if agent not in self._agent_selections: self._assert_agent_idle(agent)
            self.current_project_id=task['project_id']
            self.current_task_id=task_id
            self.set_setting('current_project_id',task['project_id'])
            self.set_setting('current_task_id',task_id)
            self._reset_shared_contexts()
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
        project=self.agent_project(agent)
        if not project: raise ValueError('Select a project before native session discovery')
        directory=str(Path(project['repo_path']).resolve())
        if not getattr(adapter,'cwd','') or Path(adapter.cwd).resolve()!=Path(directory):
            raise PermissionError('Sync the selected project before native session discovery')
        if self.provider(agent)=='claude':
            records=sanitize(adapter.list_sessions(native=True,limit=limit,offset=offset))
        else:
            records=sanitize(adapter.list_sessions())
        if (self.agent_project(agent) or {}).get('id')!=project['id'] or Path(adapter.cwd).resolve()!=Path(directory):
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
        project=self.agent_project(agent)
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
        if (self.agent_project(agent) or {}).get('id')!=project['id'] or Path(adapter.cwd).resolve()!=directory:
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
        project=self.agent_project(agent)
        project_id=project['id'] if project and cwd and Path(cwd).resolve()==Path(project['repo_path']).resolve() else None
        title=str(record.get('title') or record.get('name') or record.get('summary') or record.get('firstPrompt') or record.get('preview') or '')
        self.store.insert('sessions',dict(identity,task_id=None,project_id=project_id,title=title,cwd=cwd,
            created_at=now(),updated_at=now(),metadata=metadata))
        self._record('session_imported',agent,task_id=None,session_id=session_id,content='Native session metadata imported; explicit Resume is still required.')
        return self.store.get('sessions',identity)

    def desktop_sessions(self,agent='claude'):
        """Explicit navigator read of locally saved Claude desktop or Codex conversations (metadata only)."""
        from .desktop_sessions import list_desktop_sessions, list_codex_sessions
        if self.provider(agent) not in ('claude','codex'): raise ValueError('Local conversations are available for Claude and Codex only')
        rows=sanitize(list_desktop_sessions() if self.provider(agent)=='claude' else list_codex_sessions())
        overrides=self.get_setting('desktop.overrides',{}) or {}
        for row in rows:
            override=overrides.get(agent+':'+row['id']) or {}
            if override.get('title'): row.update(title=override['title'],renamed=True)
            if 'archived' in override: row['archived']=bool(override['archived'])
        return rows

    def set_desktop_override(self,agent,session_id,*,title=None,archived=None):
        """Rename or archive a listed conversation inside this workspace only; the source app is never written."""
        from .desktop_sessions import _valid_id
        if self.provider(agent) not in ('claude','codex') or not _valid_id(str(session_id)): raise ValueError('Invalid conversation')
        overrides=dict(self.get_setting('desktop.overrides',{}) or {})
        entry=dict(overrides.get(agent+':'+session_id) or {})
        if title is not None:
            title=sanitize(str(title)).strip()[:200]
            if title: entry['title']=title
            else: entry.pop('title',None)
            if title and self.store.get('sessions',{'agent':agent,'id':session_id}):
                self.store.update('sessions',{'agent':agent,'id':session_id},{'title':title,'updated_at':now()})
        if archived is not None: entry['archived']=bool(archived)
        if entry: overrides[agent+':'+session_id]=entry
        else: overrides.pop(agent+':'+session_id,None)
        self.set_setting('desktop.overrides',overrides)
        return entry

    def _project_for_directory(self,directory):
        directory=Path(directory)
        if not directory.is_dir(): raise ValueError('此對話的資料夾已不存在：'+str(directory))
        directory=directory.resolve()
        for project in self.list_projects():
            try:
                if Path(project['repo_path']).resolve()==directory: return project
            except OSError: continue
        return self.create_project(directory.name or str(directory),directory)

    def open_desktop_project(self,directory,title='新對話',*,agent=None):
        """Select (or create) the project for a listed folder and start a fresh task in it."""
        if agent: self._assert_agent_idle(agent)
        else: self._assert_idle()
        project=self._project_for_directory(directory)
        if agent:
            self.select_agent_project(agent,project['id'])
            task=self.create_agent_task(agent,title)
        else:
            self.select_project(project['id'])
            task=self.create_task(title)
        return {'project_id':project['id'],'task_id':task['id']}

    def open_desktop_session(self,record,history_limit=200,*,independent=False):
        """Map one explicitly chosen local conversation to a project and task, with its visible history.

        Never contacts the agent: resuming stays a separate explicit call."""
        from .desktop_sessions import read_history, _valid_id
        if not isinstance(record,dict): raise ValueError('Conversation metadata must be an object')
        agent=record.get('agent','claude')
        if self.provider(agent) not in ('claude','codex'): raise ValueError('Local conversations are available for Claude and Codex only')
        session_id=str(record.get('id') or '').lower()
        if not _valid_id(session_id): raise ValueError('Invalid session identifier')
        if independent: self._assert_agent_idle(agent)
        else: self._assert_idle()
        project=self._project_for_directory(str(record.get('cwd') or ''))
        if independent: self.select_agent_project(agent,project['id'])
        else: self.select_project(project['id'])
        title=sanitize(str(record.get('title') or session_id))[:200]
        tasks=[self.get_task(row['id']) for row in self.list_tasks(project_id=project['id'])]
        mapped=[t for t in tasks if t.get(agent+'_session')==session_id]
        # A conversation belongs to one task: the one named after it wins, and a task that merely
        # shares the title is reused only when it has no conversation of this role yet.
        task=(next((t for t in mapped if t['title']==title),None) or (mapped[0] if mapped else None)
              or next((t for t in tasks if t['title']==title and not t.get(agent+'_session')),None))
        if independent:
            if task: self.select_agent_task(agent,task['id'])
            else: task=self.create_agent_task(agent,title)
        elif task: self.select_task(task['id'])
        else: task=self.create_task(title)
        for other in mapped:
            if other['id']!=task['id']: self._set_task_session(other['id'],agent,'')
        identity={'agent':agent,'id':session_id}
        fields=dict(task_id=task['id'],project_id=project['id'],title=title,cwd=project['repo_path'],updated_at=now())
        if self.store.get('sessions',identity): self.store.update('sessions',identity,fields)
        else: self.store.insert('sessions',dict(identity,**fields,created_at=now(),metadata={'source':agent+'-local','imported_native':True}))
        self._set_task_session(task['id'],agent,session_id)
        self._contexts.pop(agent,None)
        added=self._import_local_items(agent,session_id,task['id'],read_history(self.provider(agent),session_id,history_limit))
        imported,tools=sum(kind=='message' for kind,_ in added),sum(kind=='event' for kind,_ in added)
        self._record('session_imported',agent,task_id=task['id'],session_id=session_id,
                     content=f'Local conversation opened; {imported} messages and {tools} tool records imported. Resume is a separate action.')
        return {'agent':agent,'project_id':project['id'],'task_id':task['id'],'session_id':session_id,'imported':imported,'tools':tools}

    def _import_local_items(self,agent,session_id,task_id,items):
        """Store visible messages and tool records read from a local conversation file; returns what was new, in order."""
        known={(m['role'],str(m['content']).strip()) for m in self.messages(task_id,agent)}
        added=[]
        for item in items:
            item_id='desktop-'+('' if agent in AGENTS else agent+'-')+session_id+'-'+item['id']
            if not item['id']: continue
            if item['kind']=='message':
                content=sanitize(item['content'])
                if is_hidden_reasoning(content) or (item['role'],str(content).strip()) in known: continue
                if self.store.get('messages',{'id':item_id}): continue
                self.store.insert('messages',dict(id=item_id,task_id=task_id,agent=agent,session_id=session_id,
                    role=item['role'],content=content,timestamp=item['timestamp'] or now(),status='complete',
                    metadata={'source':agent+'-local','imported':True}))
                known.add((item['role'],str(content).strip()))
                added.append(('message',item_id))
            elif not self.store.get('events',{'id':item_id}):
                payload=sanitize({'tool':item['tool'],'summary':item['summary'],'input':item['input'],'output':item['output'],'imported':True})
                if item['type']=='command': payload['command']=payload['summary']
                self.store.insert('events',dict(id=item_id,task_id=task_id,agent=agent,session_id=session_id,type=item['type'],
                    status='imported',timestamp=item['timestamp'] or now(),summary=str(payload['summary'])[:600],raw_ref='',payload=payload))
                added.append(('event',item_id))
        return added

    def sync_local_history(self,agent,after=''):
        """Bring in what another app has appended to this role's mapped local conversation since `after`.

        Read-only towards that app, and never contacts the agent."""
        from .desktop_sessions import read_history, _valid_id
        empty={'task_id':None,'session_id':'','items':[],'latest':after}
        if self.provider(agent) not in ('claude','codex'): return empty
        task=self.agent_task(agent)
        session_id=str((task or {}).get(agent+'_session') or '').lower()
        if not task or not _valid_id(session_id): return empty
        items=[item for item in read_history(self.provider(agent),session_id) if str(item['timestamp'])>after]
        added=self._import_local_items(agent,session_id,task['id'],items)
        rows=[(kind,self.store.get('messages' if kind=='message' else 'events',{'id':item_id})) for kind,item_id in added]
        latest=max([after]+[str(item['timestamp']) for item in items])
        return {'task_id':task['id'],'session_id':session_id,'items':rows,'latest':latest}

    def _context(self,agent):
        override=getattr(self._operation_context,'dot',None) if agent=='dot' else None
        if override is not None: return override
        if agent not in self._contexts:
            task=self.agent_task(agent) or {}
            self._contexts[agent]={'task_id':task.get('id'),'project_id':task.get('project_id',(self.agent_project(agent) or {}).get('id')),
                                   'session_id':task.get(agent+'_session','')}
        return self._contexts[agent]

    def _map_session(self,agent,session_id,*,native_session_id=None):
        if not session_id: return
        context=self._context(agent)
        context['session_id']=session_id
        task=self.get_task(context['task_id']) if context.get('task_id') else None
        project=self.get_project(context['project_id']) if context.get('project_id') else None
        identity={'agent':agent,'id':session_id}
        fields={'task_id':task['id'] if task else None,'project_id':project['id'] if project else None,
                'cwd':getattr(self.adapters.get(agent),'cwd',''),'updated_at':now()}
        if self.provider(agent)=='local' and hasattr(self.adapters.get(agent),'local_harness'):
            existing=self.store.get('sessions',identity) or {}
            fields['metadata']=dict(existing.get('metadata') or {},local_harness=self.adapters[agent].local_harness)
            if self.adapters[agent].local_harness=='hermes' and native_session_id is not None:
                fields['metadata']['native_session_id']=native_session_id
        if self.store.get('sessions',identity): self.store.update('sessions',identity,fields)
        else: self.store.insert('sessions',dict(identity,**fields,title=session_id,created_at=now()))
        if task: self._set_task_session(task['id'],agent,session_id)

    @_agent_action
    def create_session(self,agent):
        self._require_task(agent)
        adapter=self._adapter(agent)
        if not self.capabilities(agent).get('supports_sessions'): raise NotImplementedError(f'{agent}: sessions Unsupported')
        if getattr(adapter,'state','')=='Busy': raise RuntimeError('Wait for the active turn before creating a session')
        task=self.agent_task(agent)
        self._contexts[agent]={'task_id':task['id'],'project_id':task['project_id'],'session_id':''}
        self._apply_project(agent,self.agent_project(agent))
        result=adapter.create_session()
        sid=result.get('id',result.get('session_id','')) if isinstance(result,dict) else result
        if not isinstance(sid,str) or not sid.strip(): raise RuntimeError('Backend did not confirm a new session identifier')
        self._map_session(agent,sid)
        return result

    @_agent_action
    def resume_session(self,agent,session_id):
        self._require_task(agent)
        adapter=self._adapter(agent)
        if not self.capabilities(agent).get('supports_sessions'): raise NotImplementedError(f'{agent}: sessions Unsupported')
        if getattr(adapter,'state','')=='Busy': raise RuntimeError('Wait for the active turn before resuming a session')
        saved=self.store.get('sessions',{'agent':agent,'id':session_id})
        if self.provider(agent)=='local' and getattr(adapter,'local_harness','')=='hermes':
            if not saved or (saved.get('metadata') or {}).get('local_harness')!='hermes':
                raise ValueError('此對話不是已保存的 Hermes 對話；舊紀錄仍保留，請建立新的 Hermes 對話')
        if self.provider(agent)=='local' and saved and hasattr(adapter,'local_harness'):
            if (saved.get('metadata') or {}).get('local_harness',adapter.local_harness)!=adapter.local_harness:
                raise ValueError('此本地對話使用不同 Harness；請切回原 Harness 或建立新對話')
        if saved and agent!='dot':
            project=self.agent_project(agent)
            expected=project.get(self.provider(agent)+'_cwd') or project['repo_path']
            if saved.get('cwd') and Path(saved['cwd']).resolve()!=Path(expected).resolve():
                raise ValueError('此對話屬於不同工作目錄：'+saved['cwd']+'。請先選擇該專案與任務，再按 Resume；本次沒有恢復 session。')
        task=self.agent_task(agent)
        with self._native_session_operation(agent,session_id):
            self._contexts[agent]={'task_id':task['id'],'project_id':task['project_id'],'session_id':session_id}
            self._apply_project(agent,self.agent_project(agent))
            if self.provider(agent)=='local' and getattr(adapter,'local_harness','')=='hermes':
                adapter.restore_session_metadata(session_id,dict(saved.get('metadata') or {},cwd=saved.get('cwd','')))
            result=adapter.resume_session(session_id)
        self._map_session(agent,session_id)
        self._record('session_changed',agent,content='Resumed '+session_id)
        return result

    def rename_session(self,agent,session_id,title):
        if not self.store.get('sessions',{'agent':agent,'id':session_id}): raise ValueError('Unknown session')
        title=sanitize(str(title)).strip()
        if not title or len(title)>200 or any(ord(c)<32 for c in title): raise ValueError('Invalid session title')
        self.store.update('sessions',{'agent':agent,'id':session_id},{'title':title,'updated_at':now()})

    def _require_task(self,agent=None):
        if not (self.agent_task(agent) if agent else self.current_task): raise ValueError('Select or create a task first')

    @_agent_action
    def send_message(self,agent,content,model=None,effort=None,attachments=None):
        self._require_task(agent)
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
            attachments=[str(self.safe_artifact_path(path,agent=agent)) for path in attachments]
        task=self.agent_task(agent)
        mapped=task.get(agent+'_session','')
        active=getattr(adapter,'session_id','')
        if mapped and active!=mapped: raise RuntimeError('Resume the mapped session before sending to this task')
        if active and not mapped: raise RuntimeError('Create or explicitly resume a session for this task before sending')
        self._contexts[agent]={'task_id':task['id'],'project_id':task['project_id'],'session_id':mapped}
        self._apply_project(agent,self.agent_project(agent))
        capture=getattr(self._operation_context,'send_capture',None)
        dispatch_guard=(capture or {}).get('dispatch_guard')
        if dispatch_guard: dispatch_guard()
        message_id=uid('msg-')
        self._contexts[agent]['outbound_message_id']=message_id
        capture=getattr(self._operation_context,'send_capture',None)
        extra={}
        if capture is not None and capture['agent']==agent:
            capture['local_message_id']=message_id
            extra={'orchestration':dict(capture['metadata'])}
        active_request={'message_id':message_id,'owner':(capture or {}).get('run_id'),'adapter':adapter,'session_id':mapped,'native_turn_id':''}
        self._active_requests[agent]=active_request
        self.store.insert('messages',dict(id=message_id,task_id=task['id'],agent=agent,session_id=mapped,role='user',
                                         content=content,timestamp=now(),status='sending',metadata=dict(extra,attachments=attachments or [])))
        self._record('prompt_sent',agent,message_id=message_id,content=content,model=model,effort=effort)
        dispatch_state={'started':False}
        try:
            with self._native_session_operation(agent,mapped):
                probe=getattr(self._operation_context,'dispatch_probe',None)
                options={'model':model,'effort':effort,'attachments':attachments}
                if dispatch_guard:
                    def native_dispatch_guard(*,final=False):
                        dispatch_guard()
                        if final:
                            dispatch_state['started']=True
                            if probe is not None: probe['dispatched']=True
                    native_dispatch_guard()
                    options['dispatch_guard']=native_dispatch_guard
                else:
                    dispatch_state['started']=True
                    if probe is not None: probe['dispatched']=True
                result=adapter.send_message(content,**options)
            self.store.update('messages',{'id':message_id},{'status':'complete'})
            identity=getattr(adapter,'active_operation_id',None)
            cancel_token=identity() if callable(identity) else None
            with self._lock:
                if self._active_requests.get(agent) is active_request:
                    active_request['cancel_token']=cancel_token
            return result
        except Exception as exc:
            self.store.update('messages',{'id':message_id},{'status':'delivery_unknown' if dispatch_state['started'] else 'failed'})
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
        context=self._context(agent) if agent in self._instances else {'task_id':self.current_task_id,'session_id':''}
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
        for tap in self._event_taps:
            try: tap(event)
            except Exception: pass
        return event

    def ingest_event(self,agent,kind,**payload):
        event_type=kind
        self._check_agent(agent)
        with self._lock:
            if self._closed: return None
            if is_hidden_reasoning({'type':event_type}): return self._record('redaction',agent,content='Hidden reasoning event excluded')
            if event_type=='session' and self._context(agent).get('scope')!='dot_conversation':
                self._map_session(agent,str(payload.get('session_id') or payload.get('id') or ''),
                                  native_session_id=payload.get('native_session_id'))
            if event_type=='send_ack' and agent=='dot':
                message_id=self._context(agent).get('outbound_message_id')
                if message_id:
                    row=self.store.get('messages',{'id':message_id}) or {}
                    metadata=dict(row.get('metadata') or {},native_id=payload.get('native_id',''),native_room_id=getattr(self.adapters.get(agent),'native_room_id',''),source='manual send receipt')
                    self.store.update('messages',{'id':message_id},{'metadata':metadata,'status':'complete'})
            if event_type=='message_snapshot':
                conversation=None
                if agent=='dot':
                    target=getattr(self.adapters.get(agent),'target','')
                    if not target: raise ValueError('A selected Dot identity is required before importing snapshots')
                    conversation={'task_id':None,'session_id':target,'scope':'dot_conversation'}
                context=conversation or self._context(agent)
                if not context.get('task_id') and conversation is None: raise ValueError('Select a task before reading Dot history')
                native_id=str(payload.get('native_id',''))
                if not native_id: raise ValueError('Native message identity is required')
                room=getattr(self.adapters.get(agent),'native_room_id','')
                existing=self.store.find_native_message(agent,context.get('session_id',''),context.get('task_id'),room,native_id)
                incoming=sanitize(payload.get('content',''))
                prior_meta=(existing or {}).get('metadata') or {}
                if existing and existing.get('content')==incoming and existing.get('role')==payload.get('role','event') and existing.get('status')=='complete' and prior_meta.get('native_timestamp','')==payload.get('native_timestamp',''):
                    return dict(type=event_type,agent=agent,message_id=existing['id'],task_id=context.get('task_id'),session_id=context.get('session_id',''),unchanged=True)
                message_id=existing['id'] if existing else uid('msg-')
                payload['message_id']=message_id
                event=self._record(event_type,agent,**dict(payload,task_id=context.get('task_id'),session_id=context.get('session_id','')))
                values=dict(content=sanitize(payload.get('content','')),role=payload.get('role','event'),status='complete',
                    raw_ref=event['raw_ref'],metadata=dict(prior_meta,native_id=native_id,native_room_id=room,native_timestamp=payload.get('native_timestamp',''),content_kind=payload.get('content_kind','text'),source='manual snapshot; not streaming'))
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
                redact=getattr(self.adapters.get(agent),'redact_visible_text',lambda text:text)
                clean_content=sanitize(redact(stream['text']))
                payload['full_content']=clean_content
                payload['message_id']=stream['id']
                payload['content']=clean_content
                payload.pop('delta',None)
                status=('interrupted' if payload.get('status') in ('interrupted','cancelled') else 'complete') if event_type=='message_end' else 'streaming'
                event=self._record(event_type,agent,**payload)
                # Preserve complete lines while holding the unfinished line in memory:
                # a credential can cross arbitrary chunk boundaries, including its identifying prefix.
                persistent_content=clean_content if event_type=='message_end' else sanitize(redact(stream['text'][:stream['text'].rfind('\n')+1]))
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
        if task_id is None and agent in self._agent_selections and not self.agent_task(agent): return []
        task_id=task_id or ((self.agent_task(agent) or {}).get('id') if agent else self.current_task_id)
        clauses,values=[],[]
        if task_id: clauses.append('task_id=?'); values.append(task_id)
        if agent: clauses.append('agent=?'); values.append(agent)
        return self.store.query('SELECT * FROM messages'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY timestamp,rowid',values)

    def events(self,task_id=None,agent=None,limit=1000):
        if task_id is None and agent in self._agent_selections and not self.agent_task(agent): return []
        task_id=task_id or ((self.agent_task(agent) or {}).get('id') if agent else self.current_task_id)
        clauses,values=[],[]
        if task_id: clauses.append('task_id=?'); values.append(task_id)
        if agent: clauses.append('agent=?'); values.append(agent)
        values.append(max(1,min(int(limit),100000)))
        return self.store.query('SELECT * FROM events'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY timestamp DESC,rowid DESC LIMIT ?',values)

    def dot_conversation_messages(self,limit=None):
        """Cached native conversation projection; never used as task handoff input."""
        adapter=self.adapters.get('dot')
        target=getattr(adapter,'target','')
        if not target: return []
        room=getattr(adapter,'native_room_id','') or getattr(adapter,'settings',{}).get('expected_room_id','')
        if not room and getattr(adapter,'_require_room_provenance',False): return []
        rows=self.get_history('dot',target)
        unique={}
        for row in rows:
            if row.get('role') not in ('user','assistant'): continue
            if room and (row.get('metadata') or {}).get('native_room_id')!=room: continue
            native=(row.get('metadata') or {}).get('native_id')
            key=('native',native) if native else ('local',row['id'])
            previous=unique.get(key)
            rank=lambda item:(item.get('task_id') is None,str(item.get('timestamp') or ''),item['id'])
            if previous is None or rank(row)>=rank(previous): unique[key]=row
        from datetime import datetime, timezone
        def chronology(row):
            value=(row.get('metadata') or {}).get('native_timestamp') or row.get('timestamp','')
            try:
                stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
                if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
                return stamp.timestamp()
            except (ValueError,TypeError): return 0
        result=[]
        for row in sorted(unique.values(),key=chronology):
            displayed=dict(row)
            displayed['view_scope']='dot_conversation'
            displayed['timestamp']=(row.get('metadata') or {}).get('native_timestamp') or row.get('timestamp','')
            result.append(displayed)
        return result[-max(1,int(limit)):] if limit is not None else result

    @contextmanager
    def _agent_operation(self,agent):
        owner=threading.get_ident()
        with self._lock:
            if self._closed: raise RuntimeError('Workspace is closed')
            current=self._operations.get(agent)
            if current and current[0]!=owner: raise RuntimeError('Another operation is active for '+agent)
            self._operations[agent]=(owner,(current[1] if current else 0)+1)
        try: yield
        finally:
            with self._lock:
                current=self._operations.get(agent)
                if current and current[0]==owner:
                    if current[1]>1: self._operations[agent]=(owner,current[1]-1)
                    else: self._operations.pop(agent,None)

    @contextmanager
    def _dot_root_operation(self):
        adapter=self._adapter('dot')
        if not self._dot_root_lock.acquire(blocking=False):
            raise RuntimeError('Another dot conversation operation is active')
        old=getattr(self._operation_context,'dot',None)
        try:
            with self._agent_operation('dot'):
                self._operation_context.dot={'task_id':None,'project_id':None,'session_id':adapter.target,'scope':'dot_conversation'}
                yield self._operation_context.dot
        finally:
            self._operation_context.dot=old
            self._dot_root_lock.release()

    def connect_dot_conversation(self):
        adapter=self._adapter('dot')
        with self._dot_root_operation():
            if not self.connect('dot'): return False
            if adapter.native_room_id:
                saved=self.get_setting('agent.dot',{}) or {}
                self.set_setting('agent.dot',dict(saved,dot_id=adapter.target,dot_name=adapter.target_name,expected_room_id=adapter.native_room_id))
            # Called only after a Connect+initial-read confirmation in the UI.
            adapter.authorize_manual_action('messages')
            return adapter.refresh_messages(False)

    def read_dot_conversation(self,older=False):
        adapter=self._adapter('dot')
        if adapter.state!='Connected' or not getattr(adapter,'target',''):
            raise RuntimeError('Connect the selected dot before loading its conversation')
        with self._dot_root_operation(): return adapter.refresh_messages(older)

    def send_dot_conversation(self,content):
        adapter=self._adapter('dot')
        if adapter.state!='Connected' or not getattr(adapter,'target',''):
            raise RuntimeError('Connect the selected dot before sending')
        if not str(content).strip(): raise ValueError('Message is empty')
        with self._dot_root_operation() as context:
            message_id=uid('msg-')
            context['outbound_message_id']=message_id
            self._active_requests['dot']={'message_id':message_id,'owner':None,'adapter':adapter,'session_id':adapter.target,'native_turn_id':''}
            self.store.insert('messages',dict(id=message_id,task_id=None,agent='dot',session_id=adapter.target,
                role='user',content=sanitize(content),timestamp=now(),status='sending',metadata={'source':'ongoing dot conversation','native_room_id':getattr(adapter,'native_room_id','')}))
            self._record('prompt_sent','dot',message_id=message_id,content=content)
            try:
                result=adapter.send_message(content)
                self.store.update('messages',{'id':message_id},{'status':'complete'})
                return result
            except Exception as exc:
                self.store.update('messages',{'id':message_id},{'status':'delivery_unknown'})
                self._record('error','dot',content=str(exc))
                raise

    def _validate_run_contract(self,contract,*,receipt=False):
        agent=contract.get('agent')
        self._check_agent(agent)
        task=self.agent_task(agent) or {};project=self.agent_project(agent) or {};adapter=self._adapter(agent)
        if task.get('id')!=contract.get('task_id') or project.get('id')!=contract.get('project_id'):
            raise RuntimeError('Orchestration task/project binding changed')
        if task.get(agent+'_session','')!=contract.get('session_id') or getattr(adapter,'session_id','')!=contract.get('session_id'):
            raise RuntimeError('Orchestration session binding changed')
        if agent=='dot' and (not contract.get('dot_id') or not contract.get('room_id') or adapter.target!=contract['dot_id'] or getattr(adapter,'native_room_id','')!=contract['room_id']):
            raise RuntimeError('Orchestration Dot identity/room binding changed')
        if receipt:
            active=self._active_requests.get(agent) or {}
            if active.get('owner')!=contract.get('run_id') or active.get('message_id')!=contract.get('local_request_id') or active.get('adapter') is not adapter:
                raise RuntimeError('Orchestration request ownership changed')
        return adapter

    def send_orchestration_message(self,agent,text,contract):
        if contract.get('agent')!=agent or text!=contract.get('prompt'):
            raise ValueError('Orchestration request does not match its contract')
        if not contract.get('run_id') or not contract.get('correlation_id'): raise ValueError('Missing correlation identity')
        with self._agent_operation(agent):
            adapter=self._validate_run_contract(contract)
            previous=getattr(self._operation_context,'send_capture',None)
            def dispatch_guard():
                run_guard=contract.get('_dispatch_guard')
                if callable(run_guard): run_guard()
                if self._validate_run_contract(contract) is not adapter:
                    raise RuntimeError('Orchestration adapter changed before dispatch')
            capture={'agent':agent,'run_id':contract['run_id'],'dispatch_guard':dispatch_guard,'metadata':{key:contract.get(key) for key in ('run_id','step_sequence','correlation_id','step','task_id','project_id')}}
            self._operation_context.send_capture=capture
            try:
                if agent=='dot':
                    with adapter.operation_scope(owner=contract['run_id']): result=self.send_message(agent,text)
                else: result=self.send_message(agent,text)
                local=capture['local_message_id']
                stored=self.store.get('messages',{'id':local}) or {}
                native=(stored.get('metadata') or {}).get('native_id','') if agent=='dot' else ''
                return {'local_message_id':local,'native_message_id':native,'result':result}
            finally: self._operation_context.send_capture=previous

    def read_dot_snapshot_for_run(self,contract):
        if contract.get('agent')!='dot': raise ValueError('Dot snapshot contract required')
        with self._agent_operation('dot'):
            adapter=self._validate_run_contract(contract,receipt=True)
            with self._dot_root_operation(),adapter.operation_scope(owner=contract['run_id']):
                adapter.refresh_messages(False)
                return [dict(row) for row in adapter.get_snapshot()]

    def accept_orchestration_reply(self,contract,snapshot):
        if contract.get('agent')!='dot' or snapshot.get('role')!='assistant': raise ValueError('Only a verified Dot assistant reply can be accepted here')
        with self._lock:
            self._validate_run_contract(contract,receipt=True)
            if snapshot.get('native_room_id')!=contract['room_id']: raise ValueError('Reply room mismatch')
            source=self.store.find_native_message('dot',contract['dot_id'],None,contract['room_id'],snapshot.get('native_id'))
            if not source or source.get('role')!='assistant' or source.get('content')!=snapshot.get('content'):
                raise ValueError('Verified root snapshot changed or is unavailable')
            digest=hashlib.sha256(source['content'].encode()).hexdigest()
            material=json.dumps([contract['run_id'],contract['correlation_id'],contract['dot_id'],contract['room_id'],snapshot['native_id']],ensure_ascii=False)
            identity='orch-'+hashlib.sha256(material.encode()).hexdigest()
            existing=self.store.get('messages',{'id':identity})
            if existing:
                if existing['content']!=source['content']: raise ValueError('Accepted handoff evidence is immutable')
                return existing
            metadata={'source_root_message_id':source['id'],'native_id':snapshot['native_id'],'native_room_id':contract['room_id'],
                      'run_id':contract['run_id'],'correlation_id':contract['correlation_id'],'step_sequence':contract.get('step_sequence'),
                      'native_request_id':contract.get('native_request_id'),'local_request_id':contract.get('local_request_id'),
                      'content_sha256':digest,'source':'validated application envelope; not native completion'}
            self.store.insert('messages',dict(id=identity,task_id=contract['task_id'],agent='dot',session_id=contract['dot_id'],
                role='assistant',content=source['content'],timestamp=now(),status='complete',raw_ref=source.get('raw_ref',''),metadata=metadata))
            return self.store.get('messages',{'id':identity})

    def stop_orchestration_message(self,agent,contract):
        with self._agent_operation(agent):
            adapter=self.adapters.get(agent);active=self._active_requests.get(agent) or {}
            if active.get('adapter') is not adapter or active.get('owner')!=contract.get('run_id') or active.get('message_id')!=contract.get('local_request_id'):
                return False
            if getattr(adapter,'state','')!='Busy' or getattr(adapter,'session_id','')!=contract.get('session_id'): return False
            token=active.get('cancel_token')
            guarded_stop=getattr(adapter,'stop_if_owned',None)
            if token is None or not callable(guarded_stop): return False
            result=guarded_stop(token)
            if result:
                self._record('stop',agent,content='Cancellation requested for the owned backend operation')
            return bool(result)

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
        task=self.get_task(source['task_id']) if source.get('task_id') else None
        if not task: raise ValueError('This dot conversation message is not associated with a Workspace task; select task-specific evidence for handoff')
        if not isinstance(source.get('content'),str) or not source['content'].strip():
            raise ValueError('Source response has no text content to hand off')
        project=self.get_project(task['project_id'])
        timestamp=now()
        metadata={'source_agent':source['agent'],'target_agent':target_agent,'task_id':task['id'],'project_id':project['id'],
                  'project':project['name'],'branch':task['branch'],'timestamp':timestamp,'source_session':source['session_id']}
        target=self.agent_task(target_agent) or {}
        metadata.update(target_task_id=target.get('id'),target_project_id=target.get('project_id'),
                        target_session=target.get(target_agent+'_session',''))
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
        identity=preview if isinstance(preview,str) else preview['id']
        initial=self.store.get('handoffs',{'id':identity})
        if not initial: raise ValueError('Handoff preview does not exist')
        with self._agent_operation(initial['target_agent']):
            return self._send_handoff(preview)

    def _send_handoff(self,preview):
        handoff_id=preview if isinstance(preview,str) else preview['id']
        with self._lock:
            record=self.store.get('handoffs',{'id':handoff_id})
            if not record: raise ValueError('Handoff preview does not exist')
            if record['status']!='prepared': raise ValueError('This handoff has already been attempted; prepare a new preview to retry')
            target=self.agent_task(record['target_agent']) or {}
            expected=(record.get('metadata') or {}).get('target_task_id',record['task_id'])
            if target.get('id')!=expected: raise ValueError('Target agent task changed; prepare the handoff again')
            metadata=record.get('metadata') or {}
            if 'target_session' in metadata and target.get(record['target_agent']+'_session','')!=metadata['target_session']:
                raise ValueError('Target agent session changed; prepare the handoff again')
            self.store.update('handoffs',{'id':handoff_id},{'status':'sending'})
        previous_probe=getattr(self._operation_context,'dispatch_probe',None)
        probe={'dispatched':False};self._operation_context.dispatch_probe=probe
        try: result=self.send_message(record['target_agent'],record['handoff_message'])
        except Exception:
            self.store.update('handoffs',{'id':handoff_id},{'status':'delivery_unknown' if probe['dispatched'] else 'failed'})
            raise
        finally:
            self._operation_context.dispatch_probe=previous_probe
        self.store.update('handoffs',{'id':handoff_id},{'status':'sent'})
        self._record('handoff',record['target_agent'],handoff_id=handoff_id,source_agent=record['source_agent'],content=record['handoff_message'])
        return result

    @_synchronized
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

    def safe_artifact_path(self,path,*,agent=None):
        roots=[self.store.artifact_dir]
        project=self.agent_project(agent) if agent else self.current_project
        if project: roots.append(project['repo_path'])
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
            task=self.get_task(task_id) if task_id else None
            project=self.get_project(task['project_id']) if task else self.current_project
            roots=[self.store.artifact_dir]+([project['repo_path']] if project else [])
            source=safe_file(path,roots)
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
            # The Monitor's hermes.log belongs to the built-in local (Hermes) panel.
            target='local' if agent=='hermes' else agent
            event=self._record('legacy',target if target in AGENTS else 'workspace',task_id=None,content=clean,source=entry['source'])
            results.append(dict(entry,agent=target,content=state['contents'][agent],raw_ref=event['raw_ref']))
        return results

    def poll_requests(self):
        """Advance file requests written by the hermes-delegation skill's run.sh (see acw/requests.py)."""
        if self._closed: return []
        results = self.requests.poll()
        self.maybe_checkpoint()
        return results

    def maybe_checkpoint(self):
        """Checkpoint idle workspaces at most once per five-minute success interval."""
        with self._lock:
            if self._closed or any(getattr(adapter, 'state', '') == 'Busy' for adapter in self.adapters.values()):
                return None
            if self._checkpoint_clock() - self._last_checkpoint <= 300:
                return None
            try:
                result = self.store.checkpoint('PASSIVE')
                if not result[0] and result[1] == result[2]:
                    self._last_checkpoint = self._checkpoint_clock()
                return result
            except Exception:
                logging.getLogger('acw.store').warning('Periodic WAL checkpoint failed', exc_info=True)
                return None

    def logs_path(self,agent=None):
        if agent: self._check_agent(agent)
        return self.store.raw_dir

    def project_file(self,relative_path,project_id=None):
        project=self.get_project(project_id) if project_id else self.current_project
        if not project: raise ValueError('Select a project first')
        return safe_file(Path(project['repo_path'])/relative_path,[project['repo_path']])

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
        with self._lock:
            if self._closed: return
            if self._operations: raise RuntimeError('Wait for in-flight workspace operations before closing')
            self._closed=True
            self.requests.close()
            self.store.close()
            self._streams.clear()

