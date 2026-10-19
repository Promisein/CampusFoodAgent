"""用户收藏 —— 增删查 + 幂等添加"""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def add_favorite(user_id: str, shop_id: int, shop_name: str = "") -> bool:
    """添加收藏。UNIQUE(user_id, shop_id) + OR IGNORE 保证幂等"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_favorites (user_id, shop_id, shop_name) VALUES (?, ?, ?)",
            (user_id, shop_id, shop_name),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_favorite(user_id: str, shop_id: int) -> bool:
    """取消收藏"""
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM user_favorites WHERE user_id = ? AND shop_id = ?",
            (user_id, shop_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_favorites(user_id: str) -> list[dict]:
    """获取用户收藏列表"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM user_favorites WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_favorite_if_not_exists(user_id: str, shop_name: str) -> bool:
    """按店名添加收藏（用于 sync-local）。第 7 章完整实现写入 SQLite。"""
    if not user_id or not shop_name:
        return False
    conn = _connect()
    try:
        shop = conn.execute(
            "SELECT id FROM shops WHERE name = ?", (shop_name,)
        ).fetchone()
        if shop:
            conn.execute(
                "INSERT OR IGNORE INTO user_favorites (user_id, shop_id, shop_name) VALUES (?, ?, ?)",
                (user_id, shop["id"], shop_name),
            )
            conn.commit()
            return True
        return False
    finally:
        conn.close()
