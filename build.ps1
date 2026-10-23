$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$mpvExe = Join-Path $PSScriptRoot "vendor\mpv\mpv.exe"

if (-not (Test-Path $python)) {
    Write-Host "创建虚拟环境..."
    py -m venv .venv
}

Write-Host "安装依赖..."
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r requirements.txt pyinstaller --quiet

if (-not (Test-Path $mpvExe)) {
    Write-Host "下载 mpv 播放器..."
    $release = Invoke-RestMethod `
        -Uri "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest" `
        -Headers @{ "User-Agent" = "huya-live-build" }
    $asset = $release.assets |
        Where-Object { $_.name -match "^mpv-x86_64-\d+.*\.7z$" } |
        Select-Object -First 1
    if (-not $asset) {
        throw "未找到可用的 mpv 下载地址"
    }

    $archive = Join-Path $env:TEMP "huya-mpv.7z"
    $extractDir = Join-Path $env:TEMP "huya-mpv-extract"
    Remove-Item $archive, $extractDir -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "下载 $($asset.name)..."
    curl.exe -L --retry 3 --retry-delay 2 -o $archive $asset.browser_download_url
    if ($LASTEXITCODE -ne 0) {
        throw "mpv 下载失败"
    }

    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
    tar.exe -xf $archive -C $extractDir
    if ($LASTEXITCODE -ne 0) {
        throw "mpv 解压失败，请安装 7-Zip 后重试"
    }

    New-Item -ItemType Directory -Path (Split-Path $mpvExe) -Force | Out-Null
    Copy-Item (Join-Path $extractDir "mpv.exe") $mpvExe -Force
    $d3d = Join-Path $extractDir "d3dcompiler_43.dll"
    if (Test-Path $d3d) {
        Copy-Item $d3d (Join-Path (Split-Path $mpvExe) "d3dcompiler_43.dll") -Force
    }
    Remove-Item $archive, $extractDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "打包应用..."
& $python -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name "HuyaLive" `
    --icon "assets\icon.ico" `
    --add-data "vendor\mpv\mpv.exe;mpv" `
    --add-data "vendor\mpv\d3dcompiler_43.dll;mpv" `
    --add-data "assets\icon.ico;assets" `
    --exclude-module "PySide6.QtQml" `
    --exclude-module "PySide6.QtQuick" `
    --exclude-module "PySide6.QtNetwork" `
    --exclude-module "PySide6.QtSql" `
    --exclude-module "PySide6.QtTest" `
    --exclude-module "PySide6.QtXml" `
    "app.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败"
}

Write-Host ""
Write-Host "打包完成: $PSScriptRoot\dist\HuyaLive.exe"
