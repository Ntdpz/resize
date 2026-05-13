Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

py -3 -m PyInstaller --noconfirm --clean .\build\AutoWatermark.spec

Write-Host "Build completed. Output folder: $PSScriptRoot\dist\AutoWatermark" -ForegroundColor Green