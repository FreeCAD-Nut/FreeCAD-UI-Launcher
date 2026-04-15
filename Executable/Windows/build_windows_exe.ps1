$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Resolve-Path (Join-Path $scriptDir '..\..')
$sourceDir = Join-Path $rootDir 'Python_App'
$workDir = Join-Path $scriptDir 'build_work'
$venvDir = Join-Path $workDir '.venv'
$distDir = Join-Path $workDir 'dist'
$buildDir = Join-Path $workDir 'build'
$specDir = Join-Path $workDir 'spec'
$outputExe = Join-Path $scriptDir 'UI_Launcher.exe'

New-Item -ItemType Directory -Force -Path $workDir | Out-Null
python -m venv $venvDir
$pythonExe = Join-Path $venvDir 'Scripts\python.exe'

& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install pyinstaller cryptography certifi

if (Test-Path $outputExe) {
    Remove-Item $outputExe -Force
}

& $pythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name UI_Launcher `
    --distpath $distDir `
    --workpath $buildDir `
    --specpath $specDir `
    --icon (Join-Path $sourceDir 'Default_Shortcut_Icons\Shortcut.ico') `
    --add-data ((Join-Path $sourceDir 'Default_Shortcut_Icons') + ';Default_Shortcut_Icons') `
    --add-data ((Join-Path $sourceDir 'CC_Licenses') + ';CC_Licenses') `
    (Join-Path $sourceDir 'UI_Launcher.py')

Copy-Item (Join-Path $distDir 'UI_Launcher.exe') $outputExe -Force
Write-Host "Built: $outputExe"
