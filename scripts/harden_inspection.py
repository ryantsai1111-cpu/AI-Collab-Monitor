from pathlib import Path
p=Path('acw/inspection.py');s=p.read_text(encoding='utf-8-sig')
s=s.replace("run = subprocess.run([GIT, '--no-optional-locks', '-C', str(repo), *args],", "if any(x.startswith(('--output', '--exec-path', '--config-env')) or x in {'-D','-d','-m','-M','-c','-C','--delete','--force','--edit-description'} for x in args[1:]):\n        raise ValueError('Mutating git arguments are prohibited')\n    if args[0] == 'branch' and any(x not in {'--show-current','--list','-a','-r','--no-color'} for x in args[1:]):\n        raise ValueError('Only branch display is permitted')\n    run = subprocess.run([GIT, '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=NUL', '-C', str(repo), *args],")
p.write_text(s,encoding='utf-8')
