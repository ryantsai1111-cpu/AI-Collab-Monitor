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
    from acw.adapters.hermes import HermesAdapter
    from acw.agents import make_adapter
    app=QApplication(sys.argv[:1]);app.setStyle('Fusion');app.setApplicationName('AI Collaboration Workspace');app.setOrganizationName('AI Collaboration Workspace')
    args.data_dir.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(args.data_dir/'workspace.lock'));lock.setStaleLockTime(30000)
    if not lock.tryLock(100):
        QMessageBox.information(None,'Workspace already open','This data directory is already open. Use the existing window.');return 1
    core=None
    window=None
    try:
        core=WorkspaceCore(args.data_dir)
        if core.get_setting('ui.sidebar_page') is None: core.set_setting('ui.sidebar_page','nav')
        seed=ROOT/'config'/'local-llm.json'
        if seed.is_file() and not core.get_setting('agent.local'):
            # Import an explicit Hermes seed once. Legacy endpoint configuration
            # must never override Hermes settings or supply another CLI binary.
            import json
            try:
                values=json.loads(seed.read_text(encoding='utf-8'))
                if isinstance(values,dict) and values.get('harness')=='hermes':
                    allowed={k:values[k] for k in ('harness','executable','provider','model','run_budget','max_turns','enabled') if k in values}
                    if allowed.get('model'): allowed['default_model']=allowed['model']
                    core.set_setting('agent.local',allowed)
            except (OSError,ValueError): pass
        local=Path(os.environ.get('LOCALAPPDATA',''))
        claudes=list((local/'Packages'/'Claude_pzs8sxrjxfjjc'/'LocalCache'/'Roaming'/'Claude'/'claude-code').glob('*/*/claude.exe'))
        codexes=list((local/'OpenAI'/'Codex'/'bin').glob('*/codex.exe'))
        def newest(paths): return str(max(paths,key=lambda p:p.stat().st_mtime)) if paths else ''
        for agent, cls, default in [('claude',ClaudeAdapter,newest(claudes)),('dot',DotAdapter,''),('codex',CodexAdapter,newest(codexes)),('local',HermesAdapter,'')]:
            settings=core.get_setting('agent.'+agent,{}) or {}
            exe=settings.pop('executable','') or default
            settings.setdefault('attachment_roots',[str(core.store.artifact_dir)])
            core.set_adapter(agent,cls(core.make_emitter(agent),executable=exe,**settings))
        for agent in core.agent_ids:
            if agent in core.adapters:
                continue
            settings=dict(core.get_setting('agent.'+agent,{}) or {})
            provider=core.provider(agent)
            if not settings.get('executable'):
                settings['executable']=newest(claudes) if provider=='claude' else newest(codexes) if provider=='codex' else ''
            settings.setdefault('attachment_roots',[str(core.store.artifact_dir)])
            core.set_adapter(agent,make_adapter(provider,core.make_emitter(agent),settings))
        window=MainWindow(core);window.show()
        return app.exec()
    finally:
        if window is not None:
            for name in ('timer','sync_timer','run_timer'):
                timer=getattr(window,name,None)
                if timer is not None: timer.stop()
            window._closed=True
        try:
            if core is not None:
                for adapter in core.adapters.values():
                    try: adapter.disconnect()
                    except Exception: pass
                core.close()
        finally:
            lock.unlock()
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
