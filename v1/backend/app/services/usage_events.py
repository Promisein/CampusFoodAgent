"""通用用户行为事件追踪（埋点）"""
import json
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))


def _connect() -> sqlite3.Connection:
    from app.services import shop_repository

    shop_repository._ensure_database()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_usage_event(
    event_type: str,
    uid: str = "",
    user_id: str = "",
    anonymous_id: str = "",
    query_text: str = "",
    shop_id: int | None = None,
    shop_name: str = "",
    extra: dict | None = None,
):
    """记录通用使用事件。埋点失败不抛异常，不阻塞主流程。"""
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO usage_events (event_type, uid, user_id, anonymous_id,
               query_text, shop_id, shop_name, extra_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_type, uid, user_id, anonymous_id, query_text, shop_id, shop_name,
             json.dumps(extra or {}, ensure_ascii=False)),
        )
        conn.commit()
    except Exception:
        pass  # 埋点失败不阻塞主流程
    finally:
        conn.close()


def list_recent_events(
    uid: str | None = None,
    user_id: str | None = None,
    days: int = 30,
    limit: int = 80,
) -> list[dict]:
    """获取用户最近的事件"""
    conn = _connect()
    try:
        conditions = []
        params = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        elif uid:
            conditions.append("uid = ?")
            params.append(uid)
        else:
            return []

        conditions.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM usage_events WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def bind_anonymous_events_to_user(anonymous_id: str, user_id: str):
    """将匿名期间的事件绑定到登录用户"""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE usage_events SET user_id = ? WHERE anonymous_id = ? AND (user_id IS NULL OR user_id = '')",
            (user_id, anonymous_id),
        )
        conn.commit()
    finally:
        conn.close()
