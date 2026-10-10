param([switch]$Postgres)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$testTemp = Join-Path $projectRoot ('.local\pytest-' + [guid]::NewGuid().ToString('N'))
Push-Location -LiteralPath $projectRoot
try {
    New-Item -ItemType Directory -Path (Split-Path -Parent $testTemp) -Force | Out-Null
    & $venvPython -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Ruff lint failed.' }
    & $venvPython -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw 'Ruff format failed.' }
    & $venvPython -m region_comparison validate
    if ($LASTEXITCODE -ne 0) { throw 'Snapshot validation failed.' }
    if ($Postgres) {
        if (-not $env:TEST_DATABASE_URL) { throw 'Set TEST_DATABASE_URL to a dedicated test database.' }
        & $venvPython -m pytest --basetemp $testTemp
    } else { & $venvPython -m pytest -m 'not postgres and not live' --basetemp $testTemp }
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
} finally { Pop-Location }
