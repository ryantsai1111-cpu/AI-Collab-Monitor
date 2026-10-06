# Pure helpers. No filesystem/process/security operations.
function ConvertTo-StableAsciiJson {
    param([Parameter(Mandatory=$true)]$Value,[int]$Depth=12)
    $json=$Value | ConvertTo-Json -Depth $Depth
    [regex]::Replace($json,'[^\x00-\x7f]',[System.Text.RegularExpressions.MatchEvaluator]{
        param($match)
        '\u{0:x4}' -f [int][char]$match.Value
    })
}
function ConvertFrom-BoundedPlanJson {
    param([Parameter(Mandatory=$true)][string]$Text,[int]$MaxCharacters=1000000)
    if ($Text.Length -gt $MaxCharacters) { throw 'Plan JSON exceeds reviewed 1000000-character limit; no writes' }
    $Text | ConvertFrom-Json
}
