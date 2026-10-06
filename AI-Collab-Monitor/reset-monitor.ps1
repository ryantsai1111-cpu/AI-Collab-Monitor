param()
. (Join-Path $PSScriptRoot 'helpers\common.ps1')
$gate = $null
try {
    $gate = Enter-MonitorGate
    $blockers = @(Get-MonitorBlockers)
    if ($blockers.Count) { throw ('Reset refused: run stop-monitor.ps1 first and pause external log writers. ' + ($blockers -join ' ')) }
    $logs = Join-Path $script:MonitorRoot 'logs'
    $archive = Join-Path $script:MonitorRoot 'archive'
    New-MonitorDirectory $logs
    New-MonitorDirectory $archive
    foreach ($actor in $script:MonitorActors) { New-MonitorEmptyFile (Join-Path $logs ($actor + '.log')) }
    # Preflight all four logs before moving any. Unknown/open writer => fail safely.
    $probes = @()
    try {
        foreach ($actor in $script:MonitorActors) {
            $probes += [IO.File]::Open((Assert-MonitorPath (Join-Path $logs ($actor + '.log'))), [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        }
    } finally { foreach ($probe in $probes) { $probe.Dispose() } }
    $baseName = Get-Date -Format 'yyyyMMdd-HHmmss'
    $destination = Join-Path $archive $baseName
    $suffix = 0
    while (Test-Path -LiteralPath $destination) {
        $suffix++
        $destination = Join-Path $archive ($baseName + '-' + $suffix.ToString('D2'))
    }
    New-MonitorDirectory $destination
    # Move only the four explicit files; no recursive delete/move, no overwrite.
    foreach ($actor in $script:MonitorActors) {
        $source = Assert-MonitorPath (Join-Path $logs ($actor + '.log'))
        $dest = Assert-MonitorPath (Join-Path $destination ($actor + '.log'))
        [IO.File]::Move($source, $dest)
        New-MonitorEmptyFile $source
    }
    Write-Output "Archived logs: $destination"
    Write-Output 'Four empty UTF-8-ready logs created. tasks, earlier archives, README and scripts preserved.'
} catch {
    Write-Error -Message ($_.Exception.Message + ' No files are deleted. If an external writer raced reset, inspect logs/archive before retrying.') -ErrorAction Continue
    exit 1
} finally { if ($gate) { $gate.Dispose() } }
