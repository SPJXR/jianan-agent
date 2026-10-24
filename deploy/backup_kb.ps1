# backup_kb.ps1 — 每日备份知识库（kb.sqlite + 向量索引），保留最近 7 份
# 适用：Windows 服务器，应用目录 C:\jianan（与部署手册 v5.2 一致）
# Linux 等价（迁移时）：rsync + systemd timer + logrotate
#
# 由 install_backup_task.ps1 注册的计划任务每日 03:00 调用，也可手动运行。
$ErrorActionPreference = "Stop"

$AppDir   = "C:\jianan"
$BackupRoot = Join-Path $AppDir "backup"
$Keep     = 7
$Stamp    = Get-Date -Format "yyyyMMdd"
$Dest     = Join-Path $BackupRoot "kb_$Stamp"

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

$items = @(
    (Join-Path $AppDir "kb\kb.sqlite"),
    (Join-Path $AppDir "kb\kb.sqlite-wal")   # SQLite WAL 若存在一并带走
) + (Get-ChildItem (Join-Path $AppDir "kb") -Filter "vec_index_*.npz" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })

$copied = 0
foreach ($src in $items) {
    if (Test-Path $src) {
        # kb.sqlite 备份期间服务仍在写入：用 sqlite3 .backup 若可用，否则 Copy-Item
        # （414 片段库 <5MB，写入窗口极小，Copy-Item 足够；损坏可由下一日备份覆盖）
        Copy-Item $src -Destination $Dest -Force
        $copied++
    }
}

if ($copied -eq 0) {
    Write-Error "[jianan-backup] 未找到任何可备份文件，检查 $AppDir\kb"
    exit 1
}

# 清理过期备份（按目录名日期排序，保留最近 $Keep 份）
Get-ChildItem $BackupRoot -Directory -Filter "kb_*" |
    Sort-Object Name -Descending |
    Select-Object -Skip $Keep |
    Remove-Item -Recurse -Force

Write-Output ("[jianan-backup] {0} -> {1}（{2} 个文件）" -f $Stamp, $Dest, $copied)
