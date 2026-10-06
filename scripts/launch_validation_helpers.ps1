# Pure helpers only. No process/file/security mutations or top-level execution.
function Get-NativeLaunchFailure {
    param([Parameter(Mandatory=$true)][Exception]$Exception)
    $current=$Exception;$native=$null;$refusedException=$false
    while ($null -ne $current) {
        if (($current -is [UnauthorizedAccessException]) -or ($current -is [System.Management.Automation.PSSecurityException])) { $refusedException=$true }
        if ($current -is [ComponentModel.Win32Exception]) { $native=$current.NativeErrorCode;break }
        $current=$current.InnerException
    }
    $refused=($native -in @(5,225,226,740,1223,1260,1275)) -or
        $refusedException
    [ordered]@{status=if($refused){'BLOCKED'}else{'FAIL'};message=$Exception.Message;
        native_error_code=$native;hresult=$Exception.HResult;retry_performed=$false}
}

function ConvertTo-LauncherQuotedArgument {
    param([string]$Value,[hashtable]$Constants)
    # Executes the EXACT regex constants from reviewed Launcher.cs, not a second
    # quoting implementation. Tests use Windows CommandLineToArgvW as the oracle.
    $escaped=[regex]::Replace($Value,$Constants.QuotePattern,$Constants.QuoteReplacement)
    '"'+[regex]::Replace($escaped,$Constants.TrailingPattern,$Constants.TrailingReplacement)+'"'
}

function Test-OwnedLaunchMetadata {
    param($Captured,$Current)
    if ($null -eq $Captured -or $null -eq $Current) { return $false }
    ($Captured.ProcessId -eq $Current.ProcessId) -and
        ($null -ne $Captured.CreationDate) -and ($Captured.CreationDate -eq $Current.CreationDate) -and
        (![string]::IsNullOrEmpty($Captured.CommandLine)) -and
        ([string]::Equals($Captured.CommandLine,$Current.CommandLine,[StringComparison]::Ordinal))
}
