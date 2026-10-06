"""Deploy the official bundled session SDK; model interaction uses the installed CLI."""
from pathlib import Path
import os,sys,shutil,json
source=Path(sys.argv[1]).resolve(strict=True)
dest=Path(sys.argv[2]).absolute()
expected=Path(os.environ['LOCALAPPDATA'])/'AI-Collaboration-Workspace/app/tools/claude-session-sdk/node_modules'
if dest!=expected:raise ValueError('Only the dedicated application dependency directory is permitted')
pkg=source/'@anthropic-ai/claude-agent-sdk'
info=json.loads((pkg/'package.json').read_text(encoding='utf-8'))
if info['name']!='@anthropic-ai/claude-agent-sdk' or info['version']!='0.3.289':raise ValueError('Official pinned SDK bundle required')
out=dest/'@anthropic-ai/claude-agent-sdk'
if out.is_junction() or out.is_symlink():
 # Remove only this install's directory link, never its target contents.
 if out.is_junction():os.rmdir(out)
 else:out.unlink()
out.mkdir(parents=True,exist_ok=True)
for entry in pkg.iterdir():
 if entry.name=='node_modules':continue # optional query CLI/peers unused by the bundled session APIs
 if entry.is_dir():shutil.copytree(entry,out/entry.name,dirs_exist_ok=True)
 else:shutil.copy2(entry,out/entry.name)
(dest.parent/'deployment.json').write_text(json.dumps({'sdk':info['name'],'version':info['version'],'mode':'official bundled session API files; no PNPM links','optional_standalone_cli_included':False,'existing_agent_cli_retained':True},indent=2),encoding='utf-8')
