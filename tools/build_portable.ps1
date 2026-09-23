[CmdletBinding()]
param(
    [string]$OpenOcdExe = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $RepoRoot "dist"
}
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$Stage = Join-Path $OutputRoot "KeilTool-STLink"
$WorkPath = Join-Path $RepoRoot "build\pyinstaller-portable"
$Spec = Join-Path $RepoRoot "packaging\KeilTool-STLink.spec"

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

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $WorkPath -Parent) -Force | Out-Null
Remove-OwnedDirectory $Stage $OutputRoot
Remove-OwnedDirectory $WorkPath (Split-Path $WorkPath -Parent)

& py -3 -m PyInstaller --noconfirm --clean --distpath $OutputRoot --workpath $WorkPath $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$BundledBin = Join-Path $Stage "openocd\bin"
$BundledScripts = Join-Path $Stage "openocd\scripts"
New-Item -ItemType Directory -Path $BundledBin -Force | Out-Null
Copy-Item -LiteralPath $OpenOcdExe -Destination $BundledBin
foreach ($library in @("libusb-1.0.dll", "libftdi1.dll")) {
    $source = Join-Path (Split-Path $OpenOcdExe -Parent) $library
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination $BundledBin
    }
}
New-Item -ItemType Directory -Path $BundledScripts -Force | Out-Null
Copy-Item -Path (Join-Path $OpenOcdScripts "*") -Destination $BundledScripts -Recurse

$OpenOcdRoot = Split-Path (Split-Path $OpenOcdExe -Parent) -Parent
$DistroInfo = Join-Path $OpenOcdRoot "distro-info"
if (Test-Path -LiteralPath $DistroInfo -PathType Container) {
    Copy-Item -LiteralPath $DistroInfo -Destination (Join-Path $Stage "openocd\distro-info") -Recurse
}
$OpenOcdReadme = Join-Path $OpenOcdRoot "README.md"
if (Test-Path -LiteralPath $OpenOcdReadme -PathType Leaf) {
    Copy-Item -LiteralPath $OpenOcdReadme -Destination (Join-Path $Stage "openocd\README.md")
}

Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\PORTABLE_README.txt") -Destination (Join-Path $Stage "README.zh-CN.txt")
Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\ST-LINK-Driver-Official.url") -Destination $Stage
$UserManual = Get-ChildItem -LiteralPath (Join-Path $RepoRoot "docs") -Filter "01_KeilBridge_*.md" | Select-Object -First 1
if ($null -ne $UserManual) {
    Copy-Item -LiteralPath $UserManual.FullName -Destination (Join-Path $Stage "User-Manual.zh-CN.md")
}
$Licenses = Join-Path $Stage "licenses"
New-Item -ItemType Directory -Path $Licenses -Force | Out-Null
$PythonExe = (& py -3 -c "import sys; print(sys.executable)").Trim()
$PythonRoot = Split-Path $PythonExe -Parent
$PythonLicense = Join-Path $PythonRoot "LICENSE.txt"
if (Test-Path -LiteralPath $PythonLicense -PathType Leaf) {
    Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $Licenses "Python-LICENSE.txt")
}
$Commit = (& git -C $RepoRoot rev-parse --short HEAD).Trim()
$BuiltAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
@(
    "KeilTool portable build",
    "Commit: $Commit",
    "Built at: $BuiltAt",
    "OpenOCD: $OpenOcdExe"
) | Set-Content -LiteralPath (Join-Path $Stage "VERSION.txt") -Encoding utf8

$SelfTest = Start-Process -FilePath (Join-Path $Stage "KeilTool-STLink.exe") -ArgumentList "--portable-self-test" -Wait -PassThru -WindowStyle Hidden
if ($SelfTest.ExitCode -ne 0) {
    throw "Portable self-test failed with exit code $($SelfTest.ExitCode)"
}

$Stamp = Get-Date -Format "yyyyMMdd"
$ZipPath = Join-Path $OutputRoot "KeilTool-STLink-portable-$Stamp.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archiveCreated = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    try {
        [IO.Compression.ZipFile]::CreateFromDirectory(
            $Stage,
            $ZipPath,
            [IO.Compression.CompressionLevel]::Optimal,
            $true
        )
        $archiveCreated = $true
        break
    }
    catch {
        if ($attempt -eq 3) {
            throw
        }
        Start-Sleep -Seconds $attempt
    }
}

if (-not $archiveCreated) {
    throw "Portable archive was not created: $ZipPath"
}
$archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    $entries = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    foreach ($requiredEntry in @(
        "KeilTool-STLink/KeilTool-STLink.exe",
        "KeilTool-STLink/openocd/bin/openocd.EXE"
    )) {
        if ($requiredEntry -notin $entries) {
            throw "Portable archive is incomplete; missing: $requiredEntry"
        }
    }
    if (-not ($entries | Where-Object { $_ -like "KeilTool-STLink/openocd/scripts/target/*.cfg" })) {
        throw "Portable archive is incomplete; no OpenOCD target scripts were found."
    }
}
finally {
    $archive.Dispose()
}
$Hash = Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256
Write-Output "Portable directory: $Stage"
Write-Output "Portable archive:   $ZipPath"
Write-Output "SHA-256:            $($Hash.Hash)"
