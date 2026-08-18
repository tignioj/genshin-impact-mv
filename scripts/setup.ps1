$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "未找到 Node.js 22 或更高版本。"
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 Python 3.11 或更高版本。"
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "未找到 FFmpeg，请先安装并加入 PATH。"
}

npm install --ignore-scripts --no-audit --no-fund
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install -r "server\requirements.txt"

Write-Host "依赖安装完成。运行 .\scripts\start-dev.ps1 启动全部服务。" -ForegroundColor Green
