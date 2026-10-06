from dataclasses import dataclass, field, asdict

@dataclass
class Capabilities:
    supports_model_selection: bool = False
    supports_effort: bool = False
    supports_sessions: bool = False
    supports_create_session: bool | None = None
    supports_files: bool = False
    supports_tools: bool = False
    supports_project: bool = False
    supports_cancel: bool = False
    supports_streaming: bool = False
    supports_history: bool = False
    supports_approval: bool = False
    models: list = field(default_factory=list)
    efforts: list = field(default_factory=list)
    detail: str = ''
    def to_dict(self): return asdict(self)

class Adapter:
    agent = 'unknown'
    def __init__(self, emit, executable='', **settings):
        self.emit, self.executable, self.settings = emit, executable, settings
        self.capabilities = Capabilities()
        self.state, self.session_id, self.cwd, self.last_error, self.version = 'Disconnected', '', '', '', ''
    def set_state(self, state):
        self.state = state
        self.emit('state', state=state)
    def connect(self): raise NotImplementedError
    def disconnect(self): self.set_state('Disconnected')
    def list_models(self): return self.capabilities.models
    def list_efforts(self, model=None): return self.capabilities.efforts
    def attachment_capability(self, model=None):
        return {'supported':self.capabilities.supports_files,'detail':'Supported by backend' if self.capabilities.supports_files else 'Attachments Unsupported by backend'}
    def list_sessions(self): return []
    def create_session(self): raise NotImplementedError
    def resume_session(self, session_id): raise NotImplementedError
    def send_message(self, content, model=None, effort=None, attachments=None): raise NotImplementedError
    def stop(self): raise NotImplementedError
    def set_project(self, path, metadata=None): self.cwd = path
    def stream_events(self): return 'callback'
    def get_history(self, session_id=None): return []
    def approve(self, request_id, approved): raise NotImplementedError
    def diagnostics(self):
        return dict(agent=self.agent, executable=self.executable, version=self.version,
                    backend=type(self).__name__, session=self.session_id, cwd=self.cwd,
                    state=self.state, last_error=self.last_error, capabilities=self.capabilities.to_dict())
