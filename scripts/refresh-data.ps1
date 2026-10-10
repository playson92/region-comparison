param([string]$Destination = 'data/raw/latest')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    & '.\.venv\Scripts\python.exe' -m region_comparison fetch --output $Destination
    if ($LASTEXITCODE -ne 0) { throw 'Fetch incomplete. Check checkpoint; previous snapshot retained.' }
    & '.\.venv\Scripts\python.exe' -m region_comparison validate --snapshot $Destination
    if ($LASTEXITCODE -ne 0) { throw 'New snapshot validation failed; no activation performed.' }
} finally { Pop-Location }
