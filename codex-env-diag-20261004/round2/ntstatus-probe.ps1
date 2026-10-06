# Read-only probe: try to open the target for FILE_READ_ATTRIBUTES only and report
# the Win32 error plus the underlying NTSTATUS (distinguishes STATUS_DELETE_PENDING
# 0xC0000056 from STATUS_ACCESS_DENIED 0xC0000022; both map to Win32 error 5).
param([Parameter(Mandatory)][string]$Target)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class NtProbe {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateFileW(string name, uint access, uint share, IntPtr sa, uint disp, uint flags, IntPtr tmpl);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("ntdll.dll")] static extern int RtlGetLastNtStatus();
    public static string Probe(string path, uint access) {
        IntPtr h = CreateFileW(path, access, 7, IntPtr.Zero, 3, 0, IntPtr.Zero);
        int win32 = Marshal.GetLastWin32Error();
        int nt = RtlGetLastNtStatus();
        if (h != new IntPtr(-1)) { CloseHandle(h); return "OPEN_OK"; }
        return String.Format("FAILED win32={0} ntstatus=0x{1:X8}", win32, nt);
    }
}
'@
"target: $Target"
"who: $(whoami)  elevated: " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
"time: $(Get-Date -Format o)"
"open FILE_READ_ATTRIBUTES (0x80):  " + [NtProbe]::Probe($Target, 0x80)
"open READ_CONTROL (0x20000):       " + [NtProbe]::Probe($Target, 0x20000)
"open zero access (0):              " + [NtProbe]::Probe($Target, 0)
"control - parent dir entry listing:"
Get-ChildItem -LiteralPath (Split-Path $Target -Parent) -Force | ForEach-Object { "  {0} len={1} mod={2}" -f $_.Name,$_.Length,$_.LastWriteTime.ToString('s') }
"legend: 0xC0000056=STATUS_DELETE_PENDING  0xC0000022=STATUS_ACCESS_DENIED  0xC0000034=OBJECT_NAME_NOT_FOUND"
