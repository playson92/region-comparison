param([switch]$Postgres, [string]$RunId)
. (Join-Path $PSScriptRoot 'common.ps1')
$identifier = New-RegionRun $RunId
$testTemp = Join-Path $projectRoot "output\tmp\pytest-$identifier"
$logs = Join-Path $projectRoot "output\codex_runs\$identifier\logs"
Push-Location -LiteralPath $projectRoot
try {
    New-Item -ItemType Directory -Path (Split-Path -Parent $testTemp) -Force | Out-Null
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    Start-Transcript -Path (Join-Path $logs 'check.txt') | Out-Null
    & $venvPython -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Ruff lint failed.' }
    & $venvPython -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw 'Ruff format failed.' }
    & $venvPython -m region_comparison validate
    if ($LASTEXITCODE -ne 0) { throw 'Snapshot validation failed.' }
    if ($Postgres) {
        if (-not $env:TEST_DATABASE_URL) { throw 'Set TEST_DATABASE_URL to a dedicated test database.' }
        & $venvPython -m pytest -m 'not live' --basetemp $testTemp --junitxml (Join-Path $logs 'pytest.xml')
    } else { & $venvPython -m pytest -m 'not postgres and not live' --basetemp $testTemp --junitxml (Join-Path $logs 'pytest.xml') }
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $venvPython (Join-Path $PSScriptRoot 'check-output-policy.py')
    if ($LASTEXITCODE -ne 0) { throw 'Output policy failed.' }
} finally { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null; Pop-Location }
