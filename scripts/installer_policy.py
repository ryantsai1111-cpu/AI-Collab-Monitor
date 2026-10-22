"""Read-only deployment planner and pure fail-closed policy; no writes/processes."""
import argparse, hashlib, json, os, ntpath, re, stat, sys
from pathlib import Path, PurePosixPath
sys.path.insert(0,str(Path(__file__).resolve().parent))
from package_context import package_identity

APP_NAME = 'AI-Collaboration-Workspace'
MAX_PLAN_CHARS=1000000
ROOTS=('acw','vendor','tools/chatgpt-dot-cli-pinned/chatgpt_dot','tools/claude-session-sdk/node_modules')
class PlanningBlocked(ValueError):
    def __init__(self,reason,diagnostics):
        super().__init__(reason);self.diagnostics=diagnostics
def valid_hash(value): return isinstance(value,str) and re.fullmatch('[0-9a-fA-F]{64}',value) is not None
SECRET_NAMES = {'auth.json','credentials.json','credentials','cookies','cookies.json','tokens.json',
                'token.json','password','passwords.json','.env','.netrc','.npmrc','.yarnrc','.pnpmrc',
                '.git','.aws','.ssh','.codex','id_rsa','id_ed25519'}
FIXED = {'run.py','README.md','requirements.txt','AI Collaboration Workspace.exe',
         'docs/USER_GUIDE.md','docs/TROUBLESHOOTING.md','docs/SECURITY.md',
         'scripts/dot_cli_entry.py','tools/dot-source-manifest.json',
         'tools/chatgpt-dot-cli-pinned/LICENSE','tools/chatgpt-dot-cli-pinned/pyproject.toml',
         'tools/chatgpt-dot-cli-pinned/README.md','tools/chatgpt-dot-cli-pinned/SECURITY.md',
         'tools/claude-session-sdk/session-helper.mjs','tools/claude-session-sdk/package.json'}

def allowed(relative):
    path=PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative or ':' in relative: return False
    if any(p.lower() in SECRET_NAMES or p.lower().startswith('.env.') for p in path.parts): return False
    if '__pycache__' in path.parts or path.suffix=='.pyc': return False
    if relative in FIXED: return True
    if path.parts[:1]==('acw',): return path.suffix=='.py'
    if path.parts[:2]==('tools','chatgpt-dot-cli-pinned'):
        return len(path.parts)>=4 and path.parts[2]=='chatgpt_dot' and path.suffix=='.py'
    if path.parts[:3]==('tools','claude-session-sdk','node_modules'): return True
    if path.parts[:1]==('vendor',) and len(path.parts)>2:
        return path.parts[1] in ('PySide6','shiboken6') or path.parts[1].startswith(('pyside6','shiboken6')) and path.parts[1].endswith('.dist-info')
    return False

def absolute_windows_path(value):
    drive,tail=ntpath.splitdrive(str(value or ''))
    return bool(drive and tail.startswith(('\\','/')))

