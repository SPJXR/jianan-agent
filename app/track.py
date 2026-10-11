# -*- coding: utf-8 -*-
"""轻量埋点计数端点（迭代2.1；2026-10-11 起持久化，见 ADR-001 增补）。

合规约束（PRD §11）：
- 服务端只存「日期 + 事件名 + 计数」三元组，不存属性明细、不存问题原文、不存 IP 明文、
  不存用户身份。落盘改变的是留存期，不改变采集范围。
- 落盘失败时自动退回纯内存计数，绝不影响问答主链路。
"""
import collections
import hmac
import os
import re
import sqlite3
import sys
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import config

router = APIRouter(prefix="/api/track")

MAX_EVENTS_PER_POST = 20
RATE_LIMIT_PER_MIN = 60
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_ALLOWED_SCALARS = (str, int, float, bool)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "track.sqlite")

# ---- 计数：内存当日缓存 + SQLite 持久化（day = YYYYMMDD，跨日自动切换）----
_counts: dict[str, int] = {}
_counts_day = ""
_track_rate: dict[str, collections.deque] = {}
_db_ok = True


def _today() -> str:
    return time.strftime("%Y%m%d")


def _db():
    """惰性建库建表；任何异常都关掉持久化并退回内存模式。"""
    global _db_ok
    if not _db_ok:
        return None
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        con = sqlite3.connect(DB_PATH, timeout=5.0)
        con.execute(
            "CREATE TABLE IF NOT EXISTS track_counts ("
            " day TEXT NOT NULL, event TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,"
            " PRIMARY KEY (day, event))")
        con.commit()
        return con
    except Exception as exc:  # pragma: no cover - 环境性故障
        _db_ok = False
        print(f"[track] 持久化不可用，退回内存模式: {exc}", file=sys.stderr)
        return None


def _load_day(day: str) -> dict[str, int]:
    con = _db()
    if con is None:
        return {}
    try:
        return {r[0]: r[1] for r in con.execute(
            "SELECT event, n FROM track_counts WHERE day=?", (day,))}
    except Exception as exc:  # pragma: no cover
        print(f"[track] 读取计数失败: {exc}", file=sys.stderr)
        return {}
    finally:
        con.close()


def _persist(day: str, names: list[str]):
    if not names:
        return
    con = _db()
    if con is None:
        return
    try:
        con.executemany(
            "INSERT INTO track_counts(day, event, n) VALUES(?,?,1) "
            "ON CONFLICT(day, event) DO UPDATE SET n = n + 1",
            [(day, n) for n in names])
        con.commit()
    except Exception as exc:  # pragma: no cover
        print(f"[track] 写入计数失败（本批仅保留在内存）: {exc}", file=sys.stderr)
    finally:
        con.close()


def _rollover():
    global _counts_day, _counts
    today = _today()
    if _counts_day != today:
        _counts_day = today
        _counts = _load_day(today)


def _rate_ok(ip: str) -> bool:
    now = time.time()
    dq = _track_rate.setdefault(ip, collections.deque())
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= RATE_LIMIT_PER_MIN:
        return False
    dq.append(now)
    return True


def _sanitize_event(ev) -> dict | None:
    """白名单清洗：只保留合法事件名与标量属性；超长字段截断。非法整体丢弃。"""
    if not isinstance(ev, dict):
        return None
    name = ev.get("event")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    out = {"event": name}
    for k, v in ev.items():
        if k == "event" or not isinstance(k, str):
            continue
        if isinstance(v, _ALLOWED_SCALARS):
            if isinstance(v, str):
                v = v[:200]
            out[k[:40]] = v
    return out


@router.post("")
async def track(request: Request):
    ip = request.client.host if request.client else "?"
    if not _rate_ok(ip):
        return JSONResponse(
            {"error": {"code": "rate_limited", "message": "上报过于频繁"}},
            status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": {"code": "bad_request", "message": "请求格式错误"}}, status_code=400)
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or not events or len(events) > MAX_EVENTS_PER_POST:
        return JSONResponse({"error": {"code": "bad_request", "message": "events 需为 1-20 条数组"}}, status_code=400)

    _rollover()
    accepted = 0
    bumped: list[str] = []
    for ev in events:
        clean = _sanitize_event(ev)
        if clean is None:
            continue
        name = clean["event"]
        _counts[name] = _counts.get(name, 0) + 1
        bumped.append(name)
        accepted += 1
    if not accepted:
        return JSONResponse({"error": {"code": "bad_request", "message": "无合法事件"}}, status_code=400)
    _persist(_counts_day, bumped)
    return {"accepted": accepted}


@router.get("/stats")
async def track_stats(request: Request, history: int = 0):
    """事件计数。鉴权策略（ADR-001 增补遗留项）：

    - 配置了 TRACK_STATS_TOKEN → 必须带 `?token=` 或请求头 `X-Track-Token`，用常数时间比较；
    - 未配置口令 → **仅允许本机回环**（127.0.0.1 / ::1），公网默认关闭而非默认敞开。
      本项目由 uvicorn 直接对外服务、无反代改写 client.host，故该判断可靠；
      若日后加上 Nginx 等反向代理，必须改为强制配置口令，否则所有请求都会被误认为本机。
    """
    ip = request.client.host if request.client else ""
    token = config.TRACK_STATS_TOKEN
    if token:
        given = request.query_params.get("token") or request.headers.get("x-track-token") or ""
        if not hmac.compare_digest(given, token):
            return JSONResponse({"error": {"code": "forbidden", "message": "无权查看统计"}}, status_code=403)
    elif ip not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": {"code": "forbidden", "message": "统计端点仅限本机访问，或配置 TRACK_STATS_TOKEN"}},
                            status_code=403)
    _rollover()
    out = {"day": _counts_day, "counts": dict(sorted(_counts.items())), "persistent": _db_ok}
    if history:
        con = _db()
        days = []
        if con is not None:
            try:
                rows = con.execute(
                    "SELECT day, event, n FROM track_counts "
                    "WHERE day IN (SELECT DISTINCT day FROM track_counts ORDER BY day DESC LIMIT 30) "
                    "ORDER BY day DESC, event").fetchall()
                bucket: dict[str, dict[str, int]] = {}
                for d, e, n in rows:
                    bucket.setdefault(d, {})[e] = n
                days = [{"day": d, "counts": c} for d, c in bucket.items()]
            except Exception as exc:  # pragma: no cover
                print(f"[track] 读取历史失败: {exc}", file=sys.stderr)
            finally:
                con.close()
        out["history"] = days
    return out
