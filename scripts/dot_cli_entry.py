"""Human UI launch only. Verify unchanged pinned source before CLI authentication."""
import argparse, hashlib, json, runpy, sys
from pathlib import Path

def main():
    # parse_known_args keeps a single literal message after --, including leading dashes.
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=('list','messages','send'))
    parser.add_argument('--dot-id',default='')
    parser.add_argument('--before',default='')
    args,tail=parser.parse_known_args()
    root=Path(__file__).resolve().parents[1];source=root/'tools'/'chatgpt-dot-cli-pinned'
    manifest=json.loads((root/'tools'/'dot-source-manifest.json').read_text(encoding='utf-8'))
    if manifest['commit']!='1413f7b61060eb582fd53a0210ef1a499d158fe0': raise RuntimeError('Unexpected source revision')
    for relative,expected in manifest['files'].items():
        if hashlib.sha256((source/relative).read_bytes()).hexdigest()!=expected: raise RuntimeError('Pinned source hash mismatch: '+relative)
    argv=['chatgpt-dot-cli','--json',args.operation]
    if args.operation!='list':
        if not args.dot_id: raise ValueError('Explicit selected Dot required')
        argv+=['--dot-id='+args.dot_id]
    if args.operation=='messages':
        argv+=['--limit','32']
        if args.before: argv+=['--before='+args.before]
    if args.operation=='send':
        if len(tail)!=2 or tail[0]!='--': raise ValueError('Exactly one unchanged text argument required')
        argv+=tail
    elif tail: raise ValueError('Unexpected arguments')
    # The pinned client waits 30 seconds; a slow send then fails although it may have been delivered.
    # Allow more time here without touching the pinned source.
    import urllib.request
    original=urllib.request.urlopen
    urllib.request.urlopen=lambda *a,**k: original(*a,**dict(k,timeout=max(k.get('timeout') or 0,90)))
    sys.path.insert(0,str(source));sys.argv=argv
    runpy.run_module('chatgpt_dot',run_name='__main__')

if __name__=='__main__': main()
