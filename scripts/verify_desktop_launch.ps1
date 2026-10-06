[CmdletBinding(SupportsShouldProcess=$true,ConfirmImpact='High')]
param(
 [ValidateSet('exe','shortcut')][string]$Mode='exe',
 [Parameter(Mandatory=$true)][string]$TargetPath,
 [Parameter(Mandatory=$true)][string]$ExpectedResolvedTarget,
 [Parameter(Mandatory=$true)][string]$BuildManifest,
 [string]$Python='C:\Users\ryant\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
 [switch]$Execute
)
# SOURCE ONLY for this task. Never invoke with -Execute without new approval.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'launch_validation_helpers.ps1')
. (Join-Path $PSScriptRoot 'ascii_json_helpers.ps1')
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$target=[IO.Path]::GetFullPath($TargetPath)
$app=Split-Path -Parent $target
$data=Join-Path $root ('tests\desktop-'+$Mode+'-'+[guid]::NewGuid().ToString('N'))
$result=[ordered]@{observed_utc=[DateTime]::UtcNow.ToString('o');mode=$Mode;target=$target;
 resolved_target='UNKNOWN';expected_resolved_target=$ExpectedResolvedTarget;data_dir=$data;
 account=[Security.Principal.WindowsIdentity]::GetCurrent().Name;backend_connected='UNKNOWN';prod_data_used='UNKNOWN';
  window_visible='UNKNOWN';status='PLAN';executed=$false;retry_performed=$false;antivirus_clearance='NOT_ESTABLISHED';
  data_dir_argument_isolated='UNKNOWN';entrypoint_argument_matches='UNKNOWN';normal_close_requested=$false;normal_exit='UNKNOWN'}
