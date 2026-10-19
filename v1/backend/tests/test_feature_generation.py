"""Chapter 14 tests: 特征补齐 —— gap 检测 + JSON 解析 + 白名单过滤 + draft 管理."""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.services.deepseek_feature_service import (
    _extract_json,
    build_feature_prompt,
    parse_and_validate,
)
from app.services.feature_draft_repository import (
    approve_by_confidence,
    apply_approved_to_shops,
    list_drafts,
    save_draft,
    update_draft_status,
)
from app.services.feature_gap_service import (
    compute_data_quality_score,
    is_recommendable,
    list_missing_fields,
    needs_feature_completion,
)


# ---- 辅助：构造测试 shop dict ----
def _make_shop(**overrides) -> dict:
    base = {
        "id": 1,
        "name": "测试餐厅",
        "campus": "清水河",
        "area": "龙湖",
        "address": "清水河校区龙湖时代天街 1 楼",
        "category": "川菜;中餐厅",
        "avg_price": None,
        "avg_price_min": None,
        "avg_price_max": None,
        "tastes": "[]",
        "scenes": "[]",
        "tags": '["高德POI", "050100"]',
        "latitude": 30.75,
        "longitude": 103.93,
        "rating": None,
    }
    base.update(overrides)
    return base


# ======================== Gap Detection ========================
class TestNeedsFeatureCompletion:
    def test_all_missing(self):
        shop = _make_shop()
        assert needs_feature_completion(shop) is True

    def test_full_features(self):
        shop = _make_shop(
            avg_price=25,
            tastes='["麻辣","重口"]',
            scenes='["一人食"]',
            tags='["川菜","适合学生"]',
        )
        assert needs_feature_completion(shop) is False

    def test_only_missing_price(self):
        shop = _make_shop(
            tastes='["清淡"]',
            scenes='["一人食"]',
            tags='["快餐"]',
        )
        assert needs_feature_completion(shop) is True

    def test_empty_tastes(self):
        shop = _make_shop(avg_price=18, tastes="[]", scenes='["一人食"]')
        assert needs_feature_completion(shop) is True

    def test_empty_scenes(self):
        shop = _make_shop(avg_price=18, tastes='["麻辣"]', scenes="[]")
        assert needs_feature_completion(shop) is True

    def test_only_amap_tags(self):
        shop = _make_shop(
            avg_price=20,
            tastes='["清淡"]',
            scenes='["一人食"]',
            tags='["高德POI"]',
        )
        assert needs_feature_completion(shop) is True


class TestListMissingFields:
    def test_all(self):
        missing = list_missing_fields(_make_shop())
        assert "avg_price" in missing
        assert "tastes" in missing
        assert "scenes" in missing
        assert "tags" in missing

    def test_none(self):
        missing = list_missing_fields(_make_shop(
            avg_price=25, tastes='["麻辣"]', scenes='["一人食"]', tags='["川菜"]',
        ))
        assert missing == []

    def test_only_price_missing(self):
        missing = list_missing_fields(_make_shop(
            tastes='["麻辣"]', scenes='["一人食"]', tags='["川菜"]',
        ))
        assert missing == ["avg_price"]


# ======================== Data Quality Score ========================
class TestDataQualityScore:
    def test_full_manual_shop(self):
        shop = _make_shop(
            avg_price=28,
            tastes='["麻辣","重口"]',
            scenes='["夜宵","同学聚餐"]',
            tags='["火锅","川菜"]',
            rating=4.5,
        )
        score = compute_data_quality_score(shop)
        assert score >= 80

    def test_bare_amap_poi(self):
        shop = _make_shop()
        score = compute_data_quality_score(shop)
        # 只有 name + category + address + lat/lon = 40
        assert score == 40

    def test_no_lat_lon(self):
        shop = _make_shop(latitude=None, longitude=None)
        score = compute_data_quality_score(shop)
        assert score == 30  # name + category + address = 30

    def test_no_category_no_address(self):
        shop = _make_shop(category=None, address=None, latitude=None, longitude=None)
        score = compute_data_quality_score(shop)
        assert score == 10  # name only


class TestIsRecommendable:
    def test_quality_ge_70(self):
        shop = _make_shop(
            avg_price=20,
            tastes='["清淡"]',
            scenes='["一人食"]',
            tags='["快餐"]',
        )
        assert is_recommendable(shop) is True

    def test_quality_lt_70(self):
        shop = _make_shop()
        assert is_recommendable(shop) is False


