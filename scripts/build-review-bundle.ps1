param([string]$RunId, [string[]]$Evidence, [string]$Output)
. (Join-Path $PSScriptRoot 'common.ps1')
$identifier = New-RegionRun $RunId
Push-Location -LiteralPath $projectRoot
try {
    $arguments = @('-m','region_comparison','bundle','--run-id',$identifier)
    foreach ($file in $Evidence) { $arguments += @('--evidence',$file) }
    if ($Output) { $arguments += @('--output',$Output) }
    & $venvPython @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Review bundle creation failed.' }
} finally { Pop-Location }
