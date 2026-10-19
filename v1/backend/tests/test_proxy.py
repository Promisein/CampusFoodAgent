"""API 层测试 —— /api/recommend 三模式分发 + 容错回退"""
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestProxyRecommendRuleFallback:
    """规则引擎兜底模式"""

    def test_rule_fallback_returns_recommendations(self, monkeypatch):
        """未配置 provider 时走规则引擎兜底，返回 OK"""
        monkeypatch.setenv("RECOMMEND_PROVIDER", "")
        r = client.post("/api/recommend", json={"query": "清水河吃面 20块"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["recommendations"]) == 3
        for rec in data["recommendations"]:
            assert "name" in rec
            assert "reason" in rec
            assert "match_score" in rec

    def test_rule_fallback_respects_top_k(self, monkeypatch):
        monkeypatch.setenv("RECOMMEND_PROVIDER", "")
        r = client.post("/api/recommend", json={"query": "随便", "top_k": 2})
        assert r.status_code == 200
        assert len(r.json()["recommendations"]) <= 2

    def test_empty_query_422(self, monkeypatch):
        monkeypatch.setenv("RECOMMEND_PROVIDER", "")
        r = client.post("/api/recommend", json={"query": ""})
        assert r.status_code == 422


class TestProxyDeepSeekApiMode:
    """deepseek_api 模式 —— monkeypatch ask_deepseek"""

    def test_api_mode_returns_llm_response(self, monkeypatch):
        """模拟 DeepSeek API 正常返回"""
        monkeypatch.setenv("RECOMMEND_PROVIDER", "deepseek_api")

        def mock_ask_deepseek(query, uid="", history=None, parameters=None, stream=False):
            return {
                "ok": True,
                "answer": "推荐你去学子餐厅，便宜实惠",
                "code": 0,
                "finish_reason": "stop",
            }

        monkeypatch.setattr(
            "app.api.proxy_routes.ask_deepseek", mock_ask_deepseek
        )

        r = client.post("/api/recommend", json={"query": "清水河吃面"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "学子餐厅" in data["answer"]
        assert data["finishReason"] == "stop"

    def test_api_mode_handles_service_error(self, monkeypatch):
        """DeepSeek API 返回错误时代理路由正常透传"""
        monkeypatch.setenv("RECOMMEND_PROVIDER", "deepseek_api")

        def mock_ask_deepseek(query, uid="", history=None, parameters=None, stream=False):
            return {
                "ok": False,
                "answer": "",
                "error": "Connection timeout",
                "code": -1,
            }

        monkeypatch.setattr(
            "app.api.proxy_routes.ask_deepseek", mock_ask_deepseek
        )

        r = client.post("/api/recommend", json={"query": "随便"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["error"] == "Connection timeout"
        assert data["code"] == -1

    def test_api_mode_injects_intent_hint(self, monkeypatch):
        """验证意图增强后的查询被传给 ask_deepseek"""
        monkeypatch.setenv("RECOMMEND_PROVIDER", "deepseek_api")

        received_query = {}

        def mock_ask_deepseek(query, uid="", history=None, parameters=None, stream=False):
            received_query["query"] = query
            received_query["params"] = parameters
            return {"ok": True, "answer": "好的", "code": 0, "finish_reason": "stop"}

        monkeypatch.setattr(
            "app.api.proxy_routes.ask_deepseek", mock_ask_deepseek
        )

        client.post("/api/recommend", json={"query": "想吃面"})
        # 查询应该被意图增强
        assert "面食" in received_query["query"]
        # AGENT_CATEGORY_KEYWORDS 应该包含面食
        assert "面食" in received_query["params"].get("AGENT_CATEGORY_KEYWORDS", "")


class TestProxyDeepSeekRerankMode:
    """deepseek_rerank 模式 —— monkeypatch ask_deepseek_rerank"""

    def test_rerank_mode_returns_filtered_results(self, monkeypatch):
        """模拟 Rerank 正常返回"""
        monkeypatch.setenv("RECOMMEND_PROVIDER", "deepseek_rerank")

        def mock_ask_deepseek_rerank(query, uid="", **kwargs):
            return {
                "ok": True,
                "answer": '{"recommendations": [...]}',
                "recommendations": [
                    {"name": "学子餐厅", "reason": "便宜实惠", "match_score": 0.95},
                    {"name": "银桦餐厅", "reason": "清淡健康", "match_score": 0.88},
                ],
                "engine": "deepseek_rerank",
            }

        monkeypatch.setattr(
            "app.api.proxy_routes.ask_deepseek_rerank", mock_ask_deepseek_rerank
        )

        r = client.post("/api/recommend", json={"query": "清水河吃面"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["recommendations"]) == 2
        assert data["recommendations"][0]["name"] == "学子餐厅"

    def test_rerank_mode_fallback_when_service_fails(self, monkeypatch):
        """Rerank 服务内部失败时按规则回退结果返回"""
        monkeypatch.setenv("RECOMMEND_PROVIDER", "deepseek_rerank")

        def mock_ask_deepseek_rerank(query, uid="", **kwargs):
            return {
                "ok": True,
                "answer": "(规则引擎结果)",
                "recommendations": [
                    {"name": "银桦餐厅", "reason": "规则兜底", "match_score": 0.56},
                ],
                "engine": "rule-based-fallback",
            }

        monkeypatch.setattr(
            "app.api.proxy_routes.ask_deepseek_rerank", mock_ask_deepseek_rerank
        )

        r = client.post("/api/recommend", json={"query": "随便"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["recommendations"]) >= 1

    def test_rerank_mode_passes_uid(self, monkeypatch):
        """验证 uid 和 userId 被正确传递给 rerank 服务"""
        monkeypatch.setenv("RECOMMEND_PROVIDER", "deepseek_rerank")

        received_kwargs = {}

        def mock_ask_deepseek_rerank(query, uid="", **kwargs):
            received_kwargs["uid"] = uid
            received_kwargs["kwargs"] = kwargs
            return {
                "ok": True,
                "answer": "",
                "recommendations": [],
                "engine": "deepseek_rerank",
            }

        monkeypatch.setattr(
            "app.api.proxy_routes.ask_deepseek_rerank", mock_ask_deepseek_rerank
        )

        client.post("/api/recommend", json={
            "query": "吃面",
            "uid": "test_uid_123",
            "userId": "user_456",
        })
        assert received_kwargs["uid"] == "test_uid_123"
        assert received_kwargs["kwargs"].get("user_id") == "user_456"
