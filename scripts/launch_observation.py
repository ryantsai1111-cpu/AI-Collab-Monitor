"""Pure launch-evidence assessment; no processes, remote calls or data mutation."""
import json,ntpath,sys

def key(path):return ntpath.normcase(ntpath.normpath(str(path or '')))

def assess(snapshot):
    result=dict(status='UNKNOWN',prod_data_used='UNKNOWN',backend_connected='UNKNOWN',data_dir_argument_isolated='UNKNOWN',entrypoint_argument_matches='UNKNOWN',
                scope='Observed isolated window/start/close only; not antivirus clearance')
    args=snapshot.get('observed_argv')
    if isinstance(args,list) and args.count('--data-dir')==1:
        index=args.index('--data-dir')
        if index+1<len(args):
            if key(args[index+1])==key(snapshot.get('isolated_data_dir')):
                result['data_dir_argument_isolated']=True
            elif key(args[index+1])==key(snapshot.get('production_data_dir')):
                result['data_dir_argument_isolated']=False
    if isinstance(args,list) and len(args)>1 and snapshot.get('expected_script'):
        result['entrypoint_argument_matches']=key(args[1])==key(snapshot['expected_script'])
    states=snapshot.get('backend_states')
    if isinstance(states,dict):
        if any(value in ('Connected','Busy') for value in states.values()):result['backend_connected']=True
        elif set(states)=={'claude','dot','codex'} and all(value in ('Disconnected','Offline','Blocked') for value in states.values()):result['backend_connected']=False
    if snapshot.get('failure'):
        result['status']=snapshot['failure']['status'];result['failure']=snapshot['failure'];return result
    window=snapshot.get('window_visible') is True
    closed=snapshot.get('normal_close_requested') is True and snapshot.get('normal_exit') is True
    matched=snapshot.get('target_matches_build') is True
    if window and closed and matched and result['data_dir_argument_isolated'] is True and not snapshot.get('observation_errors'):
        result['status']='PASS launch/visible window/normal close scope'
    else: result['status']='UNKNOWN' if not args else 'FAIL'
    return result

if __name__=='__main__':print(json.dumps(assess(json.load(sys.stdin)),ensure_ascii=True))
