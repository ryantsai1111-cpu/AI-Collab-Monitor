"""Close ONLY a named dialog belonging to this known test process; never kill."""
import argparse,ctypes
from ctypes import wintypes
p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--title',required=True);a=p.parse_args()
user=ctypes.windll.user32;closed=[]
callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
def visit(hwnd,param):
 pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
 if pid.value!=a.pid:return True
 text=ctypes.create_unicode_buffer(512);user.GetWindowTextW(hwnd,text,512)
 if text.value==a.title:
  user.PostMessageW(hwnd,0x0010,0,0);closed.append(text.value)
 return True
callback=callback_type(visit);user.EnumWindows(callback,0);print({'test_pid':a.pid,'WM_CLOSE_sent':closed,'process_killed':False})
