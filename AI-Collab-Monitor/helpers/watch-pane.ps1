param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$SessionId,
    [Parameter(Mandatory=$true)][ValidateSet('claude','dot','codex','timeline')][string]$Actor
)
. (Join-Path $PSScriptRoot 'common.ps1')
$titles = @{
    claude = 'CLAUDE - PRIMARY REVIEWER'
    dot = 'DOT - SECONDARY REVIEW / RELAY'
    codex = 'CODEX - IMPLEMENTER'
    timeline = 'COLLABORATION TIMELINE'
}
$colors = @{ claude = 'Cyan'; dot = 'Yellow'; codex = 'Green'; timeline = 'Magenta' }
$sessionPath = Assert-MonitorPath (Join-Path (Join-Path $script:MonitorState 'sessions') $SessionId)
$logPath = Assert-MonitorPath (Join-Path (Join-Path $script:MonitorRoot 'logs') ($Actor + '.log'))
$stopPath = Join-Path $sessionPath 'stop.signal'
$gate = $null
$lease = $null
$logStream = $null
$exitCode = 0
try {
    $gate = Enter-MonitorGate
    # Stop/reset can happen while Terminal is still launching a delayed pane.
    if (-not (Test-Path -LiteralPath (Join-Path $sessionPath 'session.json')) -or (Test-Path -LiteralPath $stopPath)) { return }
    $lease = [IO.File]::Open((Assert-MonitorPath (Join-Path $sessionPath ($Actor + '.lease'))), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    # No Delete sharing: even an outside rename cannot silently strand the tail.
    $logStream = [IO.File]::Open($logPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    Write-MonitorJson (Join-Path $sessionPath ($Actor + '.started.json')) ([ordered]@{
        Actor=$Actor; Pid=$PID; StartedUtc=[DateTime]::UtcNow.ToString('o'); Log=$logPath; SessionId=$SessionId
    })
    $gate.Dispose()
    $gate = $null
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $Host.UI.RawUI.WindowTitle = 'AI-Collab-Monitor | ' + $titles[$Actor]
    Write-Host $titles[$Actor] -ForegroundColor $colors[$Actor]
    Write-Host ('logs\' + $Actor + '.log  |  v0.1  |  read only') -ForegroundColor DarkGray
    Write-Host ('=' * 42) -ForegroundColor DarkGray
    # Native .NET incremental UTF-8 reader. It can stop even when no lines arrive.
    # Decoder retains partial multibyte characters across separate appends.
    $encoding = [Text.UTF8Encoding]::new($false, $false)
    $decoder = $encoding.GetDecoder()
    $bytes = New-Object byte[] 8192
    $chars = New-Object char[] ($encoding.GetMaxCharCount($bytes.Length))
    while (-not (Test-Path -LiteralPath $stopPath)) {
        $count = $logStream.Read($bytes, 0, $bytes.Length)
        if ($count -gt 0) {
            $length = $decoder.GetChars($bytes, 0, $count, $chars, 0, $false)
            $text = [string]::new($chars, 0, $length)
            # Logs remain unchanged. Strip terminal control characters from display.
            $text = [regex]::Replace($text, '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\uFEFF]', '')
            [Console]::Write($text)
        } else {
            if ($logStream.Length -lt $logStream.Position) { throw 'The log was truncated externally. Stop the monitor before reset/rotation.' }
            Start-Sleep -Milliseconds 200
        }
    }
    Write-Host "`n[MONITOR STOPPED]" -ForegroundColor DarkGray
} catch {
    $exitCode = 1
    Write-Host ('[MONITOR ERROR] ' + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($logStream) { $logStream.Dispose() }
    if ($lease) { $lease.Dispose() }
    if ($gate) { $gate.Dispose() }
}
exit $exitCode
