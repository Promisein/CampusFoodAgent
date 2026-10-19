"""DeepSeek 半自动生成推荐候选特征 —— Prompt 构造 + JSON 解析 + 白名单校验."""
import json
import re

from app.services.deepseek_service import ask_deepseek
from app.services.feature_gap_service import (
    SCENE_WHITELIST,
    TAG_WHITELIST,
    TASTE_WHITELIST,
)

FEATURE_PROMPT = """你是校园餐饮推荐系统的数据标注助手。

请根据以下店铺基础信息，为它生成"候选推荐特征"。
注意：
1. 你只能根据店名、类别、地址进行合理推断。
2. 不要编造真实评分、真实评论数、真实营业时间。
3. 人均价格只能给估算范围。
4. tastes、scenes、tags 必须从给定白名单中选择。
5. 输出必须是合法 JSON，不要输出 Markdown。

店铺信息：
- name: {name}
- campus: {campus}
- area: {area}
- address: {address}
- category: {category}
- tags: {tags}

口味白名单（tastes 从中选 1-4 个）：
{TASTE_LIST}

场景白名单（scenes 从中选 1-4 个）：
{SCENE_LIST}

标签白名单（tags 从中选 2-5 个）：
{TAG_LIST}

请输出：
{{
  "avg_price": <number>,
  "avg_price_min": <number>,
  "avg_price_max": <number>,
  "tastes": ["...", "..."],
  "scenes": ["...", "..."],
  "tags": ["...", "..."],
  "confidence": <0.0-1.0>,
  "reason": "<一句话说明你的判断依据>"
}}"""


def _build_whitelist_text(whitelist: set[str]) -> str:
    return json.dumps(sorted(whitelist), ensure_ascii=False)


def build_feature_prompt(shop: dict) -> str:
    """根据店铺信息构造补齐特征的 Prompt."""
    return FEATURE_PROMPT.format(
        name=shop.get("name") or "",
        campus=shop.get("campus") or "未知",
        area=shop.get("area") or "未知",
        address=shop.get("address") or "未知",
        category=shop.get("category") or "未知",
        tags=shop.get("tags") or "[]",
        TASTE_LIST=_build_whitelist_text(TASTE_WHITELIST),
        SCENE_LIST=_build_whitelist_text(SCENE_WHITELIST),
        TAG_LIST=_build_whitelist_text(TAG_WHITELIST),
    )


def _extract_json(text: str) -> str | None:
    """从 LLM 输出中提取 JSON（容错 Markdown 代码块包裹）."""
    # 尝试直接解析
    text = text.strip()
    if text.startswith("{"):
        return text

    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)

    # 尝试找到第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]

    return None


def parse_and_validate(llm_output: str) -> dict | None:
    """
    解析 DeepSeek 输出并做白名单校验。
    返回 None 表示解析失败或全部字段非法。
    """
    json_str = _extract_json(llm_output)
    if not json_str:
        return None

    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    result: dict = {"confidence": 0.0, "reason": ""}

    # avg_price: 必须在 1-200 之间
    price = raw.get("avg_price")
    if isinstance(price, (int, float)) and 1 <= price <= 200:
        result["avg_price"] = float(price)
    else:
        result["avg_price"] = None

    # avg_price_min
    p_min = raw.get("avg_price_min")
    if isinstance(p_min, (int, float)) and 1 <= p_min <= 200:
        result["avg_price_min"] = float(p_min)
    else:
        result["avg_price_min"] = None

    # avg_price_max
    p_max = raw.get("avg_price_max")
    if isinstance(p_max, (int, float)) and 1 <= p_max <= 200:
        result["avg_price_max"] = float(p_max)
    else:
        result["avg_price_max"] = None

    # 确保 min <= avg <= max
    if result["avg_price"] is not None:
        if result["avg_price_min"] is not None and result["avg_price"] < result["avg_price_min"]:
            result["avg_price_min"] = result["avg_price"]
        if result["avg_price_max"] is not None and result["avg_price"] > result["avg_price_max"]:
            result["avg_price_max"] = result["avg_price"]

    # tastes: 白名单过滤
    tastes = raw.get("tastes")
    result["tastes"] = []
    if isinstance(tastes, list):
        result["tastes"] = [t for t in tastes if t in TASTE_WHITELIST][:5]

    # scenes: 白名单过滤
    scenes = raw.get("scenes")
    result["scenes"] = []
    if isinstance(scenes, list):
        result["scenes"] = [s for s in scenes if s in SCENE_WHITELIST][:5]

    # tags: 白名单过滤
    tags = raw.get("tags")
    result["tags"] = []
    if isinstance(tags, list):
        result["tags"] = [t for t in tags if t in TAG_WHITELIST][:6]

    # confidence
    conf = raw.get("confidence")
    if isinstance(conf, (int, float)) and 0 <= conf <= 1:
        result["confidence"] = float(conf)

    # reason
    reason = raw.get("reason")
    if isinstance(reason, str) and len(reason) <= 500:
        result["reason"] = reason
    elif isinstance(reason, str):
        result["reason"] = reason[:500]

    # 至少要有价格或标签才算有效
    has_price = result["avg_price"] is not None
    has_labels = result["tastes"] or result["scenes"] or result["tags"]
    if not has_price and not has_labels:
        return None

    return result


def generate_feature_draft(shop: dict) -> dict | None:
    """
    用 DeepSeek 为一家店生成候选特征。
    返回 None 表示生成失败，否则返回 parse_and_validate 的结果。
    """
    prompt = build_feature_prompt(shop)
    resp = ask_deepseek(prompt)
    if not resp.get("ok"):
        return None

    return parse_and_validate(resp["answer"])
