"""Read only the explicitly isolated owned launch's command line/database."""
import argparse,ctypes,json,os,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from launch_observation import assess

def windows_argv(command):
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    shell.CommandLineToArgvW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    count=ctypes.c_int();pointer=shell.CommandLineToArgvW(command,ctypes.byref(count))
    if not pointer:raise ctypes.WinError(ctypes.get_last_error())
    try:return [pointer[i] for i in range(count.value)]
    finally:kernel.LocalFree(pointer)

def snapshot(command,data,expected_script=None,decoder=windows_argv):
    states={};errors=[];args=None;isolated=Path(data).resolve()
    tests=Path(__file__).resolve().parents[1]/'tests'
    if not isolated.is_relative_to(tests.resolve()):raise ValueError('Only explicit isolated tests data can be inspected')
    try:args=decoder(command)
    except (OSError,ValueError) as error:errors.append({'component':'argv','error_type':type(error).__name__,'message':str(error)})
    db=isolated/'workspace.sqlite3';connection=None
    try:
        if db.is_file():
            connection=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
            for agent,payload in connection.execute("SELECT agent,payload FROM events WHERE type='state' ORDER BY timestamp"):
                body=json.loads(payload)
                if not isinstance(body,dict):raise ValueError('State payload is not an object')
                state=body.get('state') or body.get('status')
                if state in ('Connected','Busy'):states[agent]='Connected'
                elif agent not in states or states[agent]!='Connected':states[agent]=state
    except (sqlite3.Error,json.JSONDecodeError,ValueError,OSError) as error:
        states={};errors.append({'component':'sqlite_state','error_type':type(error).__name__,'message':str(error)})
    finally:
        if connection is not None:
            try:connection.close()
            except sqlite3.Error as error:errors.append({'component':'sqlite_close','error_type':type(error).__name__,'message':str(error)})
    result=assess({'observed_argv':args,'isolated_data_dir':str(isolated),'expected_script':expected_script,'observation_errors':errors,
                   'production_data_dir':str(Path(os.getenv('LOCALAPPDATA',''))/'AI-Collaboration-Workspace'/'data'),
                   'backend_states':states})
    result['observation_errors']=errors
    if errors:result['status']='UNKNOWN';result['backend_connected']='UNKNOWN'
    return result

def read_request(stream):
    raw=stream.read(1000001)
    if len(raw)>1000000:raise ValueError('Observation request exceeds reviewed size limit')
    request=json.loads(raw)
    if not isinstance(request,dict) or any(not isinstance(request.get(key),str) for key in ('command_line','data_dir','expected_script')):
        raise ValueError('Bounded JSON request requires command_line, data_dir and expected_script strings')
    return request

if __name__=='__main__':
    try:
        request=read_request(sys.stdin)
        result=snapshot(request['command_line'],request['data_dir'],request['expected_script'])
    except (ValueError,OSError) as error:
        result={'status':'UNKNOWN','prod_data_used':'UNKNOWN','backend_connected':'UNKNOWN',
                'data_dir_argument_isolated':'UNKNOWN','entrypoint_argument_matches':'UNKNOWN',
                'observation_errors':[{'component':'request','error_type':type(error).__name__,'message':str(error)}]}
    print(json.dumps(result,ensure_ascii=True))
