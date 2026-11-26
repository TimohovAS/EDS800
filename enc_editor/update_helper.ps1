param(
    [Parameter(Mandatory = $true)][string]$RequestPath,
    [switch]$QuietErrors
)

$ErrorActionPreference = 'Stop'
$exitCode = 1
try {
    $request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    try { $parentProcess = [Diagnostics.Process]::GetProcessById([int]$request.parent_pid) }
    catch [ArgumentException] { $parentProcess = $null }
    if ($null -ne $parentProcess) {
        try {
            if (-not $parentProcess.WaitForExit(120000)) {
                throw 'ENC Inverter Editor did not exit.'
            }
        } finally { $parentProcess.Dispose() }
    }

    # Keep the verified file open for reading so it cannot be replaced before Setup opens it.
    $installer = Get-Item -LiteralPath $request.installer
    $stream = [IO.File]::OpenRead($installer.FullName)
    try {
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
        } finally { $sha256.Dispose() }
        if ($stream.Length -ne [long]$request.size -or $digest -cne $request.sha256) {
            throw 'Installer verification failed. Download the update again.'
        }

        # Start-Process accepts a Windows command line. Quote paths with spaces and trailing backslashes.
        $arguments = foreach ($argument in $request.arguments) {
            $value = [string]$argument
            '"' + [regex]::Replace([regex]::Replace($value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
        }
        $setup = Start-Process -FilePath $installer.FullName -ArgumentList ($arguments -join ' ') `
            -WorkingDirectory $installer.DirectoryName -WindowStyle Normal -Wait -PassThru
        $exitCode = $setup.ExitCode
        if ($exitCode -notin @(0, 2, 5)) {
            throw "The installer failed (exit code $exitCode)."
        }
    } finally { $stream.Dispose() }
} catch {
    $_.Exception.Message | Set-Content -LiteralPath ([IO.Path]::ChangeExtension($RequestPath, '.error.log')) -Encoding UTF8
    if (-not $QuietErrors) {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, 'ENC Inverter Editor', 'OK', 'Error')
    }
} finally {
    Remove-Item -LiteralPath $RequestPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
exit $exitCode
