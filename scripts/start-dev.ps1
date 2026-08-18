param(
    [string]$WikiPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $WikiPath) {
    $WikiPath = Join-Path $projectRoot "..\bilibili-download\gi-wiki"
}
$resolvedWiki = (Resolve-Path -LiteralPath $WikiPath -ErrorAction Stop).Path
$wikiApp = Join-Path $resolvedWiki "app.py"
$apiPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $wikiApp -PathType Leaf)) {
    throw "未找到 GI Wiki 服务：$wikiApp"
}
if (-not (Test-Path -LiteralPath $apiPython -PathType Leaf)) {
    throw "后端环境尚未安装，请先运行 .\scripts\setup.ps1"
}

$wikiProcess = $null
$apiProcess = $null
try {
    $wikiProcess = Start-Process -FilePath "python" -ArgumentList @("app.py") -WorkingDirectory $resolvedWiki -WindowStyle Hidden -PassThru
    $apiProcess = Start-Process -FilePath $apiPython -ArgumentList @("-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8787") -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 900

    Write-Host "GI Wiki: http://127.0.0.1:8765" -ForegroundColor DarkGray
    Write-Host "合成 API: http://127.0.0.1:8787/docs" -ForegroundColor DarkGray
    Write-Host "Web 界面即将在 http://localhost:3000 启动；按 Ctrl+C 停止。" -ForegroundColor Green

    Set-Location -LiteralPath $projectRoot
    npm run dev
}
finally {
    foreach ($process in @($wikiProcess, $apiProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
