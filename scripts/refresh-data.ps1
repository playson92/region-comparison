param(
    [ValidateSet('refresh','resume','reuse')][string]$Mode = 'refresh',
    [string]$Destination,
    [string]$Snapshot
)
. (Join-Path $PSScriptRoot 'common.ps1')
Push-Location -LiteralPath $projectRoot
try {
    $arguments = @('-m','region_comparison','fetch','--mode',$Mode)
    if ($Destination) { $arguments += @('--output',$Destination) }
    if ($Mode -ne 'refresh' -and -not $Snapshot) { throw 'Resume/reuse require -Snapshot.' }
    if ($Snapshot) { $arguments += @('--snapshot',$Snapshot) }
    $result = & $venvPython @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Fetch incomplete. Check checkpoint; previous snapshot retained.' }
    $result | Write-Output
    $completed = ($result -join "`n") | ConvertFrom-Json
    & $venvPython -m region_comparison validate --snapshot $completed.snapshot
    if ($LASTEXITCODE -ne 0) { throw 'New snapshot validation failed; no activation performed.' }
} finally { Pop-Location }
