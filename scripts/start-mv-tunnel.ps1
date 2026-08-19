param(
    [string]$RouterHost = "192.168.100.1",
    [string]$RouterBindAddress = "192.168.100.1",
    [int]$RouterPort = 18787,
    [string]$KeyPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $KeyPath) {
    $KeyPath = Join-Path $projectRoot "work\astrbot-mv-tunnel-ed25519"
}
$resolvedKey = (Resolve-Path -LiteralPath $KeyPath -ErrorAction Stop).Path

$arguments = @(
    "-N",
    "-T",
    "-o", "BatchMode=yes",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "StrictHostKeyChecking=accept-new",
    "-i", $resolvedKey,
    "-R", "${RouterBindAddress}:${RouterPort}:127.0.0.1:8787",
    "root@$RouterHost"
)

Start-Process -FilePath "ssh" -ArgumentList $arguments -WindowStyle Hidden -PassThru
