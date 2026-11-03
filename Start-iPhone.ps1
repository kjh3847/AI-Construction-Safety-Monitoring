param(
    [string]$PythonPath = (Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Create backend/.venv or pass -PythonPath with your Python executable.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env.local'))) {
    throw 'Create .env.local with the camera stream URL on one line. See IPHONE-CAMERA.md.'
}
$env:CAMERA_SOURCE = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '.env.local') -Raw).Trim()
$env:CAMERA_NAME = 'CAM-01'
Set-Location $PSScriptRoot
& $PythonPath -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8002
