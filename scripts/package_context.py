"""Read-only process package identity API; no assembly loading or execution."""
import ctypes, os
NO_PACKAGE=15700
INSUFFICIENT_BUFFER=122

def interpret_identity(first_code,length=0,second_code=None,full_name=None):
    record={'status':'UNKNOWN','first_return_code':first_code,'second_return_code':second_code,
            'scope':'Process package identity only; not proof of absent filesystem virtualization'}
    if first_code==NO_PACKAGE:record['status']='UNPACKAGED'
    elif first_code==INSUFFICIENT_BUFFER and 0<length<=32768 and second_code==0 and full_name:
        record.update(status='PACKAGED',full_name=full_name)
    return record

def package_identity():
    if os.name!='nt':return {'status':'UNKNOWN','error':'Windows package identity API unavailable'}
    try:
        query=ctypes.WinDLL('kernel32',use_last_error=True).GetCurrentPackageFullName
        query.argtypes=[ctypes.POINTER(ctypes.c_uint32),ctypes.c_wchar_p];query.restype=ctypes.c_long
        length=ctypes.c_uint32(0);first=query(ctypes.byref(length),None)
        if first!=INSUFFICIENT_BUFFER or not 0<length.value<=32768:return interpret_identity(first,length.value)
        name=ctypes.create_unicode_buffer(length.value);second=query(ctypes.byref(length),name)
        return interpret_identity(first,length.value,second,name.value)
    except (OSError,AttributeError,ValueError) as error:
        return {'status':'UNKNOWN','error_type':type(error).__name__,'error':str(error)}

if __name__=='__main__':
    import json
    print(json.dumps(package_identity(),ensure_ascii=True))
