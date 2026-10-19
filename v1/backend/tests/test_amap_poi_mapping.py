"""Chapter 13 tests: AMap POI mapping and SQLite upsert behavior."""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.services.amap_poi_service import _clean_text, _parse_location, normalize_amap_poi
from scripts.sync_amap_poi import upsert_shop


class TestCleanText:
    def test_normal_string(self):
        assert _clean_text(" 清水河 ") == "清水河"

    def test_empty_values(self):
        assert _clean_text(None) is None
        assert _clean_text("") is None
        assert _clean_text("   ") is None

    def test_non_scalar_values(self):
        assert _clean_text([]) is None
        assert _clean_text({}) is None


class TestParseLocation:
    def test_normal(self):
        assert _parse_location("103.9330,30.7560") == (103.9330, 30.7560)

    def test_with_spaces(self):
        assert _parse_location(" 103.9330 , 30.7560 ") == (103.9330, 30.7560)

    @pytest.mark.parametrize("value", ["", None, "103.9330", "not,valid"])
    def test_invalid_values(self, value):
        assert _parse_location(value) == (None, None)


class TestNormalizeAmapPoi:
    def test_maps_basic_fields(self):
        raw = {
            "id": "B001",
            "name": "测试饭馆",
            "address": "清水河附近路 123 号",
            "tel": "028-123456",
            "type": "餐饮服务;中餐厅",
            "typecode": "050100",
            "location": "103.9330,30.7560",
            "adname": "郫都区",
            "business_area": "合作",
        }
        item = normalize_amap_poi(raw, campus="清水河")

        assert item["poi_id"] == "B001"
        assert item["name"] == "测试饭馆"
        assert item["longitude"] == 103.9330
        assert item["latitude"] == 30.7560
        assert item["campus"] == "清水河"
        assert item["address"] == "清水河附近路 123 号"
        assert item["phone"] == "028-123456"
        assert item["category"] == "餐饮服务;中餐厅"
        assert item["area"] == "合作"

    def test_area_fallbacks(self):
        assert normalize_amap_poi({
            "id": "B002",
            "name": "测试店",
            "adname": "郫都区",
            "business_area": "",
            "location": "103.9330,30.7560",
        })["area"] == "郫都区"

        assert normalize_amap_poi({
            "id": "B003",
            "name": "测试店",
            "adname": "",
            "business_area": "",
            "location": "103.9330,30.7560",
        })["area"] == "清水河周边"

    def test_poiid_fallback_and_empty_poi_id(self):
        assert normalize_amap_poi({
            "poiid": "B007",
            "name": "小餐馆",
            "location": "103.9330,30.7560",
        })["poi_id"] == "B007"

        assert normalize_amap_poi({
            "id": "",
            "name": "无 ID 店",
            "location": "103.9330,30.7560",
        })["poi_id"] is None

    def test_default_tags_and_empty_arrays(self):
        item = normalize_amap_poi({
            "id": "B008",
            "name": "测试标签",
            "typecode": "050100",
            "location": "103.9330,30.7560",
        })
        assert json.loads(item["tags"]) == ["高德POI", "050100"]
        assert json.loads(item["tastes"]) == []
        assert json.loads(item["scenes"]) == []
        assert json.loads(item["image_urls"]) == []
        assert item["review_count"] == 0

    def test_empty_name_is_preserved_for_upsert_skip(self):
        item = normalize_amap_poi({
            "id": "B009",
            "name": "",
            "location": "103.9330,30.7560",
        })
        assert item["name"] is None


class TestUpsertWithTempDb:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test_amap.db")
        schema_path = Path(__file__).resolve().parents[1] / "data" / "schema.sql"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        with open(schema_path, encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _upsert(self, item: dict) -> str:
        conn = self._connect()
        try:
            result = upsert_shop(conn, item)
            conn.commit()
            return result
        finally:
            conn.close()

    def test_first_sync_inserts(self):
        items = [
            normalize_amap_poi({
                "id": f"T{i:03d}",
                "name": f"测试饭馆_{i}",
                "address": f"地址_{i}",
                "location": f"103.93{i % 10:02d},30.75{i % 10:02d}",
            })
            for i in range(1, 6)
        ]
        results = [self._upsert(it) for it in items]
        assert results.count("inserted") == 5
        assert results.count("updated") == 0

    def test_second_sync_updates_not_inserts(self):
        items = [
            normalize_amap_poi({
                "id": f"T1{i:02d}",
                "name": f"重复饭馆_{i}",
                "address": f"重复地址_{i}",
                "location": f"103.93{i % 10:02d},30.75{i % 10:02d}",
            })
            for i in range(1, 4)
        ]

        for it in items:
            self._upsert(it)

        results = [self._upsert(it) for it in items]
        assert results.count("inserted") == 0
        assert results.count("updated") == 3

    def test_update_preserves_manual_recommendation_fields(self):
        item = normalize_amap_poi({
            "id": "T020",
            "name": "手工标签店",
            "address": "某处",
            "location": "103.9300,30.7500",
        })
        self._upsert(item)

        conn = self._connect()
        conn.execute(
            "UPDATE shops SET tastes = ?, scenes = ?, avg_price = ?, tags = ? WHERE poi_id = ?",
            ('["麻辣","重口"]', '["夜宵"]', 28.0, '["人工标签"]', "T020"),
        )
        conn.commit()
        conn.close()

        item2 = normalize_amap_poi({
            "id": "T020",
            "name": "手工标签店（改名了）",
            "address": "新地址 100 号",
            "location": "103.9310,30.7510",
        })
        self._upsert(item2)

        conn = self._connect()
        row = conn.execute("SELECT * FROM shops WHERE poi_id = ?", ("T020",)).fetchone()
        conn.close()

        assert row["name"] == "手工标签店（改名了）"
        assert row["address"] == "新地址 100 号"
        assert json.loads(row["tastes"]) == ["麻辣", "重口"]
        assert json.loads(row["scenes"]) == ["夜宵"]
        assert json.loads(row["tags"]) == ["人工标签"]
        assert row["avg_price"] == 28.0

    def test_existing_manual_shop_matches_by_same_campus_and_name(self):
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO shops
                (name, campus, area, address, tags, tastes, scenes, image_urls)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("紫荆餐厅", "清水河", "校内", "旧地址", '["人工标签"]', '["清淡"]', '["一人食"]', "[]"),
        )
        conn.commit()
        conn.close()

        item = normalize_amap_poi({
            "id": "AMAP_ZIJING",
            "name": "紫荆餐厅",
            "address": "高德新地址",
            "location": "103.931153,30.754402",
        }, campus="清水河")
        assert self._upsert(item) == "updated"

        conn = self._connect()
        rows = conn.execute("SELECT * FROM shops WHERE name = ?", ("紫荆餐厅",)).fetchall()
        conn.close()

        assert len(rows) == 1
        row = rows[0]
        assert row["poi_id"] == "AMAP_ZIJING"
        assert row["address"] == "高德新地址"
        assert json.loads(row["tags"]) == ["人工标签"]
        assert json.loads(row["tastes"]) == ["清淡"]
        assert json.loads(row["scenes"]) == ["一人食"]

    def test_empty_poi_id_skipped(self):
        item = normalize_amap_poi({
            "id": "",
            "name": "无 ID 店",
            "address": "某处",
            "location": "103.9300,30.7500",
        })
        assert self._upsert(item) == "skipped"

    def test_empty_name_skipped(self):
        item = normalize_amap_poi({
            "id": "NO_NAME",
            "name": "",
            "address": "某处",
            "location": "103.9300,30.7500",
        })
        assert self._upsert(item) == "skipped"
