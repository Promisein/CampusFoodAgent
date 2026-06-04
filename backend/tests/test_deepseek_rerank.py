"""DeepSeek Rerank 单元测试 —— 覆盖输出清洗、白名单过滤、回退逻辑"""
import json

import pytest

from app.services.deepseek_rerank_service import (
    ask_deepseek_rerank,
    _sanitize_or_fallback,
    _fallback_to_rules,
    _build_candidate_text,
)


# ---- 测试辅助：构造 mock candidates ----

def _make_candidates(*names: str) -> list[dict]:
    """构造与规则引擎输出格式一致的候选列表"""
    return [
        {"name": name, "campus": "清水河", "avg_price": 15,
         "tags": "面食", "score": 0.8}
        for name in names
    ]


# ---- _build_candidate_text ----

def test_build_candidate_text_formats_lines():
    candidates = _make_candidates("学子餐厅", "银桦餐厅")
    text = _build_candidate_text(candidates)
    assert "学子餐厅" in text
    assert "银桦餐厅" in text
    assert "清水河" in text
    assert "人均¥15" in text


# ---- _fallback_to_rules ----

def test_fallback_returns_top_3():
    candidates = _make_candidates("A", "B", "C", "D", "E")
    result = _fallback_to_rules(candidates)
    assert result["ok"] is True
    assert result["engine"] == "rule-based-fallback"
    assert result["answer"] == "(规则引擎结果)"
    assert len(result["recommendations"]) == 3
    assert result["recommendations"][0]["name"] == "A"


def test_fallback_with_fewer_than_3():
    candidates = _make_candidates("A", "B")
    result = _fallback_to_rules(candidates)
    assert len(result["recommendations"]) == 2


# ---- _sanitize_or_fallback: 正常 JSON ----

def test_sanitize_valid_json_output():
    """标准 JSON 格式的 LLM 输出被正确解析"""
    candidates = _make_candidates("学子餐厅", "银桦餐厅", "清真食堂")
    raw = json.dumps({
        "recommendations": [
            {"name": "学子餐厅", "reason": "便宜实惠", "match_score": 0.9},
            {"name": "银桦餐厅", "reason": "清淡健康", "match_score": 0.85},
        ]
    })
    result = _sanitize_or_fallback(raw, candidates)
    assert result["ok"] is True
    assert result["engine"] == "deepseek_rerank"
    assert result["answer"] == ""
    assert len(result["recommendations"]) == 2
    assert result["recommendations"][0]["name"] == "学子餐厅"
    assert result["recommendations"][0]["campus"] == "清水河"
    assert result["recommendations"][0]["avg_price"] == 15
    assert result["recommendations"][0]["score"] == 0.8
    assert result["recommendations"][0]["match_score"] == 0.9


def test_sanitize_markdown_wrapped_json():
    """LLM 经常返回 ```json ... ``` 包裹的 JSON"""
    candidates = _make_candidates("学子餐厅", "银桦餐厅", "清真食堂")
    raw = '```json\n{"recommendations": [{"name": "学子餐厅", "reason": "便宜实惠", "match_score": 0.9}]}\n```'
    result = _sanitize_or_fallback(raw, candidates)
    assert result["ok"] is True
    assert result["engine"] == "deepseek_rerank"
    assert len(result["recommendations"]) == 1


def test_sanitize_truncates_to_3():
    """无论 LLM 返回多少条，最终只保留前 3 条"""
    candidates = _make_candidates("A", "B", "C", "D", "E")
    raw = json.dumps({
        "recommendations": [
            {"name": name, "reason": "test", "match_score": 0.9}
            for name in ["A", "B", "C", "D", "E"]
        ]
    })
    result = _sanitize_or_fallback(raw, candidates)
    assert result["ok"] is True
    assert len(result["recommendations"]) == 3


# ---- _sanitize_or_fallback: 防幻觉（白名单过滤） ----