def validate(snapshot):
    """Pure data policy; all rejection occurs before any executor writes."""
    if (snapshot.get('package_identity') or {}).get('status')!='UNPACKAGED':
        raise ValueError('Packaged or UNKNOWN process identity; no deployment')
    if snapshot.get('alias_consistency')!='MATCH':raise ValueError('Destination alias mismatch or UNKNOWN; no deployment')
    if snapshot.get('packaged_context') or snapshot.get('destination_alias_mismatch'):
        raise ValueError('Packaged/virtualized destination requires human migration; no automatic relocation')
    if not snapshot.get('destination_absolute') or snapshot.get('destination_name')!=APP_NAME:
        raise ValueError('Explicit absolute dedicated destination required')
    if snapshot.get('app_exists'):
        manifest=snapshot.get('existing_manifest')
        if not isinstance(manifest,dict) or manifest.get('schema')!=1 or manifest.get('app')!=APP_NAME:
            raise ValueError('Existing app has no verified installation manifest; manual migration required')
        if manifest.get('state')=='COMPLETED' and not snapshot.get('installed_exe_exists'):
            raise ValueError('Completed installation missing EXE: possible quarantine; never restore via ResumePartial')
        raise ValueError('Existing app/partial state requires manual review; automatic resume/overwrite disabled')
    if snapshot.get('resume_partial'): raise ValueError('ResumePartial disabled; fresh installation only')
    if snapshot.get('shortcut_conflicts'): raise ValueError('Shortcut conflict; no writes permitted')
    if not snapshot.get('python_absolute') or snapshot.get('python_name','').lower() not in ('python.exe','pythonw.exe') or not snapshot.get('python_exists'):
        raise ValueError('Existing absolute Python runtime required')
    if not snapshot.get('console_python_exists'): raise ValueError('Companion python.exe missing')
    build=snapshot.get('build_manifest') or {}
    if build.get('schema')!=1 or build.get('status')!='BUILT' or not valid_hash(build.get('compiler',{}).get('sha256')) or not build.get('command'):
        raise ValueError('Complete successful build provenance required; old binary not implicitly trusted')
    files=snapshot.get('files') or []
    if not files or len({r.get('path') for r in files})!=len(files): raise ValueError('Missing/duplicate deployment manifest entries')
    for row in files:
        if not allowed(row.get('path','')) or not valid_hash(row.get('sha256')):
            raise ValueError('Unsafe/incomplete deployment entry: '+str(row.get('path')))
    index={r['path']:r['sha256'] for r in files}
    excluded=snapshot.get('excluded')
    if not isinstance(excluded,list):raise ValueError('Explicit excluded-source record required')
    if any(row.get('necessity')!='GENERATED' for row in excluded):raise ValueError('Excluded dependency/resource necessity UNKNOWN; review required')
    inventories=snapshot.get('source_inventory') or []
    if len(inventories)!=len(ROOTS) or {row.get('root') for row in inventories}!=set(ROOTS):raise ValueError('Complete inventories required for every runtime root')
    for inventory in inventories:
        prefix=inventory['root']+'/'
        entries=inventory.get('entries')
        if inventory.get('enumeration_complete') is not True or inventory.get('reparse_checked') is not True or not isinstance(entries,list):raise ValueError('Runtime enumeration/reparse checks incomplete')
        if inventory.get('entry_count')!=len(entries) or not entries or len(entries)!=len(set(entries)) or any(not name.startswith(prefix) for name in entries):raise ValueError('Invalid/empty runtime inventory')
        included={name for name in index if name.startswith(prefix)}
        skipped={row['path'] for row in excluded if row.get('kind')=='file' and row.get('path','').startswith(prefix)}
        if set(entries)!=included|skipped or included&skipped:raise ValueError('Inventory and included/excluded files disagree: '+inventory['root'])
    required={'run.py','acw/__init__.py','acw/core.py','acw/store.py','acw/ui/__init__.py','acw/ui/main_window.py','acw/ui/widgets.py','scripts/dot_cli_entry.py','tools/dot-source-manifest.json',
              'tools/claude-session-sdk/session-helper.mjs','tools/claude-session-sdk/package.json',
              'tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/package.json',
              'vendor/PySide6/__init__.py','vendor/PySide6/QtCore.pyd','vendor/PySide6/QtGui.pyd','vendor/PySide6/QtWidgets.pyd',
              'vendor/shiboken6/__init__.py','vendor/shiboken6/Shiboken.pyd','tools/chatgpt-dot-cli-pinned/chatgpt_dot/__init__.py'}
    if not required.issubset(index): raise ValueError('Required runtime source missing')
    for package in ('pyside6','shiboken6'):
        if not any(name.startswith('vendor/'+package) and '.dist-info/' in name and name.endswith('/METADATA') for name in index):
            raise ValueError('Required vendor distribution metadata missing: '+package)
    sdk=snapshot.get('sdk_package') or {}
    targets=sdk.get('entrypoints')
    if sdk.get('name')!='@anthropic-ai/claude-agent-sdk' or sdk.get('version')!='0.3.289' or not isinstance(targets,list) or not targets:
        raise ValueError('Pinned SDK package entrypoint metadata UNKNOWN/missing')
    if any(not name.startswith('tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/') or name not in index for name in targets):
        raise ValueError('SDK declared entrypoint missing from full source inventory')
    if index.get('AI Collaboration Workspace.exe') != build.get('output',{}).get('sha256'):
        raise ValueError('Binary does not match successful build manifest')
    if not snapshot.get('build_sources_match'): raise ValueError('Build source hashes no longer match')
    return {'schema':1,'app':APP_NAME,'state':'PREFLIGHT_VERIFIED','files':files,
            'build':build,'paths':snapshot.get('paths',{}),'runtime':snapshot.get('runtime',{}),
            'package_identity':snapshot['package_identity'],'excluded':excluded,'source_inventory':inventories,'sdk_package':sdk,
            'warnings':['Local hashes record provenance, not a malware verdict or publisher trust.',
                        'Plan approval does not authorize deployment, compilation or EXE execution.',
                        'Eligible-file inventory is not runtime validation; package identity plus alias checks are not full virtualization coverage. Unknowns fail closed.']}

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def require_unlinked(path):
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
        raise ValueError('Linked/reparse source requires separate reviewed preparation: '+str(path))
    return info

