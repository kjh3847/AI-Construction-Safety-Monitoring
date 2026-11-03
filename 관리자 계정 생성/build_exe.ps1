param([string]$Name = 'SafetyAccountAdmin-cloud', [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonExe = $PythonPath
if (-not $pythonExe) {
    $pythonExe = Join-Path $projectRoot '.venv-accounts\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = Join-Path $projectRoot 'AI-Construction-Safety-Monitoring-main\.venv-accounts\Scripts\python.exe'
    }
}
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Project Python environment not found.' }
$policyFile = & $pythonExe -c "import ssl,pathlib; print(pathlib.Path(ssl.__file__).with_name('codex-rejected-cas.pem'))"
$sslArguments = @()
if (Test-Path -LiteralPath $policyFile) {
    $sslArguments = @('--add-data', "$policyFile;.", '--runtime-hook', (Join-Path $PSScriptRoot 'frozen_ssl_hook.py'))
}
& $pythonExe -m PyInstaller --noconfirm --onefile --windowed --noupx --collect-data certifi @sslArguments --name $Name --distpath (Join-Path $PSScriptRoot 'dist') --workpath (Join-Path $PSScriptRoot 'build') --specpath $PSScriptRoot (Join-Path $PSScriptRoot 'main.py')
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
Write-Host (Join-Path $PSScriptRoot "dist\$Name.exe")
