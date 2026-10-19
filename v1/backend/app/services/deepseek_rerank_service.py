import json
import os
import httpx

from app.services.parser import parse_query
from app.services.recommender import recommend as rule_recommend


def ask_deepseek_rerank(query: str, uid: str = "", **kwargs) -> dict:
    # Step 1：规则引擎初排 Top 30
    slots = parse_query(query)
    candidates = rule_recommend(slots, top_k=30)
    if not candidates:
        return {"ok": False, "answer": "暂无匹配的店铺推荐", "recommendations": []}

    # Step 2：构造 Prompt
    candidate_text = _build_candidate_text(candidates)
    system_prompt = """你是成电校园餐饮推荐助手。根据用户需求，从候选店铺列表中选出最合适的 3 家。
输出格式（严格 JSON）：
{"recommendations": [
  {"name": "店名", "reason": "推荐理由", "match_score": 0.0-1.0}
]}
只输出 JSON，不要任何其他文字。只从候选列表中选，不要编造店名。"""

    user_prompt = f"用户需求：{query}\n\n候选店铺列表：\n{candidate_text}"

    # Step 3：调 DeepSeek V4 API（失败回退规则引擎）
    try:
        raw_output = _call_deepseek_api(system_prompt, user_prompt)
    except Exception:
        return _fallback_to_rules(candidates)

    # Step 4：输出清洗
    return _sanitize_or_fallback(raw_output, candidates)


def _build_candidate_text(candidates: list[dict]) -> str:
    """将候选店铺列表格式化为 LLM 可读的文本"""
    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"{i+1}. {c['name']} | {c['campus']} | "
            f"人均¥{c['avg_price']} | 标签:{c.get('tags','')} | "
            f"评分:{c['score']}"
        )
    return "\n".join(lines)


def _call_deepseek_api(system_prompt: str, user_prompt: str) -> str:
    """调 DeepSeek V4 API（非流式）"""
    endpoint = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3"))
    max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "1800"))

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _sanitize_or_fallback(raw_output: str, candidates: list[dict]) -> dict:
    """
    输出清洗：防止 LLM 编造候选列表里不存在的店名。
    如果清洗后不足 1 条，回退到规则引擎结果。
    """
    # 提取候选店名的白名单
    valid_names = {c["name"] for c in candidates}

    # 尝试解析 LLM 返回的 JSON
    try:
        # LLM 可能返回 ```json ... ``` 包裹的文本
        text = raw_output.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]  # 去第一行 ```json
            if text.endswith("```"):
                text = text[:-3]
        parsed = json.loads(text)
        items = parsed.get("recommendations", [])
        if not isinstance(items, list):
            return _fallback_to_rules(candidates)
    except (json.JSONDecodeError, AttributeError):
        # JSON 解析失败 → 回退规则引擎
        return _fallback_to_rules(candidates)

    # 白名单过滤：只保留在候选中的店名，并用本地候选数据补齐 shop_id / campus / price 等可信字段。
    candidate_by_name = {c["name"]: c for c in candidates}
    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        if name not in valid_names:
            continue

        candidate = candidate_by_name[name]
        clean.append(
            {
                **candidate,
                "reason": item.get("reason") or candidate.get("reason", ""),
                "match_score": item.get("match_score", candidate.get("score", 0)),
            }
        )

    if len(clean) < 1:
        return _fallback_to_rules(candidates)

    return {
        "ok": True,
        "answer": "",
        "recommendations": clean[:3],
        "engine": "deepseek_rerank",
    }


def _fallback_to_rules(candidates: list[dict]) -> dict:
    """LLM 输出不可用时回退规则引擎"""
    return {
        "ok": True,
        "answer": "(规则引擎结果)",
        "recommendations": candidates[:3],
        "engine": "rule-based-fallback",
    }
