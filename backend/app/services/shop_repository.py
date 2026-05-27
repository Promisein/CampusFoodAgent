import csv
import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))
SCHEMA_PATH = str(Path(__file__).resolve().parents[2] / "data" / "schema.sql")
SEED_PATH = str(Path(__file__).resolve().parents[2] / "data" / "shops_mock.csv")

_lock = threading.Lock()
_db_ready = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # 让查询结果可以用 row["name"] 访问
    conn.execute("PRAGMA journal_mode=WAL")  # 提升并发性能
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_database():
    """首次调用时建表 + 导种子数据（线程安全）"""
    global _db_ready
    if _db_ready:
        return
    with _lock:
        if _db_ready:
            return

        conn = _connect()
        try:
            # 1. 执行 schema.sql 建表
            with open(SCHEMA_PATH, encoding="utf-8") as f:
                conn.executescript(f.read())

            # 2. 导入 CSV 种子数据（只导一次）
            cur = conn.execute("SELECT COUNT(*) as cnt FROM shops")
            if cur.fetchone()["cnt"] == 0:
                with open(SEED_PATH, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # 跳过 id 字段，让数据库自增
                        values = {k: v for k, v in row.items() if k != "id"}
                        columns = ", ".join(values.keys())
                        placeholders = ", ".join("?" * len(values))
                        conn.execute(
                            f"INSERT INTO shops ({columns}) VALUES ({placeholders})",
                            list(values.values()),
                        )
            conn.commit()
        finally:
            conn.close()
        _db_ready = True


def fetch_active_shops() -> list[dict]:
    """获取全部活跃店铺"""
    _ensure_database()
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM shops ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_shop_by_id(shop_id: int) -> dict | None:
    """根据 ID 查店铺"""
    _ensure_database()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch_store_detail_by_name(name: str) -> dict | None:
    """根据店名查详情"""
    _ensure_database()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM shops WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def suggest_store_names(keyword: str, limit: int = 8) -> list[str]:
    """店名模糊搜索（自动补全用）"""
    _ensure_database()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT name FROM shops WHERE name LIKE ? LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        conn.close()
