param([string]$Python = 'py')
. (Join-Path $PSScriptRoot 'common.ps1')
Push-Location -LiteralPath $projectRoot
try {
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($Python -eq 'py') { & $Python -3.12 -m venv .venv }
        else { & $Python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python 3.12 environment.' }
    }
    & $venvPython -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 required"'
    if ($LASTEXITCODE -ne 0) { throw 'The existing environment is not Python 3.12.' }
    & $venvPython -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $venvPython -m pip install -e . --no-deps --no-build-isolation
    if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
    & $venvPython -m region_comparison validate
    if ($LASTEXITCODE -ne 0) { throw 'Demo snapshot validation failed.' }
} finally { Pop-Location }