$owned=$null;$ownedMeta=$null;$ownedConfirmed=$false;$snapshot=$null
try {
 $identityJson=& $Python -X utf8 -I (Join-Path $PSScriptRoot 'package_context.py')
 if ($LASTEXITCODE -ne 0) { throw 'Package identity diagnostic failed; no launch' }
 $result.package_identity=ConvertFrom-BoundedPlanJson -Text ($identityJson -join "`n")
 if ($result.package_identity.status -ne 'UNPACKAGED') { throw 'Packaged/UNKNOWN process identity; no launch' }
 if ($Mode -eq 'shortcut') { throw 'Shortcut target resolution in the intended human context is required; COM sandbox aliases are not authoritative. No launch performed.' }
 if (!(Test-Path -LiteralPath $target -PathType Leaf)) { throw 'Explicit target missing; never restore it' }
 $resolved=& $Python -X utf8 -I -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' $target
 if ($LASTEXITCODE -ne 0) { throw 'Target physical path could not be observed' }
 $result.resolved_target=($resolved -join '').Trim()
 if (![string]::Equals($result.resolved_target,$ExpectedResolvedTarget,[StringComparison]::OrdinalIgnoreCase)) { throw 'Target alias differs from explicitly expected physical path; no automatic reroute' }
 $build=Get-Content -LiteralPath $BuildManifest -Raw | ConvertFrom-Json
 if ($build.status -ne 'BUILT' -or !$build.output.sha256) { throw 'Successful build provenance required' }
 $result.target_sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
 if ($result.target_sha256 -ne $build.output.sha256) { throw 'Target differs from build output; do not launch' }
  if (!$Execute) { ConvertTo-StableAsciiJson -Value $result; return }
 if (!$PSCmdlet.ShouldProcess($target,'ONE approved isolated EXE launch; no retry or security changes')) { return }
 [IO.Directory]::CreateDirectory($data) | Out-Null
 $before=@(Get-Process -Name pythonw -ErrorAction SilentlyContinue | ForEach-Object {$_.Id})
 $info=New-Object Diagnostics.ProcessStartInfo
 $info.FileName=$target;$info.Arguments='--data-dir "'+$data+'"';$info.WorkingDirectory=$app;$info.UseShellExecute=$true
 $result.executed=$true
 $launcher=[Diagnostics.Process]::Start($info)
 $deadline=[DateTime]::UtcNow.AddSeconds(25);$owned=$null;$ownedMeta=$null
 while ([DateTime]::UtcNow -lt $deadline) {
  foreach ($candidate in @(Get-Process -Name pythonw -ErrorAction SilentlyContinue | Where-Object {$_.Id -notin $before})) {
   $meta=Get-CimInstance Win32_Process -Filter ('ProcessId='+$candidate.Id)
   if ($meta.CommandLine -like ('*'+$data+'*') -and $meta.CommandLine -like ('*'+$app+'\run.py*')) {
    $candidate.Refresh();if ($candidate.MainWindowHandle -ne 0) {$owned=$candidate;$ownedMeta=$meta;break}
   }
  }
  if ($owned) {break};Start-Sleep -Milliseconds 200
 }
 if (!$owned) { throw 'No observed isolated app window; do not close unrelated processes' }
 $owned.Refresh();$result.pythonw_pid=$owned.Id;$result.window_title=$owned.MainWindowTitle
 $result.window_visible=($owned.MainWindowTitle -like '*AI Collaboration Workspace*')
 # CIM command line is observed, not assumed. Exact argv decoding and backend
 # state assessment use a trusted read-only Python helper, never the application.
  $request=ConvertTo-StableAsciiJson -Value @{command_line=$ownedMeta.CommandLine;data_dir=$data;expected_script=(Join-Path $app 'run.py')}
  $snapshotJson=$request | & $Python -X utf8 -I (Join-Path $PSScriptRoot 'read_launch_snapshot.py')
 if ($LASTEXITCODE -ne 0) { throw 'Unable to verify child command-line/data scope; no PASS claimed' }
  $snapshot=ConvertFrom-BoundedPlanJson -Text ($snapshotJson -join "`n")
  $result.prod_data_used=$snapshot.prod_data_used;$result.backend_connected=$snapshot.backend_connected
  $result.data_dir_argument_isolated=$snapshot.data_dir_argument_isolated
  $result.entrypoint_argument_matches=$snapshot.entrypoint_argument_matches
  $result.observation_errors=@($snapshot.observation_errors)
  $ownedConfirmed=($snapshot.data_dir_argument_isolated -eq $true -and $snapshot.entrypoint_argument_matches -eq $true)
  $result.status='UNKNOWN'
} catch {
  $failure=Get-NativeLaunchFailure -Exception $_.Exception
  $result.status=if (!$result.executed) {'BLOCKED_PREFLIGHT'}else{$failure.status};$result.failure=$failure
} finally {
 if ($ownedConfirmed -and $null -ne $owned -and $null -ne $ownedMeta) {
  try {
   $currentMeta=Get-CimInstance Win32_Process -Filter ('ProcessId='+$owned.Id)
   if (Test-OwnedLaunchMetadata -Captured $ownedMeta -Current $currentMeta) {
    $owned.Refresh()
    if (!$owned.HasExited) {
     $result.normal_close_requested=$owned.CloseMainWindow()
     $result.normal_exit=$owned.WaitForExit(15000)
    } else { $result.normal_exit=$true }
   } else { $result.cleanup_ownership='UNKNOWN; identity changed/unavailable; no close or kill' }
  } catch { $result.cleanup_error=$_.Exception.Message }
 } elseif ($result.executed) { $result.cleanup_ownership='UNKNOWN; no confirmed owned process; no close or kill' }
}
if ($null -ne $snapshot -and !$result.Contains('failure') -and !$result.Contains('cleanup_error')) {
 $result.status=if ($result.window_visible -and $result.normal_close_requested -and $result.normal_exit -eq $true -and
     $result.data_dir_argument_isolated -eq $true -and $result.entrypoint_argument_matches -eq $true -and @($result.observation_errors).Count -eq 0) {
     'PASS launch/visible window/normal close scope; production data use UNKNOWN'
 } else {'UNKNOWN'}
}
if ($result.executed) {
  ConvertTo-StableAsciiJson -Value $result | Set-Content -LiteralPath (Join-Path $data 'launch-result.json') -Encoding UTF8
}
ConvertTo-StableAsciiJson -Value $result
