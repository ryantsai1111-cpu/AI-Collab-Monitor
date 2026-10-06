"""Open real, disconnected Workspace for HUMAN Dot activation only.
No CLI/auth/backend call. Uses isolated local task/data, not existing work sessions.
"""
import runpy,sys,argparse
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'vendor'),str(root)]
from acw.core import WorkspaceCore
parser=argparse.ArgumentParser();parser.add_argument('--selection-fix',action='store_true');parser.add_argument('--identifier-fix',action='store_true');options=parser.parse_args()
base=root/'tests'/('dot-human-handoff-identifier-fix' if options.identifier_fix else 'dot-human-handoff-selection-fix' if options.selection_fix else 'dot-human-handoff')
data=base/'data'
repo=base/'repo';repo.mkdir(parents=True,exist_ok=True)
core=WorkspaceCore(data)
if not core.current_project:
    project=core.create_project('DOT IDENTIFIER CONTRACT FIX — ISOLATED LOCAL DATA' if options.identifier_fix else 'DOT SELECTION FIX — ISOLATED LOCAL DATA' if options.selection_fix else 'DOT HUMAN ACTIVATION — ISOLATED LOCAL DATA',repo)
    core.select_project(project['id'])
if not core.current_task:core.create_task('SOURCE CONTRACT UPDATED — Copy native ID or Use G8; HUMAN ONLY' if options.identifier_fix else 'UPDATED — Select G8 Dot, then Use G8; HUMAN ONLY' if options.selection_fix else 'HUMAN ONLY — select G8 Dot, review each action; no automatic calls')
core.close()
sys.argv=[str(root/'run.py'),'--data-dir',str(data)]
runpy.run_path(str(root/'run.py'),run_name='__main__')