# ======================== Prompt Building ========================
class TestBuildFeaturePrompt:
    def test_includes_shop_info(self):
        shop = _make_shop(name="老麻抄手", area="西门")
        prompt = build_feature_prompt(shop)
        assert "老麻抄手" in prompt
        assert "西门" in prompt
        assert "清淡" in prompt  # whitelist
        assert "一人食" in prompt  # scene whitelist

    def test_includes_whitelists(self):
        prompt = build_feature_prompt(_make_shop())
        for wl_item in ["麻辣", "微辣", "夜宵", "早餐", "食堂", "快餐"]:
            assert wl_item in prompt


# ======================== JSON Parsing & Validation ========================
class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == '{"a": 1}'

    def test_markdown_code_block(self):
        text = "```json\n{\"a\": 1}\n```"
        assert _extract_json(text) == '{"a": 1}'

    def test_markdown_without_lang(self):
        text = "```\n{\"a\": 1}\n```"
        assert _extract_json(text) == '{"a": 1}'

    def test_text_wrapped(self):
        text = "Some text before {\"a\": 1} and after"
        assert _extract_json(text) == '{"a": 1}'

    def test_no_json(self):
        assert _extract_json("No JSON here") is None

    def test_empty(self):
        assert _extract_json("") is None


class TestParseAndValidate:
    def test_valid_full_output(self):
        fake = {
            "avg_price": 18,
            "avg_price_min": 12,
            "avg_price_max": 25,
            "tastes": ["清淡", "家常"],
            "scenes": ["一人食", "午餐", "低预算"],
            "tags": ["米线", "快餐", "适合学生"],
            "confidence": 0.82,
            "reason": "店名含米线，适合一人食",
        }
        result = parse_and_validate(json.dumps(fake, ensure_ascii=False))
        assert result is not None
        assert result["avg_price"] == 18
        assert result["tastes"] == ["清淡", "家常"]
        assert result["scenes"] == ["一人食", "午餐", "低预算"]
        assert result["tags"] == ["米线", "快餐", "适合学生"]
        assert result["confidence"] == 0.82

    def test_price_out_of_range(self):
        fake = {
            "avg_price": 999,
            "tastes": ["清淡"],
            "scenes": ["一人食"],
            "tags": ["快餐"],
            "confidence": 0.5,
            "reason": "test",
        }
        result = parse_and_validate(json.dumps(fake))
        assert result is not None
        assert result["avg_price"] is None  # 价格 999 被拒绝

    def test_price_negative(self):
        fake = {
            "avg_price": -5,
            "tastes": ["清淡"],
            "scenes": ["一人食"],
            "tags": ["快餐"],
            "confidence": 0.5,
            "reason": "test",
        }
        result = parse_and_validate(json.dumps(fake))
        assert result is not None
        assert result["avg_price"] is None

    def test_invalid_tastes_filtered(self):
        fake = {
            "avg_price": 20,
            "tastes": ["清淡", "超辣无敌", "家常", "不存在"],
            "scenes": ["一人食"],
            "tags": ["快餐"],
            "confidence": 0.6,
            "reason": "test",
        }
        result = parse_and_validate(json.dumps(fake))
        assert result is not None
        # 只保留白名单内的
        assert result["tastes"] == ["清淡", "家常"]

    def test_invalid_scenes_filtered(self):
        fake = {
            "avg_price": 20,
            "tastes": ["清淡"],
            "scenes": ["一人食", "蹦迪", "同学聚餐", "游泳"],
            "tags": ["快餐"],
            "confidence": 0.6,
            "reason": "test",
        }
        result = parse_and_validate(json.dumps(fake))
        assert result["scenes"] == ["一人食", "同学聚餐"]

    def test_invalid_tags_filtered(self):
        fake = {
            "avg_price": 20,
            "tastes": ["清淡"],
            "scenes": ["一人食"],
            "tags": ["快餐", "按摩", "川菜", "洗脚"],
            "confidence": 0.6,
            "reason": "test",
        }
        result = parse_and_validate(json.dumps(fake))
        assert result["tags"] == ["快餐", "川菜"]

    def test_confidence_clamped(self):
        fake = {
            "avg_price": 20,
            "tastes": ["清淡"],
            "scenes": ["一人食"],
            "tags": ["快餐"],
            "confidence": 1.5,
            "reason": "test",
        }
        result = parse_and_validate(json.dumps(fake))
        # confidence 1.5 不在 [0,1]，保持默认 0.0
        assert result["confidence"] == 0.0

    def test_no_price_no_labels_returns_none(self):
        fake = {
            "tastes": [],
            "scenes": [],
            "tags": [],
            "confidence": 0.5,
            "reason": "nothing useful",
        }
        result = parse_and_validate(json.dumps(fake))
        assert result is None

    def test_invalid_json_returns_none(self):
        assert parse_and_validate("not json {{{") is None

    def test_reason_truncated(self):
        fake = {
            "avg_price": 20,
            "tastes": ["清淡"],
            "scenes": ["一人食"],
            "tags": ["快餐"],
            "confidence": 0.7,
            "reason": "x" * 600,
        }
        result = parse_and_validate(json.dumps(fake))
        assert len(result["reason"]) == 500

    def test_price_min_max_order_fixed(self):
        fake = {
            "avg_price": 25,
            "avg_price_min": 30,  # min > avg
            "avg_price_max": 20,  # max < avg
            "tastes": ["清淡"],
            "scenes": ["一人食"],
            "tags": ["快餐"],
            "confidence": 0.5,
            "reason": "test",
        }
        result = parse_and_validate(json.dumps(fake))
        # min 被修正为 avg，max 被修正为 avg
        if result["avg_price_min"] is not None:
            assert result["avg_price_min"] <= result["avg_price"]
        if result["avg_price_max"] is not None:
            assert result["avg_price_max"] >= result["avg_price"]


