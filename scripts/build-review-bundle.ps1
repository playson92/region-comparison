$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    & '.\.venv\Scripts\python.exe' -m region_comparison bundle --output REVIEW_BUNDLE.zip
    if ($LASTEXITCODE -ne 0) { throw 'Review bundle creation failed.' }
} finally { Pop-Location }
