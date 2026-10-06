"""Human-triggered unofficial pinned CLI; no startup calls or polling."""
import json, re, subprocess, sys, unicodedata
from pathlib import Path
from .base import Adapter, Capabilities
from ..security import sanitize

COMMIT = '1413f7b61060eb582fd53a0210ef1a499d158fe0'
DOT_ID_PATTERN = r'[A-Za-z0-9][A-Za-z0-9._~-]{0,199}'  # HTTP path guard, NOT the list identity schema.
def normalized_dot_name(name):
    return unicodedata.normalize('NFKC',str(name)).strip()
def valid_dot_id(value):
    # resolve_dot compares list-node identity literally. _ID only guards HTTP
    # paths in the unchanged CLI; metadata identity need not be a URL segment.
    # Never rewrite/trim/decode it. Local bound/control checks protect argv/logs.
    return (isinstance(value,str) and 0<len(value)<=16384
            and not any(ord(char)<32 or ord(char)==127 for char in value))
def checked_action(method):
    def wrapped(self,*args,**kwargs):
        try:return method(self,*args,**kwargs)
        except Exception as exc:
            if self.state=='Busy':
                self.last_error=str(sanitize(str(exc)));self.emit('error',content=self.last_error);self.set_state('Error')
            raise
    return wrapped
DISCLOSURE = ('Unofficial integration. This action launches the pinned chatgpt-dot-cli locally. '
    'It reads the existing Codex ChatGPT login and transmits its access token to '
    'https://chatgpt.com/backend-api. Workspace does not read the credential file. '
    'The CLI enumerates Dot metadata to resolve your selected Dot; only that Dot conversation '
    'messages are read or sent. No automatic login, polling or relay. '
    'Continue only for your intended G8毛 Dot. ')

def cli_runner(operation, dot_id='', text='', before=''):
    root=Path(__file__).resolve().parents[2]
    python=Path(sys.executable)
    if python.name.lower()=='pythonw.exe': python=python.with_name('python.exe')
    args=[str(python),'-X','utf8','-I',str(root/'scripts'/'dot_cli_entry.py'),operation]
    if dot_id: args += ['--dot-id='+dot_id]
    if before: args += ['--before='+before]
    if operation=='send': args += ['--',text]
    proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    out,err=proc.communicate()  # No timeout kill / process-tree kill.
    if proc.returncode: raise RuntimeError(sanitize(err.decode('utf-8',errors='replace'))[:3000] or 'Dot CLI failed')
    return sanitize(json.loads(out.decode('utf-8')))

