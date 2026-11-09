param(
    [ValidateSet('start','status','stop')][string]$Action = 'start',
    [ValidateSet('demo','configured')][string]$Mode = 'demo'
)
$ErrorActionPreference = 'Stop'
$TaskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $TaskPython -PathType Leaf)) {
    throw 'Project .venv is missing. Install the project dependencies first.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $TaskPython tools/run_local.py $Action --mode $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Local server command failed. See .local-run logs.' }
}
finally { Pop-Location }
