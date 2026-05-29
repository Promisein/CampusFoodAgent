"""广告系统 —— 广告位展示 + 点击追踪"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_public_ad_slots(limit: int = 5) -> list[dict]:
    """获取当前生效中的广告位"""
    conn = _connect()
    try:
        now = datetime.now().isoformat()
        rows = conn.execute(
            """SELECT * FROM ad_slots
               WHERE is_active = 1
                 AND (starts_at IS NULL OR starts_at <= ?)
                 AND (ends_at IS NULL OR ends_at >= ?)
               ORDER BY id LIMIT ?""",
            (now, now, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def log_ad_click_event(slot_id: int, uid: str = "", user_id: str = "", anonymous_id: str = ""):
    """记录广告点击"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO ad_click_events (slot_id, uid, user_id, anonymous_id) VALUES (?, ?, ?, ?)",
            (slot_id, uid, user_id, anonymous_id),
        )
        conn.commit()
    finally:
        conn.close()


def seed_default_ads():
    """如果没有广告数据，插入默认广告位"""
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) as cnt FROM ad_slots").fetchone()["cnt"]
        if count == 0:
            defaults = [
                ("校内食堂一卡通充值", None, "store_detail", "学子餐厅", 1),
                ("西门夜宵一条街", None, "store_detail", "老麻抄手", 1),
                ("轻食沙拉外卖", None, "store_detail", "龙湖米线", 1),
            ]
            for title, img, ltype, lval, active in defaults:
                conn.execute(
                    "INSERT INTO ad_slots (title, image_url, landing_type, landing_value, is_active) VALUES (?, ?, ?, ?, ?)",
                    (title, img, ltype, lval, active),
                )
            conn.commit()
    finally:
        conn.close()
