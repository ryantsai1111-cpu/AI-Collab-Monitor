param()
. (Join-Path $PSScriptRoot 'helpers\common.ps1')
$gate = $null
$sessionPath = $null
try {
    $wtCommand = Get-Command wt.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $wtCommand) { throw 'Windows Terminal (wt.exe) was not found. No software or PATH was changed.' }
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $shell)) { throw 'Windows PowerShell 5.1 was not found.' }
    if ($script:MonitorRoot.Contains(';')) { throw 'A semicolon in the monitor path is unsupported by the Windows Terminal command separator. Use a path without semicolons.' }
    $gate = Enter-MonitorGate
    $blockers = @(Get-MonitorBlockers)
    if ($blockers.Count) { throw ('Monitor already running/pending. Run stop-monitor.ps1 first. ' + ($blockers -join ' ')) }
    foreach ($dir in @('logs','archive','tasks')) { New-MonitorDirectory (Join-Path $script:MonitorRoot $dir) }
    foreach ($actor in $script:MonitorActors) { New-MonitorEmptyFile (Join-Path (Join-Path $script:MonitorRoot 'logs') ($actor + '.log')) }
    $sessionId = [Guid]::NewGuid().ToString('N')
    $sessionPath = Join-Path (Join-Path $script:MonitorState 'sessions') $sessionId
    New-MonitorDirectory $sessionPath
    $titleMap = @{
        claude = 'CLAUDE - PRIMARY REVIEWER'; dot = 'DOT - SECONDARY REVIEW / RELAY'
        codex = 'CODEX - IMPLEMENTER'; timeline = 'COLLABORATION TIMELINE'
    }
    function Get-PaneCommand([string]$Actor) {
        $parts = @('--title', ('AI-Collab-Monitor | ' + $titleMap[$Actor]), '--suppressApplicationTitle', '-d', $script:MonitorRoot,
            $shell, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'helpers\watch-pane.ps1'),
            '-SessionId', $sessionId, '-Actor', $Actor)
        return (($parts | ForEach-Object { Quote-MonitorArgument $_ }) -join ' ')
    }
    # Verified against Ryan-PC wt 1.24.12741.0 local help; always uses ONE fresh window.
    $commandLine = '-w new --maximized new-tab ' + (Get-PaneCommand 'claude') +
        ' ; split-pane -H --size 0.30 ' + (Get-PaneCommand 'timeline') +
        ' ; move-focus up ; split-pane -V --size 0.6667 ' + (Get-PaneCommand 'dot') +
        ' ; split-pane -V --size 0.5 ' + (Get-PaneCommand 'codex') + ' ; move-focus first'
    Write-MonitorJson (Join-Path $sessionPath 'session.json') ([ordered]@{
        Version='0.1'; SessionId=$sessionId; CreatedUtc=[DateTime]::UtcNow.ToString('o'); Root=$script:MonitorRoot
        Layout='Top: Claude | Dot | Codex. Bottom: Timeline (30%).'; WindowsTerminal=$wtCommand.Source
        CommandLine=$commandLine
    })
    $gate.Dispose()
    $gate = $null
    # This is the explicitly requested visible interactive monitor window.
    $launcher = Start-Process -FilePath $wtCommand.Source -ArgumentList $commandLine -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        if (Test-Path -LiteralPath (Join-Path $sessionPath 'stop.signal')) { throw 'Startup was cancelled by stop-monitor.ps1.' }
        $ready = @($script:MonitorActors | Where-Object { Test-Path -LiteralPath (Join-Path $sessionPath ($_ + '.started.json')) })
        if ($ready.Count -eq 4) { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($ready.Count -ne 4) { throw "Only $($ready.Count)/4 panes started. Stop requested. Inspect this monitor window and local wt --help; do not retry blindly." }
    $gate = Enter-MonitorGate
    if (Test-Path -LiteralPath (Join-Path $sessionPath 'stop.signal')) { throw 'Startup was cancelled.' }
    foreach ($actor in $script:MonitorActors) {
        if (-not (Test-MonitorLeaseBusy $sessionPath $actor)) { throw "Pane exited during startup: $actor" }
    }
    Write-Output "AI-Collab-Monitor v0.1 started: $sessionId"
    Write-Output 'Single window: CLAUDE | DOT | CODEX above full-width TIMELINE.'
    Write-Output 'All four reader leases are active. UI visibility must be checked separately.'
} catch {
    if ($gate) { $gate.Dispose(); $gate = $null }
    if ($sessionPath -and (Test-Path -LiteralPath $sessionPath)) {
        $cancelGate = Enter-MonitorGate
        try { Request-MonitorStop $sessionPath } finally { $cancelGate.Dispose() }
    }
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
} finally {
    if ($gate) { $gate.Dispose() }
}
