"""shop_feature_drafts 表的 CRUD —— pending / approved / rejected / applied 管理."""
import json
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))
VALID_STATUSES = {"pending", "approved", "rejected", "applied"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _merge_json_lists(existing_json: str | None, draft_json: str | None) -> str:
    merged = []
    seen = set()
    for item in [*_json_list(existing_json), *_json_list(draft_json)]:
        if not isinstance(item, str) or item in seen:
            continue
        merged.append(item)
        seen.add(item)
    return json.dumps(merged, ensure_ascii=False)


def save_draft(shop_id: int, shop_name: str, feature_data: dict) -> bool:
    """保存或更新候选特征（UNIQUE shop_id + source），状态 reset 为 pending."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO shop_feature_drafts
                (shop_id, shop_name, avg_price, avg_price_min, avg_price_max,
                 tastes_json, scenes_json, tags_json, confidence, reason, source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'deepseek', 'pending')
            ON CONFLICT(shop_id, source) DO UPDATE SET
                shop_name = excluded.shop_name,
                avg_price = excluded.avg_price,
                avg_price_min = excluded.avg_price_min,
                avg_price_max = excluded.avg_price_max,
                tastes_json = excluded.tastes_json,
                scenes_json = excluded.scenes_json,
                tags_json = excluded.tags_json,
                confidence = excluded.confidence,
                reason = excluded.reason,
                status = 'pending',
                updated_at = datetime('now')
            """,
            (
                shop_id,
                shop_name,
                feature_data.get("avg_price"),
                feature_data.get("avg_price_min"),
                feature_data.get("avg_price_max"),
                json.dumps(feature_data.get("tastes") or [], ensure_ascii=False),
                json.dumps(feature_data.get("scenes") or [], ensure_ascii=False),
                json.dumps(feature_data.get("tags") or [], ensure_ascii=False),
                feature_data.get("confidence", 0.0),
                feature_data.get("reason", ""),
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_drafts(status: str | None = None, limit: int = 30) -> list[dict]:
    """查询草稿列表. status 可选 pending/approved/rejected/applied."""
    conn = _connect()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM shop_feature_drafts WHERE status = ? ORDER BY confidence DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM shop_feature_drafts ORDER BY confidence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_draft_status(draft_id: int, status: str) -> bool:
    """更新单条 draft 状态."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid draft status: {status}")

    conn = _connect()
    try:
        conn.execute(
            "UPDATE shop_feature_drafts SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, draft_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def approve_by_confidence(min_confidence: float) -> int:
    """将 confidence >= min_confidence 的 pending drafts 批量标记为 approved."""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE shop_feature_drafts SET status = 'approved', updated_at = datetime('now') "
            "WHERE status = 'pending' AND confidence >= ?",
            (min_confidence,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def apply_approved_to_shops() -> int:
    """
    将 status='approved' 的 drafts 写入 shops 正式字段。
    只更新 shops 中已有的行，不新增店铺。
    返回写入条数。
    """
    conn = _connect()
    count = 0
    try:
        rows = conn.execute(
            "SELECT * FROM shop_feature_drafts WHERE status = 'approved'"
        ).fetchall()

        for row in rows:
            shop_id = row["shop_id"]
            # 确认 shops 中存在
            existing = conn.execute(
                "SELECT id, tags FROM shops WHERE id = ?", (shop_id,)
            ).fetchone()
            if not existing:
                continue
            merged_tags_json = _merge_json_lists(existing["tags"], row["tags_json"])

            conn.execute(
                """
                UPDATE shops
                SET avg_price = COALESCE(shops.avg_price, ?),
                    avg_price_min = COALESCE(shops.avg_price_min, ?),
                    avg_price_max = COALESCE(shops.avg_price_max, ?),
                    tastes = CASE WHEN shops.tastes IS NULL OR shops.tastes = '[]' THEN ? ELSE shops.tastes END,
                    scenes = CASE WHEN shops.scenes IS NULL OR shops.scenes = '[]' THEN ? ELSE shops.scenes END,
                    tags = ?,           -- tags 合并：高德POI + DeepSeek tags
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    row["avg_price"], row["avg_price_min"], row["avg_price_max"],
                    row["tastes_json"], row["scenes_json"],
                    merged_tags_json,
                    shop_id,
                ),
            )
            conn.execute(
                "UPDATE shop_feature_drafts SET status = 'applied', updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            count += 1

        conn.commit()
    finally:
        conn.close()

    return count


def delete_drafts_for_shop(shop_id: int) -> bool:
    """删除某店铺的所有 drafts."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM shop_feature_drafts WHERE shop_id = ?", (shop_id,))
        conn.commit()
        return True
    finally:
        conn.close()
