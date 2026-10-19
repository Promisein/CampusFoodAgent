"""Sync AMap POI data into the local SQLite shops table.

Examples:
  python scripts/sync_amap_poi.py --campus qingshuihe --dry-run
  python scripts/sync_amap_poi.py --campus qingshuihe
  python scripts/sync_amap_poi.py --campus qingshuihe --limit-pages 2 --radius 3000
  python scripts/sync_amap_poi.py --center 103.9330,30.7560 --keywords 米线 --dry-run
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))


def get_db_path() -> str:
    return os.getenv(
        "SQLITE_DB_PATH",
        str(Path(BACKEND_ROOT) / "data" / "chedian.db"),
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    schema_path = Path(BACKEND_ROOT) / "data" / "schema.sql"
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def upsert_shop(conn: sqlite3.Connection, item: dict) -> str:
    """Insert or update one normalized POI. Returns inserted/updated/skipped."""
    poi_id = item.get("poi_id")
    name = item.get("name")
    if not poi_id or not name:
        return "skipped"

    existing = conn.execute(
        "SELECT id FROM shops WHERE poi_id = ?", (poi_id,)
    ).fetchone()
    if existing is None:
        existing = conn.execute(
            "SELECT id FROM shops WHERE campus = ? AND name = ? ORDER BY id LIMIT 1",
            (item["campus"], name),
        ).fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO shops
                (name, campus, area, poi_id, address, phone, category,
                 latitude, longitude, tags, tastes, scenes, image_urls,
                 review_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["name"], item["campus"], item["area"], item["poi_id"],
                item["address"], item["phone"], item["category"],
                item["latitude"], item["longitude"],
                item["tags"], item["tastes"], item["scenes"], item["image_urls"],
                item.get("review_count", 0),
            ),
        )
        return "inserted"

    conn.execute(
        """
        UPDATE shops
        SET name = ?,
            address = ?,
            phone = ?,
            category = ?,
            area = ?,
            latitude = ?,
            longitude = ?,
            updated_at = datetime('now'),
            poi_id = ?
        WHERE id = ?
        """,
        (
            item["name"], item["address"], item["phone"],
            item["category"], item["area"],
            item["latitude"], item["longitude"],
            poi_id, existing["id"],
        ),
    )
    return "updated"


def _campus_config(campus: str) -> tuple[str, int, str]:
    if campus == "qingshuihe":
        center = os.getenv("AMAP_QINGSHUIHE_CENTER", "103.9330,30.7560")
        radius = int(os.getenv("AMAP_QINGSHUIHE_RADIUS", "4000"))
        return center, radius, "清水河"
    center = os.getenv("AMAP_SHAHE_CENTER", "104.0500,30.6800")
    radius = int(os.getenv("AMAP_SHAHE_RADIUS", "3000"))
    return center, radius, "沙河"


def main() -> None:
    parser = argparse.ArgumentParser(description="高德 POI 同步到本地 SQLite")
    parser.add_argument("--campus", default="qingshuihe", choices=["qingshuihe", "shahe"])
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    parser.add_argument("--limit-pages", type=int, default=None, help="限制翻页数")
    parser.add_argument("--radius", type=int, default=None, help="覆盖半径，单位米")
    parser.add_argument("--center", default=None, help="覆盖中心坐标，格式：经度,纬度")
    parser.add_argument("--types", default=None, help="覆盖高德 POI 类型码，例如 050000")
    parser.add_argument("--keywords", default=None, help="按关键词过滤，例如 米线、火锅、咖啡")
    parser.add_argument("--city", default=None, help="覆盖城市，例如 成都")
    args = parser.parse_args()

    key = os.getenv("AMAP_WEB_SERVICE_KEY", "").strip()
    if not key:
        print("错误: 未配置 AMAP_WEB_SERVICE_KEY，请在 backend/.env 中设置")
        sys.exit(1)

    default_center, default_radius, campus_name = _campus_config(args.campus)
    center = args.center or default_center
    radius = args.radius or default_radius
    max_pages = args.limit_pages or int(os.getenv("AMAP_POI_MAX_PAGES", "8"))
    types = args.types or os.getenv("AMAP_POI_TYPES", "050000")
    keywords = args.keywords if args.keywords is not None else os.getenv("AMAP_POI_KEYWORDS", "")
    city = args.city or os.getenv("AMAP_POI_CITY", "成都")

    print("AMap POI sync started")
    print(f"campus={args.campus} center={center} radius={radius} types={types} keywords={keywords or '-'}")
    if args.dry_run:
        print("[DRY-RUN] 不会写入数据库")

    from app.services.amap_poi_service import (
        AmapPoiError,
        fetch_amap_poi_page,
        normalize_amap_poi,
    )

    all_pois: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            data = fetch_amap_poi_page(
                key=key,
                center=center,
                radius=radius,
                page=page,
                types=types,
                keywords=keywords,
                city=city,
            )
            pois = data.get("pois") or []
        except AmapPoiError as e:
            print(f"  page={page} 请求失败: {e}")
            break

        print(f"  page={page} fetched={len(pois)}")
        all_pois.extend(pois)
        if len(pois) < 25:
            break

    print(f"共获取 {len(all_pois)} 条 POI")

    if args.dry_run:
        skipped_preview = 0
        for poi in all_pois[:10]:
            item = normalize_amap_poi(poi, campus=campus_name)
            if not item.get("poi_id") or not item.get("name"):
                skipped_preview += 1
                continue
            print(f"  {item['name']} | {item['address']} | location={item['longitude']},{item['latitude']} | poi_id={item['poi_id']}")
        if skipped_preview:
            print(f"  dry-run preview skipped={skipped_preview}")
        if len(all_pois) > 10:
            print(f"  ... 还有 {len(all_pois) - 10} 条")
        print("dry-run done")
        return

    conn = _connect()
    try:
        _ensure_schema(conn)
        inserted = updated = skipped = 0

        for poi in all_pois:
            item = normalize_amap_poi(poi, campus=campus_name)
            result = upsert_shop(conn, item)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1

        conn.commit()
        print(f"inserted={inserted} updated={updated} skipped={skipped}")
    finally:
        conn.close()

    print("done")


if __name__ == "__main__":
    main()
