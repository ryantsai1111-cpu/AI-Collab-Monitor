# Elevated READ-ONLY query. Finds processes holding a handle to / mapping the fault target.
# Uses Sysinternals handle64.exe in search mode only (never -c / close).
# Output: only rows matching the target fragment. No command lines are recorded.
$ErrorActionPreference = 'Continue'
$r      = Split-Path -Parent $MyInvocation.MyCommand.Path
$out    = Join-Path $r 'elevated-query-output.txt'
$frag   = '81ea4d5168ddd0a3'
$target = "C:\Users\ryant\AppData\Local\OpenAI\Codex\runtimes\cua_node\$frag\bin\node_repl.exe"
$handle = Join-Path $r 'sysinternals-handle\handle64.exe'

function W($s) { $s | Out-File -LiteralPath $out -Append -Encoding utf8 }
if (Test-Path -LiteralPath $out) { exit 3 }   # never overwrite

W "time: $(Get-Date -Format o)"
W "who: $(whoami)  elevated: $(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))"
W "target: $target"

W "`r`n=== 1. NTSTATUS probe as elevated ==="
W (& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $r 'ntstatus-probe.ps1') -Target $target | Out-String)

W "=== 2. handle64 search (query only): -a -u $frag ==="
$sig = Get-AuthenticodeSignature -LiteralPath $handle
W "handle64 signature: $($sig.Status) / $($sig.SignerCertificate.Subject)"
$pids = @()
if ($sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -match 'O=Microsoft Corporation') {
    $h = & $handle -accepteula -nobanner -a -u $frag 2>&1
    W "handle64 exit=$LASTEXITCODE"
    W ($h | Out-String)
    foreach ($line in $h) { if ("$line" -match 'pid:\s*(\d+)') { $pids += [int]$Matches[1] } }
} else { W "SKIPPED: signature not valid" }

W "=== 3. loaded-module / image scan across all processes for $frag ==="
$all = Get-CimInstance Win32_Process
$hit = $false
foreach ($p in Get-Process) {
    try { foreach ($m in $p.Modules) { if ($m.FileName -match $frag) { W "module: pid=$($p.Id) $($p.ProcessName) -> $($m.FileName)"; $pids += $p.Id; $hit = $true } } } catch {}
}
foreach ($c in $all) { if ($c.ExecutablePath -match $frag) { W "image: pid=$($c.ProcessId) $($c.Name) -> $($c.ExecutablePath)"; $pids += [int]$c.ProcessId; $hit = $true } }
if (-not $hit) { W "no module/image match" }

W "`r`n=== 4. details for matching PIDs ==="
$pids = $pids | Sort-Object -Unique
if (-not $pids) { W "no matching PIDs" }
foreach ($id in $pids) {
    $c = $all | Where-Object ProcessId -eq $id
    if (-not $c) { W "pid=$id : process no longer present / unknown"; continue }
    $own = try { $o = Invoke-CimMethod -InputObject $c -MethodName GetOwner; if ($o.User) { "$($o.Domain)\$($o.User)" } else { 'unknown' } } catch { 'unknown' }
    $par = $all | Where-Object ProcessId -eq $c.ParentProcessId
    $parName = if ($par) { $par.Name } else { 'unknown (exited)' }
    $path = if ($c.ExecutablePath) { $c.ExecutablePath } else { 'unknown' }
    W ("pid={0} name={1}`r`n   path={2}`r`n   user={3}`r`n   parent pid={4} ({5})`r`n   started={6}" -f $id,$c.Name,$path,$own,$c.ParentProcessId,$parName,$c.CreationDate.ToString('s'))
}
W "`r`n=== done $(Get-Date -Format o) ==="
