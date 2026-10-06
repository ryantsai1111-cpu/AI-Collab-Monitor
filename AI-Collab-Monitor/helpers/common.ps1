Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:MonitorRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$script:MonitorActors = @('claude', 'dot', 'codex', 'timeline')
$script:MonitorState = Join-Path $script:MonitorRoot '.monitor'

function Assert-MonitorPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -ne $script:MonitorRoot -and -not $full.StartsWith($script:MonitorRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside this monitor: $full"
    }
    $cursor = $full
    while ($cursor.Length -ge $script:MonitorRoot.Length) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing linked/reparse monitor path: $cursor"
            }
        }
        if ($cursor -eq $script:MonitorRoot) { break }
        $cursor = Split-Path -Parent $cursor
    }
    return $full
}

function New-MonitorDirectory([string]$Path) {
    $full = Assert-MonitorPath $Path
    [void][IO.Directory]::CreateDirectory($full)
}

function New-MonitorEmptyFile([string]$Path) {
    $full = Assert-MonitorPath $Path
    if (Test-Path -LiteralPath $full) {
        if (-not [IO.File]::Exists($full)) { throw "Expected a file: $full" }
        return
    }
    $file = [IO.File]::Open($full, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $file.Dispose()
}

function Enter-MonitorGate {
    New-MonitorDirectory $script:MonitorState
    $path = Assert-MonitorPath (Join-Path $script:MonitorState 'lifecycle.lock')
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ($true) {
        try { return [IO.File]::Open($path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -ge $deadline) { throw 'Another monitor lifecycle operation is running. Try again after it finishes.' }
            Start-Sleep -Milliseconds 100
        }
    }
}

function Get-MonitorSessions {
    $dir = Assert-MonitorPath (Join-Path $script:MonitorState 'sessions')
    if (-not (Test-Path -LiteralPath $dir)) { return }
    foreach ($item in Get-ChildItem -LiteralPath $dir -Directory) {
        if ($item.Name -notmatch '^[a-f0-9]{32}$') { throw "Unrecognized session directory; inspect manually: $($item.FullName)" }
        [void](Assert-MonitorPath $item.FullName)
        $item.FullName
    }
}

function Test-MonitorLeaseBusy([string]$SessionPath, [string]$Actor) {
    $leasePath = Assert-MonitorPath (Join-Path $SessionPath ($Actor + '.lease'))
    if (-not (Test-Path -LiteralPath $leasePath)) { return $false }
    try {
        $probe = [IO.File]::Open($leasePath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $probe.Dispose()
        return $false
    }
    catch [IO.IOException] { return $true }
    # Permission/unknown errors are deliberately not treated as an inactive lease.
}

function Get-MonitorBlockers {
    foreach ($session in @(Get-MonitorSessions)) {
        if (-not (Test-Path -LiteralPath (Assert-MonitorPath (Join-Path $session 'stop.signal')))) {
            "Session $(Split-Path -Leaf $session) is running or pending."
        }
        foreach ($actor in $script:MonitorActors) {
            if (Test-MonitorLeaseBusy $session $actor) { "Active lease: $(Split-Path -Leaf $session)/$actor" }
        }
    }
}

function Request-MonitorStop([string]$SessionPath) {
    New-MonitorEmptyFile (Join-Path $SessionPath 'stop.signal')
}

function Write-MonitorJson([string]$Path, $Value) {
    $full = Assert-MonitorPath $Path
    [IO.File]::WriteAllText($full, ($Value | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
}

function Quote-MonitorArgument([string]$Value) {
    # Values are our fixed flags/titles/IDs or validated absolute paths, never a shell expression.
    if ($Value -match '["\r\n]' -or $Value.EndsWith('\')) { throw 'Unsupported character/trailing separator in command argument.' }
    return '"' + $Value + '"'
}