class DotAdapter(Adapter):
    agent = 'dot'
    BLOCKER = ('Unofficial integration: select Dot and explicitly consent locally. '
               'Model / effort: Managed by ChatGPT / dot. '
               'Streaming, Stop, attachments and New chat: Unsupported.')
    def __init__(self, emit, executable='', runner=None, **settings):
        super().__init__(emit, executable, **settings)
        self._runner=runner or cli_runner
        self.target=settings.get('dot_id','')
        self.target_name=normalized_dot_name(settings.get('dot_name',''))
        if self.target and (not valid_dot_id(self.target) or self.target_name!='G8毛'):
            self.target='';self.target_name=''
        self._ticket=None
        self.before=''
        self._history=[]
        self.metadata = {}
        self._refresh_capabilities()
    def _refresh_capabilities(self):
        self.capabilities=Capabilities(supports_sessions=bool(self.target),supports_history=bool(self.target),supports_create_session=False,
            detail=self.BLOCKER+(' Selected: '+self.target_name+' ('+self.target+').' if self.target else ' Select Dot first.'))
    def authorize_manual_action(self,action):
        if action not in ('list','connect','messages','send'): raise ValueError('Invalid Dot action')
        if self.state=='Busy': raise RuntimeError('Wait for this request; backend Stop Unsupported')
        self._ticket=(action,self.target)
    def _call(self,action,operation,hold_busy=False,**kwargs):
        ticket,self._ticket=self._ticket,None
        if ticket!=(action,self.target): raise PermissionError('One-use local human consent required for this Dot action')
        if operation!='list' and not self.target: raise ValueError('Select Dot first')
        previous=self.state;self.set_state('Busy')
        try:
            result=sanitize(self._runner(operation,dot_id=self.target if operation!='list' else '',**kwargs))
            if operation=='list':
                items=result.get('items',[]) if isinstance(result,dict) else result
                if not isinstance(items,list) or not all(isinstance(x,dict) for x in items): raise RuntimeError('Malformed Dot list response')
            elif operation=='messages':
                if not isinstance(result,dict) or not isinstance(result.get('messages'),list) or not all(isinstance(x,dict) for x in result['messages']): raise RuntimeError('Malformed Dot messages response')
                if not isinstance(result.get('lines',[]),list): raise RuntimeError('Malformed Dot speaker metadata')
            elif not isinstance(result,dict):raise RuntimeError('Malformed Dot send receipt')
            return result
        except Exception as exc:
            self.last_error=str(sanitize(str(exc)));self.emit('error',content=self.last_error);self.set_state('Error');raise
        finally:
            if self.state=='Busy' and not hold_busy: self.set_state(previous)
    @checked_action
    def discover_targets(self):
        previous=self.state
        result=self._call('list','list',hold_busy=True)
        items=result.get('items',[]) if isinstance(result,dict) else result
        targets=[]
        for item in items:
            name=normalized_dot_name(item.get('display_name',''))
            native_id=item.get('id')
            if name=='G8毛':
                # Persist only this approved target's non-secret identifier/schema,
                # so a rejected selection is diagnosable without another API call.
                self.emit('dot_target_metadata',dot_id=native_id if isinstance(native_id,str) else None,
                    dot_id_type=type(native_id).__name__,display_name=name,
                    fields=[key for key in ('id','display_name','messaging_room_id','active_root_thread_id') if key in item],
                    messaging_room_id=item.get('messaging_room_id') if isinstance(item.get('messaging_room_id'),str) else None,
                    active_root_thread_id=item.get('active_root_thread_id') if isinstance(item.get('active_root_thread_id'),str) else None,
                    source='Human-triggered metadata list; no messages or other Dot previews retained')
                if not isinstance(native_id,str):raise RuntimeError('Unsupported Dot identifier type: '+type(native_id).__name__+'; native identity was not coerced')
            if isinstance(native_id,str) and native_id:targets.append({'id':native_id,'name':name})
        self.set_state(previous)
        return targets
    def configure_target(self,dot_id,name=''):
        if self.state in ('Connected','Busy'): raise RuntimeError('Disconnect before changing Dot')
        if not valid_dot_id(dot_id): raise ValueError('Unsupported Dot identifier type/control/size; selection was not saved')
        name=normalized_dot_name(name)
        if name!='G8毛': raise ValueError('Only the approved G8毛 Dot is in scope')
        self.target,self.target_name=dot_id,str(sanitize(name))
        self._ticket=None;self.session_id='';self.last_error='';self._refresh_capabilities()
        self.set_state('Disconnected')
    @checked_action
    def connect(self):
        if not self.target:
            self.last_error=self.BLOCKER;self.set_state('Offline');return False
        result=self._call('connect','list',hold_busy=True)
        items=result.get('items',[]) if isinstance(result,dict) else result
        chosen=next((x for x in items if isinstance(x,dict) and x.get('id')==self.target),None)
        if not chosen:
            self.set_state('Error');raise RuntimeError('Selected Dot missing; no other conversation was selected')
        if normalized_dot_name(chosen.get('display_name',''))!='G8毛':
            self.set_state('Error');raise RuntimeError('Selected Dot name differs from approved G8毛; connection refused')
        self.target_name=normalized_dot_name(sanitize(chosen.get('display_name',self.target_name)))
        self.version='0.2.2 / '+COMMIT;self.session_id=self.target;self._refresh_capabilities()
        self.last_error=''
        self.emit('session',session_id=self.target,native_room_id=chosen.get('messaging_room_id',''),content='Existing Dot identity: '+self.target_name+'; this is not a new chat thread')
        self.set_state('Connected')
        return True
    def disconnect(self):
        if self.state=='Busy': raise RuntimeError('Wait for this request; no server cancellation')
        self._ticket=None;super().disconnect()
    def create_session(self): raise NotImplementedError('New independent Dot chat session Unsupported')
    def resume_session(self,session_id):
        if self.state!='Connected' or session_id!=self.target: raise RuntimeError('Connect selected Dot before mapping this task')
        self.session_id=self.target;self.emit('session',session_id=self.target);return self.target
    def list_sessions(self):
        return [{'session_id':self.session_id,'title':self.target_name}] if self.session_id else []
    def get_history(self,session_id=None):
        if session_id and session_id!=self.target: return []
        return list(self._history)  # Cached explicit snapshot only; never a network read.
    @checked_action
    def refresh_messages(self,older=False):
        if self.state!='Connected': raise RuntimeError('Connect selected Dot first')
        result=self._call('messages','messages',hold_busy=True,before=self.before if older else '')
        messages=result.get('messages',[]);lines=list(reversed(result.get('lines',[])))
        for i,item in enumerate(messages):
            native_id=str(item.get('id',''))
            if not native_id: continue
            speaker=lines[i].split(':',1)[0] if i<len(lines) and isinstance(lines[i],str) else 'unknown'
            role='assistant' if speaker=='dot' else 'user' if speaker=='you' else 'event'
            body=item.get('content',{});text=body.get('text','') if isinstance(body,dict) else str(body)
            self.emit('message_snapshot',native_id=native_id,role=role,content=text,
                      native_timestamp=item.get('created_at',''),source='Manual paginated snapshot; not streaming')
        if messages: self.before=str(messages[0].get('id',''))
        self.emit('history_page',count=len(messages),before=self.before,content='Manual snapshot loaded; no polling')
        self._history=list(messages)
        self.set_state('Connected')
        return len(messages)
    @checked_action
    def send_message(self,content,model=None,effort=None,attachments=None):
        if self.state!='Connected': raise RuntimeError('Connect selected Dot first')
        if model or effort or attachments: raise NotImplementedError('Dot model, effort and attachments Unsupported')
        if not str(content).strip(): raise ValueError('Message is empty')
        result=self._call('send','send',hold_busy=True,text=content)
        self.emit('send_ack',native_id=str(result.get('id','')),content='Backend accepted manual send. Press Refresh for replies; not streaming.')
        self.set_state('Connected')
        return result
    def stop(self): raise NotImplementedError('Unsupported: local read stop is not server cancellation')
    def set_project(self, path, metadata=None):
        self.metadata = dict(metadata or {})
        self.cwd = ''
        self.emit('project', metadata=self.metadata, content='Metadata only; dot has no filesystem connection.')
    def diagnostics(self):
        return {**super().diagnostics(), 'metadata':self.metadata,'selected_dot':self.target,
                'integration':'Unofficial / live validation pending','background_polling':False}
