"""用户反馈存储 —— 提交反馈 + 查询历史"""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def save_feedback(
    feedback_type: str,
    store_name: str,
    rating: int | None = None,
    scene_tags: str | None = None,
    taste_tags: str | None = None,
    recommend_dish: str | None = None,
    comment: str | None = None,
    uid: str | None = None,
    user_id: str | None = None,
    anonymous_id: str | None = None,
) -> int:
    """保存用户反馈，返回新记录 ID"""
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO feedback_submissions
               (feedback_type, store_name, rating, scene_tags, taste_tags,
                recommend_dish, comment, uid, user_id, anonymous_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (feedback_type, store_name, rating, scene_tags, taste_tags,
             recommend_dish, comment, uid, user_id, anonymous_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_feedback_by_user(
    uid: str | None = None,
    user_id: str | None = None,
    days: int = 90,
    limit: int = 80,
) -> list[dict]:
    """获取指定用户的反馈历史"""
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
            f"SELECT * FROM feedback_submissions WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
