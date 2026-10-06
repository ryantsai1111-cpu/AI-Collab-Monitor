[CmdletBinding(SupportsShouldProcess=$true,ConfirmImpact='High')]
param([Parameter(Mandatory=$true)][string]$OutputDirectory,[switch]$Execute)
# SOURCE ONLY in the current authorized task: do not invoke this script now.
# Default produces a read-only plan. Future -Execute needs separate approval.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'ascii_json_helpers.ps1')
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$outputRoot=[IO.Path]::GetFullPath($OutputDirectory)
$allowedRoot=[IO.Path]::GetFullPath((Join-Path $root 'tests'))+'\'
if (!$outputRoot.StartsWith($allowedRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must be a new isolated directory under tests' }
if (Test-Path -LiteralPath $outputRoot) { throw 'Build output already exists; never overwrite/rebuild in place' }
$compiler=Join-Path ([Environment]::GetFolderPath('Windows')) 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (!(Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'Existing compiler unavailable; no tool installation' }
$launcherSource=Join-Path $root 'scripts\Launcher.cs'
$appManifest=Join-Path $root 'scripts\launcher.manifest'
$binary=Join-Path $outputRoot 'AI Collaboration Workspace.exe'
$compilerSignature=Get-AuthenticodeSignature -LiteralPath $compiler
if ($compilerSignature.Status -ne 'Valid') { throw 'Existing compiler signature is not Valid; no compilation' }
$sources=@()
foreach ($entry in @(@('scripts/Launcher.cs',$launcherSource),@('scripts/launcher.manifest',$appManifest))) {
    $sources+=@{path=$entry[0];sha256=(Get-FileHash -LiteralPath $entry[1] -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$compileArgs=@('/nologo','/noconfig','/target:winexe',('/out:'+$binary),('/win32manifest:'+$appManifest),
    '/reference:System.dll','/reference:System.Windows.Forms.dll',$launcherSource)
$record=[ordered]@{schema=1;status='PLAN';created_utc=[DateTime]::UtcNow.ToString('o');sources=$sources;
    compiler=@{path=$compiler;sha256=(Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant();signature_status=[string]$compilerSignature.Status};
    command=@($compiler)+$compileArgs;stdout=$null;stderr=$null;exit_code=$null;
    deterministic_verified='NOT_VERIFIED';publisher_trust='NOT_ESTABLISHED';
    output=@{path=$binary;sha256=$null;bytes=$null;signature_status='UNKNOWN'};
    scope='Build provenance only; not a malware verdict or EXE acceptance';executed=$false;
    invocation_attempted=$false;process_started=$false;default_response_file='DISABLED /noconfig';native_failure=$null}
if (!$Execute) { ConvertTo-StableAsciiJson -Value $record; return }
if (!$PSCmdlet.ShouldProcess($outputRoot,'ONE separately approved compiler invocation; never run output EXE')) { return }
# No retry. Original/source/installed binaries are never targeted.
[IO.Directory]::CreateDirectory($outputRoot) | Out-Null
$stdoutPath=Join-Path $outputRoot 'compiler.stdout.txt';$stderrPath=Join-Path $outputRoot 'compiler.stderr.txt'
$compilerProcess=$null;$stdoutTask=$null;$stderrTask=$null
try {
    $startInfo=New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName=$compiler
    # Controlled file/option paths cannot contain quote characters or trailing
    # backslashes; quote each complete option to preserve spaces.
    if (@($compileArgs | Where-Object { $_.Contains('"') -or $_.EndsWith('\') }).Count) { throw 'Unsupported compiler argument shape; no invocation' }
    $startInfo.Arguments=(@($compileArgs | ForEach-Object {'"'+$_+'"'}) -join ' ')
    $startInfo.UseShellExecute=$false;$startInfo.CreateNoWindow=$true
    $startInfo.RedirectStandardOutput=$true;$startInfo.RedirectStandardError=$true
    $record.invocation_attempted=$true;$record.attempt_started_utc=[DateTime]::UtcNow.ToString('o')
    $compilerProcess=[Diagnostics.Process]::Start($startInfo)
    if ($null -eq $compilerProcess) { throw 'Compiler process was not returned' }
    $record.executed=$true;$record.process_started=$true
    $stdoutTask=$compilerProcess.StandardOutput.ReadToEndAsync();$stderrTask=$compilerProcess.StandardError.ReadToEndAsync()
    $compilerProcess.WaitForExit();$record.exit_code=$compilerProcess.ExitCode
    $record.stdout=$stdoutTask.Result;$record.stderr=$stderrTask.Result
    if ($record.exit_code -ne 0 -or !(Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'Compile did not produce a verified output; stop without retry' }
    $record.output.sha256=(Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
    $record.output.bytes=(Get-Item -LiteralPath $binary).Length
    $record.output.signature_status=[string](Get-AuthenticodeSignature -LiteralPath $binary).Status
    $record.status='BUILT'
} catch {
    $record.status='BLOCKED';$record.error=$_.Exception.Message
    $current=$_.Exception;$native=$null
    while ($null -ne $current) { if ($current -is [ComponentModel.Win32Exception]) {$native=$current.NativeErrorCode;break};$current=$current.InnerException }
    $record.native_failure=@{type=$_.Exception.GetType().FullName;hresult=$_.Exception.HResult;native_error_code=$native;message=$_.Exception.Message}
} finally {
    if ($null -ne $stdoutTask -and $stdoutTask.IsCompleted -and !$stdoutTask.IsFaulted) {$record.stdout=$stdoutTask.Result}
    if ($null -ne $stderrTask -and $stderrTask.IsCompleted -and !$stderrTask.IsFaulted) {$record.stderr=$stderrTask.Result}
    if ($null -ne $record.stdout) {[IO.File]::WriteAllText($stdoutPath,[string]$record.stdout)}
    if ($null -ne $record.stderr) {[IO.File]::WriteAllText($stderrPath,[string]$record.stderr)}
    ConvertTo-StableAsciiJson -Value $record | Set-Content -LiteralPath (Join-Path $outputRoot 'launcher-build-manifest.json') -Encoding UTF8
    if ($null -ne $compilerProcess) {$compilerProcess.Dispose()}
}
ConvertTo-StableAsciiJson -Value $record
if ($record.status -ne 'BUILT') { throw 'Build blocked; do not retry or execute output' }
