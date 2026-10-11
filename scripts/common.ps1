$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'

function New-RegionRun {
    param([string]$RunId)
    $oldPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $projectRoot 'src'
        $arguments = @('-c', 'import sys; from region_comparison.paths import run_id; print(run_id(sys.argv[1] if len(sys.argv)>1 else None))')
        if ($RunId) { $arguments += $RunId }
        $identifier = & $venvPython @arguments
        if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve run identifier.' }
        return $identifier.Trim()
    } finally { $env:PYTHONPATH = $oldPythonPath }
}