def test_filters_hallucinated_store_entirely():
    """LLM 完全编造了不存在的店名 → 全部被过滤 → 回退规则引擎"""
    candidates = _make_candidates("学子餐厅", "银桦餐厅", "清真食堂")
    raw = json.dumps({
        "recommendations": [
            {"name": "银杏餐厅", "reason": "环境好", "match_score": 0.95},
            {"name": "芙蓉餐厅", "reason": "味道好", "match_score": 0.9},
        ]
    })
    result = _sanitize_or_fallback(raw, candidates)
    assert result["engine"] == "rule-based-fallback"
    # 回退结果来自真实候选
    for r in result["recommendations"]:
        assert r["name"] in {"学子餐厅", "银桦餐厅", "清真食堂"}


def test_filters_hallucinated_store_partial():
    """LLM 混合返回了真实店名和编造店名 → 只保留真实店名"""
    candidates = _make_candidates("学子餐厅", "银桦餐厅", "清真食堂")
    raw = json.dumps({
        "recommendations": [
            {"name": "银杏餐厅", "reason": "虚构的店", "match_score": 0.95},
            {"name": "学子餐厅", "reason": "真实存在的店", "match_score": 0.9},
        ]
    })
    result = _sanitize_or_fallback(raw, candidates)
    assert result["ok"] is True
    assert result["engine"] == "deepseek_rerank"
    assert len(result["recommendations"]) == 1
    assert result["recommendations"][0]["name"] == "学子餐厅"


# ---- _sanitize_or_fallback: 异常输入回退 ----

def test_malformed_json_fallback():
    """LLM 返回的不是合法 JSON → 回退规则引擎"""
    candidates = _make_candidates("学子餐厅", "银桦餐厅", "清真食堂")
    raw = "抱歉，我无法理解你的需求..."
    result = _sanitize_or_fallback(raw, candidates)
    assert result["engine"] == "rule-based-fallback"
    assert len(result["recommendations"]) == 3


def test_empty_string_fallback():
    """LLM 返回空字符串 → 回退"""
    result = _sanitize_or_fallback("", _make_candidates("A", "B", "C"))
    assert result["engine"] == "rule-based-fallback"


def test_json_without_recommendations_key():
    """LLM 返回了 JSON 但没有 recommendations 字段"""
    candidates = _make_candidates("学子餐厅", "银桦餐厅")
    raw = '{"answer": "推荐学子餐厅"}'
    result = _sanitize_or_fallback(raw, candidates)
    assert result["engine"] == "rule-based-fallback"


def test_recommendations_not_a_list():
    """recommendations 字段不是数组"""
    candidates = _make_candidates("学子餐厅", "银桦餐厅")
    raw = '{"recommendations": "学子餐厅"}'
    result = _sanitize_or_fallback(raw, candidates)
    assert result["engine"] == "rule-based-fallback"


# ---- _sanitize_or_fallback: 白名单为空的边界情况 ----

def test_empty_candidates_with_non_empty_output():
    """候选列表为空 + LLM 返回了内容 → 回退（但候选也为空）"""
    result = _sanitize_or_fallback(
        json.dumps({"recommendations": [{"name": "X"}]}),
        [],
    )
    assert result["engine"] == "rule-based-fallback"
    assert result["recommendations"] == []


# ---- ask_deepseek_rerank: API 失败直接回退 ----

def test_api_call_failure_falls_back_to_rules(monkeypatch):
    """_call_deepseek_api 抛异常 → ask_deepseek_rerank 不崩，返回规则引擎兜底"""
    def mock_api_fail(*args, **kwargs):
        raise ConnectionError("模拟网络故障")

    monkeypatch.setattr(
        "app.services.deepseek_rerank_service._call_deepseek_api",
        mock_api_fail,
    )

    result = ask_deepseek_rerank(query="清水河吃面")
    assert result["ok"] is True
    assert result["engine"] == "rule-based-fallback"
    assert len(result["recommendations"]) >= 1
