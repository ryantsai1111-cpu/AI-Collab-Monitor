$ErrorActionPreference='Stop'
$sourceRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$applicationRoot=[IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'AI-Collaboration-Workspace\app')).TrimEnd('\')
if ($applicationRoot -ne 'C:\Users\ryant\AppData\Local\AI-Collaboration-Workspace\app') { throw 'Unexpected installed app target; refusing writes' }
if (!(Test-Path -LiteralPath (Join-Path $applicationRoot 'acw\core.py'))) { throw 'Existing installed candidate not found' }
if ((Get-Item -LiteralPath $applicationRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installed app is a reparse point' }
$backupRoot=[IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA ('AI-Collaboration-Workspace\source-backups\'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssffffZ'))))
if (!$backupRoot.StartsWith('C:\Users\ryant\AppData\Local\AI-Collaboration-Workspace\source-backups\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected backup target' }
$files=@()
foreach ($directory in @('acw','docs','scripts')) {
 $files+=Get-ChildItem -LiteralPath (Join-Path $sourceRoot $directory) -Recurse -File | Where-Object { $_.Extension -in @('.py','.md') }
}
$files+=Get-ChildItem -LiteralPath (Join-Path $sourceRoot 'tests') -File -Filter 'test_*.py'
foreach ($name in @('g8-dot-contract-sample.json','g8-dot-observed.json')) {
 $fixture=Join-Path $sourceRoot ('tests\fixtures\'+$name)
 if (Test-Path -LiteralPath $fixture) { $files+=Get-Item -LiteralPath $fixture }
}
$dotRoot=Join-Path $sourceRoot 'tools\chatgpt-dot-cli-pinned'
$files+=Get-ChildItem -LiteralPath (Join-Path $dotRoot 'chatgpt_dot') -File -Filter '*.py'
foreach ($name in @('LICENSE','pyproject.toml','README.md','SECURITY.md')) { $files+=Get-Item -LiteralPath (Join-Path $dotRoot $name) }
$files+=Get-Item -LiteralPath (Join-Path $sourceRoot 'tools\dot-source-manifest.json')
foreach ($name in @('run.py','README.md','requirements.txt')) {$files+=Get-Item -LiteralPath (Join-Path $sourceRoot $name)}
$entries=@()
foreach ($file in $files) {
 $relative=$file.FullName.Substring($sourceRoot.Length+1)
 $target=[IO.Path]::GetFullPath((Join-Path $applicationRoot $relative))
 if (!$target.StartsWith($applicationRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or $file.Extension -eq '.exe') { throw 'Invalid source copy target' }
 $ancestor=Split-Path -Parent $target
 while ($ancestor.Length -ge $applicationRoot.Length) {
  if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Reparse ancestor in installed source path' }
  $ancestor=Split-Path -Parent $ancestor
 }
 $before=$null
 if (Test-Path -LiteralPath $target) {
  if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse source target' }
  $before=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
  $backup=Join-Path $backupRoot $relative
  New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
  Copy-Item -LiteralPath $target -Destination $backup
  if ((Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash -ne $before) { throw 'Backup hash mismatch' }
 }
 New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
 Copy-Item -LiteralPath $file.FullName -Destination $target -Force
 $after=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
 if ($after -ne (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash) { throw 'Installed source hash mismatch' }
 $entries+=@{path=$relative;previous_sha256=$before;installed_sha256=$after;previous_source_backed_up=($null -ne $before)}
}
$report=@{observed_utc=[DateTime]::UtcNow.ToString('o');status='PASS';target=$applicationRoot;backup=$backupRoot;files=$entries;user_data_accessed=$false;user_data_modified=$false;exe_copied_restored_rebuilt_executed=$false;installed_exe_exists=(Test-Path -LiteralPath (Join-Path $applicationRoot 'AI Collaboration Workspace.exe'));scope='Explicit Python/docs and pinned Dot stdlib source/license/provenance only. No .git, runtime test repos, DB, raw, settings, auth, credential, vendor, node_modules, shortcuts or EXE touched. No Dot CLI executed. Active sessions were not stopped or directed.'}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $sourceRoot 'evidence\installed-source-sync.json') -Encoding utf8
Write-Output ('Source synced: '+$entries.Count+' files. Backup: '+$backupRoot+'. EXE operations: none.')