def collect_root(source,prefix):
    files=[];excluded=[];entries=[]
    def visit(path):
        info=require_unlinked(path);relative=path.relative_to(source).as_posix();parts=PurePosixPath(relative).parts
        reason='generated_python_cache' if '__pycache__' in parts or path.suffix=='.pyc' else None
        if any(p.lower() in SECRET_NAMES or p.lower().startswith('.env.') for p in parts):reason='credential_or_configuration_name_not_read'
        if reason:
            if stat.S_ISREG(info.st_mode):entries.append(relative)
            excluded.append({'path':relative,'reason':reason,'necessity':'GENERATED' if reason=='generated_python_cache' else 'UNKNOWN',
                             'kind':'directory' if stat.S_ISDIR(info.st_mode) else 'file','content_read':False})
            return
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as children:names=sorted(entry.name for entry in children)
            for name in names:visit(path/name)
        elif stat.S_ISREG(info.st_mode):
            entries.append(relative)
            if len(entries)>50000:raise ValueError('Inventory exceeds reviewed entry limit')
            if allowed(relative):files.append({'path':relative,'source':str(path),'sha256':sha(path),'bytes':info.st_size})
            else:excluded.append({'path':relative,'reason':'unreviewed_resource_or_package','necessity':'UNKNOWN','kind':'file','content_read':False})
        else:raise ValueError('Non-regular dependency source: '+relative)
    try:
        for ancestor in (source/prefix).parents:
            if ancestor==source:break
            require_unlinked(ancestor)
        visit(source/prefix)
    except (OSError,ValueError) as error:
        raise PlanningBlocked(str(error),{'root':prefix,'enumeration_complete':False,'excluded':excluded,'observed_entries':entries,'error_type':type(error).__name__}) from error
    return files,excluded,{'root':prefix,'enumeration_complete':True,'reparse_checked':True,'entry_count':len(entries),'entries':entries}

def read_json(path):
    if path.stat().st_size>MAX_PLAN_CHARS:raise ValueError('Input manifest exceeds reviewed size limit')
    return json.loads(path.read_text(encoding='utf-8-sig'))

def encode_plan(record):
    text=json.dumps(record,ensure_ascii=True,indent=2)
    if len(text)>MAX_PLAN_CHARS:raise ValueError('Plan JSON exceeds reviewed 1000000-character limit; no writes')
    return text

def sdk_entrypoints(metadata):
    prefix='tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/'
    targets=[]
    def add(value):
        if isinstance(value,dict):
            for child in value.values():add(child)
        elif isinstance(value,str):
            relative=value.removeprefix('./')
            path=PurePosixPath(relative)
            if not relative or path.is_absolute() or '..' in path.parts or '*' in relative or '\\' in relative or ':' in relative:
                raise ValueError('SDK entrypoint metadata needs separate review')
            targets.append(prefix+relative)
        else:raise ValueError('SDK entrypoint metadata shape UNKNOWN')
    if 'exports' in metadata:add(metadata['exports'])
    elif 'main' in metadata:add(metadata['main'])
    else:raise ValueError('SDK entrypoint metadata UNKNOWN')
    return {'name':metadata.get('name'),'version':metadata.get('version'),'entrypoints':sorted(set(targets)),
            'scope':'Declared package exports/main paths only; no SDK execution/transitive-runtime certification'}

