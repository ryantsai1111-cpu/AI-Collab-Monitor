"""Read-only git inspection and incremental legacy monitor input."""
from pathlib import Path
import subprocess, codecs, re, time

GIT = r'C:\Program Files\Git\cmd\git.exe'

def git_read(repo, *args):
    if not Path(repo).is_dir(): raise ValueError('Project directory does not exist')
    if not args or args[0] not in {'status','diff','branch','log','rev-parse'}:
        raise ValueError('Only read-only git commands are permitted')
    options = args[1:args.index('--')] if '--' in args else args[1:]
    if any(x.startswith(('--output', '--exec-path', '--config-env')) or x in {'-D','-d','-m','-M','-c','-C','--delete','--force','--edit-description','--ext-diff','--textconv','--no-index'} for x in options):
        raise ValueError('Mutating git arguments are prohibited')
    if args[0] == 'branch' and any(x not in {'--show-current','--list','-a','-r','--no-color'} for x in args[1:]):
        raise ValueError('Only branch display is permitted')
    safe_args = list(args)
    if args[0] in {'diff', 'log'}:
        safe_args[1:1] = ['--no-ext-diff', '--no-textconv', '--no-color']
    run = subprocess.run([GIT, '--no-pager', '--no-optional-locks', '--literal-pathspecs',
                          '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=NUL',
                          '-C', str(repo), *safe_args],
                         capture_output=True, text=True, encoding='utf-8', errors='replace',
                         timeout=20, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {'command': 'git ' + subprocess.list2cmdline(safe_args), 'cwd': str(repo), 'stdout':run.stdout,
            'stderr':run.stderr,'exit_code':run.returncode}

def git_snapshot(repo):
    status = git_read(repo, 'status','--porcelain=v2','--branch')
    result = {'repo': str(repo), 'branch': '', 'dirty': False, 'ahead': None, 'behind': None,
              'upstream': None, 'has_upstream': False, 'divergence': 'unknown',
              'unborn': False, 'is_git': status['exit_code'] == 0,
              'status':status['stdout'], 'error':status['stderr'], 'status_result':status}
    for line in status['stdout'].splitlines():
        if line.startswith('# branch.head '): result['branch'] = line[14:]
        elif line == '# branch.oid (initial)': result['unborn'] = True
        elif line.startswith('# branch.upstream '):
            result.update(upstream=line[18:], has_upstream=True)
        elif line.startswith('# branch.ab '):
            match = re.search(r'\+(\d+) -(\d+)',line)
            if match: result.update(ahead=int(match[1]),behind=int(match[2]),divergence='known')
        elif line and not line.startswith('#'): result['dirty'] = True
    if result['is_git'] and not result['has_upstream']:
        result['divergence'] = 'no_upstream'
    return result

def git_diff(repo):
    """Return read-only patches plus native command results, including unborn HEAD.

    Without HEAD, staged additions and unstaged tracked edits are separate native
    patches (components); stdout concatenates them for a unified viewer. Untracked
    files are reported as a count and are never opened to manufacture a Git patch.
    """
    from .security import is_secret_path, safe_file
    state = git_snapshot(repo)
    untracked = sum(line.startswith('? ') for line in state['status'].splitlines())
    result = {'command':'', 'cwd':str(repo), 'stdout':'', 'stderr':'', 'exit_code':0,
              'changed_files':[], 'unborn':state['unborn'], 'scope':'worktree compared with HEAD',
              'notice':'', 'components':[], 'listing_results':[],
              'status_result':state['status_result'], 'untracked_count':untracked,
              'excluded_secret_paths':True, 'excluded_path_count':0}
    if not state['is_git']:
        result.update(state['status_result'])
        result['notice'] = 'Git status failed; no diff was generated.'
        return result
    modes = [('worktree compared with HEAD', ('HEAD',))]
    if state['unborn']:
        modes = [('staged additions', ('--cached',)), ('unstaged tracked edits', ())]
        result['scope'] = 'staged additions and unstaged tracked edits (unborn HEAD)'
        result['notice'] = ('Repository has no commits (unborn HEAD). Staged additions and '
                            'unstaged tracked edits are separate patches; untracked files '
                            'have no Git patch until staged.')
    elif untracked:
        result['notice'] = 'Untracked files are not included in the tracked Git patch.'
    for label, revisions in modes:
        # Disable rename detection so an allowed destination cannot pull in the
        # prior contents of an excluded credential path through a rename patch.
        listing = git_read(repo, 'diff', '--no-renames', '--name-only', '-z', *revisions, '--')
        result['listing_results'].append(listing)
        if listing['exit_code']:
            result['components'].append(dict(listing, scope=label))
            break
        allowed = []
        for name in listing['stdout'].split('\0'):
            if not name:
                continue
            try:
                if is_secret_path(name):
                    raise PermissionError('Credential path excluded')
                safe_file(Path(repo)/name, [repo], must_exist=False)
            except (ValueError, PermissionError):
                result['excluded_path_count'] += 1
                continue
            allowed.append(name)
            if name not in result['changed_files']:
                result['changed_files'].append(name)
        if allowed:
            component = git_read(repo, 'diff', '--no-renames', *revisions, '--', *allowed)
            result['components'].append(dict(component, scope=label))
    commands = result['components'] or result['listing_results']
    result['command'] = '\n'.join(item['command'] for item in commands)
    result['stdout'] = ''.join(item['stdout'] for item in result['components'] if not item['exit_code'])
    result['stderr'] = ''.join(item['stderr'] for item in commands)
    result['exit_code'] = next((item['exit_code'] for item in commands if item['exit_code']), 0)
    if result['excluded_path_count']:
        result['notice'] += (' ' if result['notice'] else '') + 'Credential or outside-project paths were excluded.'
    return result

def diff_sides(diff):
    left,right = [],[]
    for line in diff.splitlines():
        if line.startswith('-') and not line.startswith('---'): left.append(line[1:]);right.append('')
        elif line.startswith('+') and not line.startswith('+++'): left.append('');right.append(line[1:])
        else: left.append(line);right.append(line)
    return '\n'.join(left),'\n'.join(right)

def parse_test_result(command, output, exit_code=None, duration=None):
    framework = next((x for x in ('pytest','unittest','jest','vitest','cargo test','dotnet test') if x in command),'Unknown')
    result = {'command':command,'framework':framework,'passed':None,'failed':None,'skipped':None,
              'duration':duration,'exit_code':exit_code,'output':output}
    for label in ('passed','failed','skipped'):
        match = re.search(r'(\d+)\s+'+label,output,re.I)
        if match: result[label] = int(match[1])
    total = re.search(r'Ran (\d+) tests?',output)
    if total and re.search(r'^OK(?:\s|$)',output,re.M):
        result.update(passed=int(total[1]),failed=0)
    return result

class LegacyReader:
    """Read explicitly selected four log files only; never write/reset old Monitor."""
    def __init__(self, root, chunk_size=65536):
        self.root=Path(root); self.chunk_size=chunk_size; self.offsets={};self.decoders={}
    def poll(self):
        entries=[]
        for agent in ('claude','dot','codex','timeline'):
            path=self.root/'logs'/(agent+'.log')
            if not path.is_file() or path.is_symlink(): continue
            size=path.stat().st_size
            offset=self.offsets.get(agent,0)
            if size<offset:
                offset=0; self.decoders.pop(agent,None)
            with path.open('rb') as stream:
                stream.seek(offset); data=stream.read(self.chunk_size);self.offsets[agent]=stream.tell()
            if not data: continue
            decoder=self.decoders.setdefault(agent,codecs.getincrementaldecoder('utf-8')('replace'))
            content=decoder.decode(data)
            if content: entries.append({'agent':agent,'content':content,'source':str(path),'type':'legacy'})
        return entries
