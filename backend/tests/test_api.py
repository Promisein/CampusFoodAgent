"""API 层测试 —— 验证 HTTP 接口的状态码、响应格式和校验逻辑"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestHealthAPI:
    """健康检查端点"""

    def test_health_ok(self):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestRecommendAPI:
    """核心推荐端点"""

    def test_recommend_success(self):
        """正常请求返回完整三部分"""
        r = client.post("/api/v1/recommend", json={
            "query": "清水河 预算25 清淡 一个人",
            "top_k": 3,
        })
        assert r.status_code == 200
        data = r.json()
        assert "parsed" in data
        assert "recommendations" in data
        assert "meta" in data
        assert data["parsed"]["budget_max"] == 25.0
        assert data["parsed"]["location"] == "清水河"
        assert data["meta"]["engine"] == "rule-based"
        assert data["meta"]["returned"] == len(data["recommendations"])
        assert 1 <= data["meta"]["returned"] <= 3

    def test_recommend_default_top_k(self):
        """不传 top_k 时默认返回 3 家"""
        r = client.post("/api/v1/recommend", json={"query": "随便"})
        assert r.status_code == 200
        assert r.json()["meta"]["returned"] <= 3

    def test_recommend_empty_query_422(self):
        """空 query 被 Pydantic min_length=1 拦截"""
        r = client.post("/api/v1/recommend", json={"query": ""})
        assert r.status_code == 422

    def test_recommend_top_k_0_422(self):
        """top_k < 1 被 Pydantic ge=1 拦截"""
        r = client.post("/api/v1/recommend", json={
            "query": "清水河",
            "top_k": 0,
        })
        assert r.status_code == 422

    def test_recommend_top_k_11_422(self):
        """top_k > 10 被 Pydantic le=10 拦截"""
        r = client.post("/api/v1/recommend", json={
            "query": "清水河",
            "top_k": 11,
        })
        assert r.status_code == 422

    def test_recommend_respects_top_k(self):
        """返回数量不超过 top_k"""
        r = client.post("/api/v1/recommend", json={
            "query": "随便",
            "top_k": 1,
        })
        assert r.status_code == 200
        assert len(r.json()["recommendations"]) <= 1


class TestStoreDetailAPI:
    """店铺详情端点"""

    def test_store_detail_found(self):
        r = client.get("/api/v1/stores/detail?name=学子餐厅")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "学子餐厅"
        assert data["campus"] == "清水河"
        assert isinstance(data["tastes"], list)
        assert isinstance(data["scenes"], list)
        assert isinstance(data["image_urls"], list)
        # 内部字段不应泄露
        assert "created_at" not in data
        assert "updated_at" not in data
        assert "poi_id" not in data

    def test_store_detail_404(self):
        r = client.get("/api/v1/stores/detail?name=不存在的餐厅")
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_store_detail_empty_name_422(self):
        """空 name 被 Query(min_length=1) 拦截"""
        r = client.get("/api/v1/stores/detail?name=")
        assert r.status_code == 422


class TestStoreSuggestAPI:
    """店名自动补全端点"""

    def test_store_suggest_exact_match(self):
        r = client.get("/api/v1/stores/suggest?keyword=龙湖米线")
        assert r.status_code == 200
        data = r.json()
        assert "suggestions" in data
        assert "龙湖米线" in data["suggestions"]

    def test_store_suggest_partial_match(self):
        r = client.get("/api/v1/stores/suggest?keyword=龙湖")
        assert r.status_code == 200
        names = r.json()["suggestions"]
        assert len(names) >= 2
        assert "龙湖米线" in names
        assert "龙湖火锅" in names

    def test_store_suggest_no_match(self):
        r = client.get("/api/v1/stores/suggest?keyword=xyz123")
        assert r.status_code == 200
        assert r.json()["suggestions"] == []

    def test_store_suggest_empty_keyword_422(self):
        r = client.get("/api/v1/stores/suggest?keyword=")
        assert r.status_code == 422


class TestRankingsAPI:
    """热门排行端点"""

    def test_rankings_today_ok(self):
        r = client.get("/api/v1/rankings/today")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "generated_at" in data
        assert len(data["items"]) >= 1
        # 验证每个 item 的结构
        item = data["items"][0]
        assert "rank" in item
        assert "name" in item
        assert "tag" in item
        assert "avg_price" in item
        assert "query" in item

    def test_rankings_are_sorted_by_rank(self):
        r = client.get("/api/v1/rankings/today")
        items = r.json()["items"]
        ranks = [item["rank"] for item in items]
        assert ranks == sorted(ranks)
