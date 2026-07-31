<#
.SYNOPSIS
    Freeze the editor and compile the Windows installer.

.DESCRIPTION
    Runs PyInstaller over packaging\enc_editor.spec and hands the result to
    Inno Setup, which writes packaging\output\ENC-Inverter-Editor-<version>-Setup.exe.
    The version comes from enc_editor.VERSION, so it is never typed twice.

    Requirements: the project virtual environment with pyinstaller installed,
    and Inno Setup 6 (winget install JRSoftware.InnoSetup).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1

.EXAMPLE
    # Refresh the executable only, skipping the installer step.
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipInstaller
#>
[CmdletBinding()]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$packaging = $PSScriptRoot
$root = Split-Path $packaging -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "No virtual environment at $python - create it and pip install -r requirements.txt pyinstaller"
}

$version = & $python -c "import sys; sys.path.insert(0, r'$root'); import enc_editor; print(enc_editor.VERSION)"
if (-not $?) { throw "Could not read enc_editor.VERSION" }
Write-Host "Building $version" -ForegroundColor Cyan

# --- freeze -----------------------------------------------------------
& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $packaging "dist") `
    --workpath (Join-Path $packaging "build") `
    (Join-Path $packaging "enc_editor.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$executable = Join-Path $packaging "dist\ENC Inverter Editor\ENC Inverter Editor.exe"
if (-not (Test-Path $executable)) { throw "PyInstaller produced no executable" }

if ($SkipInstaller) {
    Write-Host "Executable: $executable" -ForegroundColor Green
    return
}

# --- installer --------------------------------------------------------
# winget puts Inno Setup under the user profile when it installs without
# elevation, so look there too before giving up.
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
}
if (-not $iscc) {
    throw "Inno Setup 6 not found - install it with: winget install JRSoftware.InnoSetup"
}

& $iscc "/DAppVersion=$version" (Join-Path $packaging "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }

$setup = Join-Path $packaging "output\ENC-Inverter-Editor-$version-Setup.exe"
$size = "{0:N1} MB" -f ((Get-Item $setup).Length / 1MB)
Write-Host "Installer: $setup ($size)" -ForegroundColor Green
