param()
. (Join-Path $PSScriptRoot 'helpers\common.ps1')
$gate = $null
try {
    $gate = Enter-MonitorGate
    $sessions = @(Get-MonitorSessions)
    foreach ($session in $sessions) { Request-MonitorStop $session }
    # Keep the lifecycle gate until old readers stop, preventing a concurrent new start.
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $busy = @()
        foreach ($session in $sessions) {
            foreach ($actor in $script:MonitorActors) {
                if (Test-MonitorLeaseBusy $session $actor) { $busy += ((Split-Path -Leaf $session) + '/' + $actor) }
            }
        }
        if (-not $busy.Count) { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($busy.Count) { throw ('Readers did not release their leases. Manually close ONLY the AI-Collab-Monitor window, then run stop again. No process was killed. ' + ($busy -join ', ')) }
    Write-Output 'Monitor readers stopped; all monitor leases released. No process was killed.'
    Write-Output 'If Terminal keeps completed panes open, manually close ONLY the AI-Collab-Monitor window.'
} catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
} finally { if ($gate) { $gate.Dispose() } }