# ======================== Draft Repository ========================
class TestDraftRepository:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test_feature.db")

        # 创建 schema
        schema_path = Path(__file__).resolve().parents[1] / "data" / "schema.sql"
        conn = sqlite3.connect(self.db_path)
        with open(schema_path, encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()

        # 注入 seed shop
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO shops (id, name, campus, area, address, category, tags, tastes, scenes, image_urls) "
            "VALUES (1, '测试店A', '清水河', '龙湖', '地址A', '川菜', '[\"高德POI\"]', '[]', '[]', '[]')"
        )
        conn.execute(
            "INSERT INTO shops (id, name, campus, area, address, category, tags, tastes, scenes, image_urls) "
            "VALUES (2, '测试店B', '清水河', '西门', '地址B', '火锅', '[\"火锅\"]', '[\"麻辣\"]', '[\"夜宵\"]', '[]')"
        )
        conn.commit()
        conn.close()

    def _set_db_path(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.feature_draft_repository.DB_PATH", self.db_path
        )

    def test_save_and_list_draft(self, monkeypatch):
        self._set_db_path(monkeypatch)
        feature_data = {
            "avg_price": 28,
            "avg_price_min": 20,
            "avg_price_max": 35,
            "tastes": ["麻辣", "重口"],
            "scenes": ["夜宵", "同学聚餐"],
            "tags": ["火锅", "川菜"],
            "confidence": 0.85,
            "reason": "店名含火锅，适合聚餐",
        }
        ok = save_draft(1, "测试店A", feature_data)
        assert ok is True

        drafts = list_drafts(status="pending", limit=10)
        assert len(drafts) == 1
        d = drafts[0]
        assert d["shop_id"] == 1
        assert d["avg_price"] == 28
        assert d["confidence"] == 0.85
        assert d["status"] == "pending"

    def test_update_status(self, monkeypatch):
        self._set_db_path(monkeypatch)
        save_draft(1, "测试店A", {"avg_price": 20, "tastes": ["清淡"], "scenes": ["一人食"], "tags": ["快餐"], "confidence": 0.6, "reason": "t"})
        drafts = list_drafts(status="pending", limit=10)
        assert len(drafts) == 1

        update_draft_status(drafts[0]["id"], "approved")
        assert len(list_drafts(status="pending", limit=10)) == 0
        assert len(list_drafts(status="approved", limit=10)) == 1

        update_draft_status(drafts[0]["id"], "rejected")
        assert list_drafts(status="rejected", limit=10)[0]["status"] == "rejected"

    def test_update_status_rejects_invalid_status(self, monkeypatch):
        self._set_db_path(monkeypatch)
        save_draft(1, "A", {"avg_price": 20, "tastes": ["light"], "scenes": ["solo"], "tags": ["fast"], "confidence": 0.6, "reason": "t"})
        draft = list_drafts(status="pending", limit=10)[0]

        with pytest.raises(ValueError):
            update_draft_status(draft["id"], "apprvoed")

        assert list_drafts(status="pending", limit=10)[0]["status"] == "pending"

    def test_approve_by_confidence(self, monkeypatch):
        self._set_db_path(monkeypatch)
        save_draft(1, "A", {"avg_price": 20, "tastes": ["清淡"], "scenes": ["一人食"], "tags": ["快餐"], "confidence": 0.9, "reason": "t"})
        save_draft(2, "B", {"avg_price": 30, "tastes": ["麻辣"], "scenes": ["夜宵"], "tags": ["火锅"], "confidence": 0.5, "reason": "t"})

        n = approve_by_confidence(0.75)
        assert n == 1  # 只有 0.9 那条

        approved = list_drafts(status="approved", limit=10)
        assert len(approved) == 1
        assert approved[0]["shop_id"] == 1

    def test_apply_approved_writes_to_shops(self, monkeypatch):
        self._set_db_path(monkeypatch)
        save_draft(1, "测试店A", {
            "avg_price": 28,
            "avg_price_min": 20,
            "avg_price_max": 35,
            "tastes": ["麻辣", "重口"],
            "scenes": ["夜宵", "同学聚餐"],
            "tags": ["火锅", "川菜"],
            "confidence": 0.88,
            "reason": "川菜馆适合聚餐",
        })
        # approve
        update_draft_status(1, "approved")

        n = apply_approved_to_shops()
        assert n == 1

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM shops WHERE id = 1").fetchone()
        conn.close()

        assert row["avg_price"] == 28
        tastes = json.loads(row["tastes"])
        assert "麻辣" in tastes
        scenes = json.loads(row["scenes"])
        assert "夜宵" in scenes

    def test_apply_approved_merges_tags_without_overwriting_existing_tags(self, monkeypatch):
        self._set_db_path(monkeypatch)
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE shops SET tags = ? WHERE id = 1", (json.dumps(["amap_keep", "shared"]),))
        conn.commit()
        conn.close()

        save_draft(1, "A", {
            "avg_price": 28,
            "tastes": ["light"],
            "scenes": ["solo"],
            "tags": ["shared", "deepseek_new"],
            "confidence": 0.88,
            "reason": "t",
        })
        update_draft_status(1, "approved")

        assert apply_approved_to_shops() == 1

        conn = sqlite3.connect(self.db_path)
        tags_json = conn.execute("SELECT tags FROM shops WHERE id = 1").fetchone()[0]
        conn.close()
        assert json.loads(tags_json) == ["amap_keep", "shared", "deepseek_new"]

    def test_apply_approved_marks_draft_as_applied(self, monkeypatch):
        self._set_db_path(monkeypatch)
        save_draft(1, "A", {"avg_price": 28, "tastes": ["light"], "scenes": ["solo"], "tags": ["fast"], "confidence": 0.88, "reason": "t"})
        update_draft_status(1, "approved")

        assert apply_approved_to_shops() == 1
        assert apply_approved_to_shops() == 0
        assert list_drafts(status="approved", limit=10) == []
        assert list_drafts(status="applied", limit=10)[0]["shop_id"] == 1

    def test_rejected_draft_not_applied(self, monkeypatch):
        self._set_db_path(monkeypatch)
        save_draft(1, "A", {"avg_price": 99, "tastes": ["清淡"], "scenes": ["一人食"], "tags": ["快餐"], "confidence": 0.3, "reason": "t"})
        update_draft_status(1, "rejected")

        n = apply_approved_to_shops()
        assert n == 0

    def test_uniqueness_per_shop_source(self, monkeypatch):
        self._set_db_path(monkeypatch)
        save_draft(1, "A", {"avg_price": 20, "tastes": ["清淡"], "scenes": ["一人食"], "tags": ["快餐"], "confidence": 0.7, "reason": "t"})
        save_draft(1, "A", {"avg_price": 35, "tastes": ["麻辣"], "scenes": ["夜宵"], "tags": ["火锅"], "confidence": 0.9, "reason": "t2"})
        # 应该覆盖而非新增
        drafts = list_drafts(limit=10)
        assert len(drafts) == 1
        assert drafts[0]["avg_price"] == 35
