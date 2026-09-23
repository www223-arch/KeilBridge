[CmdletBinding()]
param(
    [string]$OpenOcdExe = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $RepoRoot "dist\rtt-collector"
}
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$WorkPath = Join-Path $RepoRoot "build\pyinstaller-rtt-collector"
$Spec = Join-Path $RepoRoot "packaging\RTT-Collector.spec"

function Remove-OwnedDirectory([string]$Path, [string]$AllowedRoot) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullRoot = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\', '/')
    $prefix = $fullRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a directory outside the build root: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

if (-not $OpenOcdExe) {
    $OpenOcdExe = (& py -3 -X utf8 -c "from keiltool.core.tool_finder import find_openocd; print(find_openocd())").Trim()
}
$OpenOcdExe = [IO.Path]::GetFullPath($OpenOcdExe)
if (-not (Test-Path -LiteralPath $OpenOcdExe -PathType Leaf)) {
    throw "OpenOCD executable was not found: $OpenOcdExe"
}
$OpenOcdScripts = (& py -3 -X utf8 -c "from keiltool.core.tool_finder import find_openocd_scripts; print(find_openocd_scripts(r'$($OpenOcdExe.Replace("'", "''"))'))").Trim()
if (-not $OpenOcdScripts -or -not (Test-Path -LiteralPath $OpenOcdScripts -PathType Container)) {
    throw "OpenOCD scripts directory was not found for: $OpenOcdExe"
}

$DistRoot = Split-Path $OutputRoot -Parent
New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $WorkPath -Parent) -Force | Out-Null
Remove-OwnedDirectory $OutputRoot $DistRoot
Remove-OwnedDirectory $WorkPath (Split-Path $WorkPath -Parent)
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$env:KEILTOOL_BUILD_OPENOCD_EXE = $OpenOcdExe
$env:KEILTOOL_BUILD_OPENOCD_SCRIPTS = $OpenOcdScripts
try {
    & py -3 -m PyInstaller --noconfirm --clean --distpath $OutputRoot --workpath $WorkPath $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item Env:KEILTOOL_BUILD_OPENOCD_EXE -ErrorAction SilentlyContinue
    Remove-Item Env:KEILTOOL_BUILD_OPENOCD_SCRIPTS -ErrorAction SilentlyContinue
}

$Executable = Join-Path $OutputRoot "RTT-Collector.exe"
$SelfTest = Start-Process -FilePath $Executable -ArgumentList "--portable-self-test" -Wait -PassThru -WindowStyle Hidden
if ($SelfTest.ExitCode -ne 0) {
    throw "Portable self-test failed with exit code $($SelfTest.ExitCode)"
}

$Hash = Get-FileHash -LiteralPath $Executable -Algorithm SHA256
Write-Output "RTT collector: $Executable"
Write-Output "SHA-256:      $($Hash.Hash)"
