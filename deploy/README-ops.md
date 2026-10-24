# 建安法规问答助手 · 运维工件（B-3，2026-10-24）

> 适用环境：**Windows 服务器**（与《部署手册-新服务器-v5.2》一致：应用装在 `C:\jianan\`，9000 端口）。
> 路线图 B-3 原文按 Linux 惯例写了 systemd/rsync/journald；实际线上是 Windows，
> 故本目录按等价物实现（任务计划程序 / robocopy / 日志轮转脚本），并在各文件头注明 Linux 等价方案备迁移。

## 工件清单

| 文件 | 作用 | 安装方式 |
|------|------|----------|
| `backup_kb.ps1` | 每日备份 kb.sqlite + 向量索引到 `C:\jianan\backup\`，保留最近 7 份 | `install_backup_task.ps1` 注册每日 03:00 任务 |
| `install_backup_task.ps1` | 注册/卸载备份计划任务（schtasks） | 管理员 PowerShell 运行 |
| `rotate_logs.ps1` | 轮转 `server.log`（>50MB 归档 zip，保留 8 份） | `install_backup_task.ps1 -AlsoLogs` 一并注册每日 03:30 |
| `Caddyfile` | HTTPS 反向代理（80/443 → 127.0.0.1:9000，自动 TLS） | 见文件头注释 |

## 安装步骤（服务器上，管理员 PowerShell）

```powershell
cd C:\jianan\deploy
# 1) 备份 + 日志轮转（一次性注册两个计划任务）
Set-ExecutionPolicy -Scope Process Bypass
.\install_backup_task.ps1 -AlsoLogs
# 验证：手动触发一次并查看产物
schtasks /run /tn "jianan-backup-daily"
dir C:\jianan\backup

# 2) HTTPS（可选，需要已解析到本机的域名）
#    下载 Caddy for Windows: https://caddy.community/download → 放到 C:\caddy\caddy.exe
copy Caddyfile C:\caddy\Caddyfile
# 编辑 Caddyfile 把 <域名> 换成实际域名，然后：
C:\caddy\caddy.exe run --config C:\caddy\Caddyfile
# 首次确认可用后，用 NSSM 把 caddy 注册为 Windows 服务（或 sc create）。
# 开启 443 后建议在安全组收掉 9000 的公网入方向，只留 127.0.0.1 回环。
```

## 验证清单

- [ ] `C:\jianan\backup\kb_YYYYMMDD\` 出现且含 kb.sqlite 与 vec_index*.npz
- [ ] backup 目录超过 7 份时最旧的被清理
- [ ] server.log 超过 50MB 时生成 `server-YYYYMMDD-HHMM.log.zip`
- [ ] （若装 Caddy）`https://<域名>/api/health` 返回 200 且证书有效

## 已核对无需改动的项（2026-10-24 实测，避免重复施工）

- **限流分端点**：实测 `/api/sources` 连发 30 次全 200、`/api/chat` 第 21 次 429——
  现行代码本就只对 chat 限流（`app/main.py` 仅 `chat()` 调 `_rate_ok`；track 有独立限流器），
  路线图该项描述与代码现状不符，**无需改动**。
