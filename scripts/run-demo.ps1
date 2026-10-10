param([int]$Port = 8503)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run scripts/bootstrap.ps1 first.' }
Push-Location -LiteralPath $projectRoot
$oldMode = $env:REGION_DATA_MODE
try {
    $env:REGION_DATA_MODE = 'snapshot'
    & $venvPython -m streamlit run app.py --server.port $Port --server.headless true --server.address 127.0.0.1
    if ($LASTEXITCODE -ne 0) { throw 'Streamlit exited with an error.' }
} finally { $env:REGION_DATA_MODE = $oldMode; Pop-Location }
