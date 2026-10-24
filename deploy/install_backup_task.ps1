# install_backup_task.ps1 — 注册每日备份（与可选日志轮转）计划任务
# 用法（管理员 PowerShell）：
#   .\install_backup_task.ps1              # 只注册备份（每日 03:00）
#   .\install_backup_task.ps1 -AlsoLogs    # 同时注册日志轮转（每日 03:30）
#   .\install_backup_task.ps1 -Uninstall   # 卸载两个任务
param(
    [switch]$AlsoLogs,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"

$TaskBackup = "jianan-backup-daily"
$TaskLogs   = "jianan-logrotate-daily"
$DeployDir  = $PSScriptRoot

if ($Uninstall) {
    schtasks /change /tn $TaskBackup /disable 2>$null | Out-Null
    schtasks /end /tn $TaskBackup 2>$null | Out-Null
    schtasks /delete /tn $TaskBackup /f 2>$null
    schtasks /delete /tn $TaskLogs /f 2>$null
    Write-Output "已卸载计划任务（如存在）"
    exit 0
}

# 备份：每日 03:00，以 SYSTEM 运行（无需用户登录）
schtasks /create /tn $TaskBackup /sc daily /st 03:00 /ru SYSTEM /f /tr `
    "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$DeployDir\backup_kb.ps1`" >> C:\jianan\backup\backup.log 2>&1"
if ($LASTEXITCODE -ne 0) { throw "注册备份任务失败（需管理员权限）" }
Write-Output "已注册 $TaskBackup（每日 03:00）"

if ($AlsoLogs) {
    schtasks /create /tn $TaskLogs /sc daily /st 03:30 /ru SYSTEM /f /tr `
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$DeployDir\rotate_logs.ps1`""
    if ($LASTEXITCODE -ne 0) { throw "注册日志轮转任务失败（需管理员权限）" }
    Write-Output "已注册 $TaskLogs（每日 03:30）"
}

Write-Output "手动验证：schtasks /run /tn $TaskBackup  然后 dir C:\jianan\backup"
