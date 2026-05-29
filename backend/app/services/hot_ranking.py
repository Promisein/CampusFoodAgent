"""基于查询事件分析的热门关键词排行"""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))


def get_today_hot_rankings(limit: int = 5) -> list[dict]:
    """统计今日最常被查询的店铺"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT shop_name, COUNT(*) as query_count
               FROM usage_events
               WHERE event_type = 'query'
                 AND shop_name IS NOT NULL AND shop_name != ''
                 AND created_at >= date('now')
               GROUP BY shop_name
               ORDER BY query_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        items = []
        for i, row in enumerate(rows):
            shop = conn.execute(
                "SELECT * FROM shops WHERE name = ?", (row["shop_name"],)
            ).fetchone()
            items.append({
                "rank": i + 1,
                "name": row["shop_name"],
                "tag": (shop["category"] if shop and shop["category"] else "美食"),
                "avg_price": shop["avg_price"] if shop else None,
                "query": row["shop_name"],
                "query_count": row["query_count"],
            })

        return items
    finally:
        conn.close()
