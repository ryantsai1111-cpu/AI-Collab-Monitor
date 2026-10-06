"""Desktop entry point. No backend starts until the user presses Connect."""
import sys, os, argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AI-Collaboration-Workspace'/'data')
    args=parser.parse_args()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QLockFile
    from acw.core import WorkspaceCore
    from acw.ui import MainWindow
    from acw.adapters.claude import ClaudeAdapter
    from acw.adapters.codex import CodexAdapter
    from acw.adapters.dot import DotAdapter
    from acw.adapters.local import make_local_adapter
    app=QApplication(sys.argv[:1]);app.setStyle('Fusion');app.setApplicationName('AI Collaboration Workspace');app.setOrganizationName('AI Collaboration Workspace')
    args.data_dir.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(args.data_dir/'workspace.lock'));lock.setStaleLockTime(30000)
    if not lock.tryLock(100):
        QMessageBox.information(None,'Workspace already open','This data directory is already open. Use the existing window.');return 1
    core=WorkspaceCore(args.data_dir)
    local=Path(os.environ.get('LOCALAPPDATA',''))
    claudes=list((local/'Packages'/'Claude_pzs8sxrjxfjjc'/'LocalCache'/'Roaming'/'Claude'/'claude-code').glob('*/*/claude.exe'))
    codexes=list((local/'OpenAI'/'Codex'/'bin').glob('*/codex.exe'))
    def newest(paths): return str(max(paths,key=lambda p:p.stat().st_mtime)) if paths else ''
    for agent, cls, default in [('claude',ClaudeAdapter,newest(claudes)),('dot',DotAdapter,''),('codex',CodexAdapter,newest(codexes)),('local',make_local_adapter,'')]:
        settings=core.get_setting('agent.'+agent,{}) or {}
        exe=settings.pop('executable',default)
        settings.setdefault('attachment_roots',[str(core.store.artifact_dir)])
        if agent=='local':
            settings.setdefault('codex_executable',newest(codexes))
            settings.setdefault('claude_executable',newest(claudes))
        core.set_adapter(agent,cls(core.make_emitter(agent),executable=exe,**settings))
    window=MainWindow(core);window.show()
    result=app.exec()
    for adapter in core.adapters.values():
        try: adapter.disconnect()
        except Exception: pass
    if hasattr(core,'close'):core.close()
    lock.unlock()
    return result
if __name__=='__main__':
    try: sys.exit(main())
    except Exception:
        import traceback
        from acw.security import redact_text
        trace=redact_text(traceback.format_exc())
        fallback=ROOT/'startup-error.log'
        fallback.write_text(trace,encoding='utf-8')
        try:
            from PySide6.QtWidgets import QApplication,QMessageBox
            instance=QApplication.instance() or QApplication([])
            QMessageBox.critical(None,'Workspace startup error',trace)
        except Exception: pass
        sys.exit(1)
