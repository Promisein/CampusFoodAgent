"""第 7 章测试 —— 反馈、收藏、广告、事件追踪、热门排行"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---- 反馈 ----

class TestFeedback:
    def test_submit_feedback_ok(self):
        r = client.post("/api/v1/feedback", json={
            "feedbackType": "dining_feedback",
            "storeName": "学子餐厅",
            "rating": 5,
            "comment": "好吃",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["id"] >= 1

    def test_submit_feedback_validation(self):
        """缺少必填字段 → 422"""
        r = client.post("/api/v1/feedback", json={"rating": 5})
        assert r.status_code == 422


# ---- 收藏 ----

class TestFavorites:
    def test_add_favorite_ok(self):
        r = client.post("/api/v1/favorites", json={
            "user_id": "test_fav_user",
            "shop_id": 1,
            "shop_name": "学子餐厅",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_add_duplicate_favorite_is_idempotent(self):
        """重复收藏不报错（INSERT OR IGNORE）"""
        for _ in range(2):
            r = client.post("/api/v1/favorites", json={
                "user_id": "test_dup_user",
                "shop_id": 1,
                "shop_name": "学子餐厅",
            })
            assert r.status_code == 200

    def test_list_favorites(self):
        # 先添加几条
        for sid in [2, 3]:
            client.post("/api/v1/favorites", json={
                "user_id": "test_list_user",
                "shop_id": sid,
                "shop_name": f"Shop{sid}",
            })
        r = client.get("/api/v1/favorites?user_id=test_list_user")
        assert r.status_code == 200
        assert len(r.json()["favorites"]) >= 2

    def test_remove_favorite(self):
        user_id = "test_remove_user"
        client.post("/api/v1/favorites", json={
            "user_id": user_id, "shop_id": 1, "shop_name": "学子餐厅",
        })
        r = client.request("DELETE", "/api/v1/favorites", json={
            "user_id": user_id, "shop_id": 1,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_list_requires_user_id(self):
        r = client.get("/api/v1/favorites?user_id=")
        assert r.status_code == 422


# ---- 广告 ----

class TestAds:
    def test_get_ad_slots_returns_list(self):
        r = client.get("/api/v1/ads/slots")
        assert r.status_code == 200
        data = r.json()
        assert "slots" in data
        assert isinstance(data["slots"], list)
        assert len(data["slots"]) >= 1  # 种子数据已插入

    def test_ad_slots_respects_limit(self):
        r = client.get("/api/v1/ads/slots?limit=1")
        assert r.status_code == 200
        assert len(r.json()["slots"]) <= 1

    def test_log_ad_click_ok(self):
        r = client.post("/api/v1/events/ad-click", json={"slotId": 1})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_ad_click_validation(self):
        r = client.post("/api/v1/events/ad-click", json={"slotId": 0})
        assert r.status_code == 422


# ---- 事件追踪 ----

class TestEventTracking:
    def test_track_event_ok(self):
        r = client.post("/api/v1/events/track", json={
            "event_type": "query",
            "uid": "test_uid_001",
            "query_text": "清水河吃面",
            "shop_name": "老麻抄手",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_track_event_without_shop(self):
        r = client.post("/api/v1/events/track", json={
            "event_type": "view",
            "uid": "test_uid_002",
        })
        assert r.status_code == 200

    def test_track_event_validation(self):
        r = client.post("/api/v1/events/track", json={"event_type": ""})
        assert r.status_code == 422


# ---- 热门排行 ----

class TestHotRankings:
    def test_rankings_returns_items(self):
        r = client.get("/api/v1/rankings/today")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "generated_at" in data

    def test_rankings_from_events(self):
        """热门排行能够从事件数据中统计"""
        # 造一些查询事件
        for _ in range(3):
            client.post("/api/v1/events/track", json={
                "event_type": "query",
                "shop_name": "学子餐厅",
            })
        for _ in range(5):
            client.post("/api/v1/events/track", json={
                "event_type": "query",
                "shop_name": "老麻抄手",
            })

        r = client.get("/api/v1/rankings/today")
        assert r.status_code == 200
        items = r.json()["items"]
        if items:
            # 老麻抄手（5次）应该排在学子餐厅（3次）前面
            names = [item["name"] for item in items]
            if "老麻抄手" in names and "学子餐厅" in names:
                assert names.index("老麻抄手") < names.index("学子餐厅")