def inspect(source,destination,python,build_path,shortcuts,expected_resolved,resume=False):
    """Read only explicit sources/manifest and supplied target paths; never executes."""
    source=Path(source).resolve(); destination=Path(destination); interpreter=Path(python)
    provenance_path=Path(build_path).resolve()
    if not provenance_path.is_relative_to(source/'tests') or provenance_path.name!='launcher-build-manifest.json':
        raise ValueError('Only explicit isolated launcher-build-manifest.json provenance is read')
    if not absolute_windows_path(str(interpreter)) or interpreter.name.lower() not in ('python.exe','pythonw.exe'):
        raise ValueError('Refuse reading a non-Python runtime path')
    app=destination/'app'; exe=app/'AI Collaboration Workspace.exe'; manifest=app/'install-manifest.json'
    existing=read_json(manifest) if manifest.is_file() else None
    build=read_json(provenance_path) if provenance_path.is_file() else {}
    resolved=destination.resolve(); parts='/'.join(resolved.parts).casefold()
    snapshot=dict(package_identity=package_identity(),alias_consistency='MATCH' if os.path.normcase(str(resolved))==os.path.normcase(str(Path(expected_resolved))) else 'MISMATCH',
        excluded=[],source_inventory=[],destination_absolute=absolute_windows_path(str(destination)),destination_name=destination.name,
        destination_alias_mismatch=os.path.normcase(str(resolved))!=os.path.normcase(str(Path(expected_resolved))),
        packaged_context='/packages/' in parts and '/localcache/' in parts,
        app_exists=app.exists(),existing_manifest=existing,installed_exe_exists=exe.is_file(),resume_partial=resume,
        shortcut_conflicts=[p for p in shortcuts if Path(p).exists()],python_absolute=absolute_windows_path(str(interpreter)),
        python_name=interpreter.name,python_exists=interpreter.is_file(),console_python_exists=(interpreter.parent/'python.exe').is_file(),
        build_manifest=build,build_sources_match=False,files=[],paths={'logical_destination':str(destination),'resolved_destination':str(resolved),
            'expected_resolved_destination':str(expected_resolved),'app':str(app),'shortcuts':shortcuts},
        runtime={'path':str(interpreter),'identity_verified':'PATH/NAME/HASH ONLY; publisher/PE identity not established'})
    if snapshot['package_identity'].get('status')!='UNPACKAGED' or snapshot['app_exists'] or snapshot['packaged_context'] or snapshot['destination_alias_mismatch'] or snapshot['shortcut_conflicts']:
        try:validate(snapshot)
        except ValueError as error:raise PlanningBlocked(str(error),{'package_identity':snapshot['package_identity'],'paths':snapshot['paths']}) from error
    if interpreter.is_file(): snapshot['runtime']['sha256']=sha(interpreter)
    build_sources=build.get('sources',[])
    snapshot['build_sources_match']={r.get('path') for r in build_sources}=={'scripts/Launcher.cs','scripts/launcher.manifest'} and all(
        row.get('path') in ('scripts/Launcher.cs','scripts/launcher.manifest') and
        (source/row['path']).is_file() and sha(source/row['path'])==row.get('sha256') for row in build_sources)
    require_unlinked(source)
    candidates=[source/name for name in FIXED if name!='AI Collaboration Workspace.exe']
    for prefix in ROOTS:
        try:rows,excluded,inventory=collect_root(source,prefix)
        except PlanningBlocked as error:
            raise PlanningBlocked(str(error),{'package_identity':snapshot['package_identity'],'paths':snapshot['paths'],
                'excluded':snapshot['excluded'],'source_inventory':snapshot['source_inventory'],'failed_inventory':error.diagnostics}) from error
        snapshot['files'].extend(rows);snapshot['excluded'].extend(excluded);snapshot['source_inventory'].append(inventory)
    try:
        sdk_json=source/'tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/package.json'
        require_unlinked(sdk_json)
        snapshot['sdk_package']=sdk_entrypoints(read_json(sdk_json))
    except (OSError,ValueError) as error:
        raise PlanningBlocked(str(error),{'excluded':snapshot['excluded'],'source_inventory':snapshot['source_inventory'],'dependency_metadata_status':'UNKNOWN'}) from error
    output=Path(build.get('output',{}).get('path',''))
    if build.get('output',{}).get('path') and (not output.resolve().is_relative_to(source/'tests') or output.name!='AI Collaboration Workspace.exe'):
        raise ValueError('Only the approved isolated staged build output can be hashed; no arbitrary file reads')
    if output.is_file(): candidates.append(output)
    for path in sorted(set(candidates)):
        if not path.exists(): continue
        for ancestor in [path]+list(path.parents):
            if ancestor==source:break
            require_unlinked(ancestor)
        if not path.is_file():continue
        if path==output: relative='AI Collaboration Workspace.exe'
        else:
            if not path.resolve().is_relative_to(source): raise ValueError('Source escapes reviewed root')
            relative=path.relative_to(source).as_posix()
        if allowed(relative): snapshot['files'].append({'path':relative,'source':str(path),'sha256':sha(path),'bytes':path.stat().st_size})
    try:return validate(snapshot)
    except ValueError as error:raise PlanningBlocked(str(error),{'excluded':snapshot['excluded'],'source_inventory':snapshot['source_inventory'],'paths':snapshot['paths'],'package_identity':snapshot['package_identity']}) from error

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--destination',required=True)
    parser.add_argument('--python',required=True);parser.add_argument('--build-manifest',required=True)
    parser.add_argument('--expected-resolved',required=True);parser.add_argument('--shortcut',action='append',default=[])
    parser.add_argument('--resume-partial',action='store_true');args=parser.parse_args()
    try:
        print(encode_plan(inspect(args.source,args.destination,args.python,args.build_manifest,args.shortcut,args.expected_resolved,args.resume_partial)))
    except (ValueError,OSError,KeyError,TypeError) as error:
        record={'status':'BLOCKED_PREFLIGHT','reason':str(error),'writes':0,'diagnostics':getattr(error,'diagnostics',{})}
        try:print(encode_plan(record))
        except ValueError:print(json.dumps({'status':'BLOCKED_PREFLIGHT','reason':str(error),'diagnostics_truncated':True,'writes':0},ensure_ascii=True))
        raise SystemExit(2)
