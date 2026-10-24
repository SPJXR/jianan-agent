# rotate_logs.ps1 — 轮转 uvicorn server.log（>50MB 归档 zip，保留 8 份）
# Linux 等价（迁移时）：logrotate 或 journald SystemMaxUse=200M
$ErrorActionPreference = "Continue"

$Log     = "C:\jianan\server.log"
$MaxMB   = 50
$Keep    = 8
$Archive = "C:\jianan\logs"

if (-not (Test-Path $Log)) { Write-Output "[logrotate] 无 $Log，跳过"; exit 0 }
if ((Get-Item $Log).Length -lt $MaxMB * 1MB) { Write-Output "[logrotate] 未超 $MaxMB MB，跳过"; exit 0 }

New-Item -ItemType Directory -Force -Path $Archive | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"
$Zipped = Join-Path $Archive "server-$Stamp.log.zip"
Compress-Archive -Path $Log -DestinationPath $Zipped -Force

# 清空原文件（服务进程保持打开句柄，不能删除重命名，只能清空）
Clear-Content $Log

# 清理过期归档
Get-ChildItem $Archive -Filter "server-*.log.zip" |
    Sort-Object Name -Descending |
    Select-Object -Skip $Keep |
    Remove-Item -Force

Write-Output "[logrotate] $Log -> $Zipped"
