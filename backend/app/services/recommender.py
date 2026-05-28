import json

from app.core.scoring_config import load_scoring_config
from app.services.parser import ParsedSlots
from app.services.shop_repository import fetch_active_shops


def recommend(parsed: ParsedSlots, top_k: int = 3) -> list[dict]:
    shops = fetch_active_shops()
    if not shops:
        return []

    config = load_scoring_config()
    weights = config["weights"]
    time_slots = config["time_slot_ranges"]
    scene_aliases = config["scene_aliases"]

    scored: list[dict] = []
    for shop in shops:
        score, matched = _score_shop(shop, parsed, weights, time_slots, scene_aliases)
        if matched or parsed.budget_max is None:
            # 至少有一项匹配才返回（或者用户没设任何条件）
            scored.append({
                "shop_id": shop["id"],
                "name": shop["name"],
                "campus": shop["campus"],
                "area": shop.get("area", ""),
                "avg_price": shop["avg_price"],
                "tags": shop.get("tags", ""),
                "score": round(score, 4),
                "reason": _build_reason(shop, parsed, matched, score),
            })

    scored.sort(key=lambda x: (-x["score"], x["avg_price"] or 999, x["shop_id"]))
    return scored[:top_k]


def _score_shop(shop: dict, slots: ParsedSlots, weights: dict, time_slots: dict, scene_aliases: dict) -> tuple[float, list[str]]:
    total = 0.0
    matched: list[str] = []

    # 基础分
    total += weights.get("base_score", 0.15)

    # 1. 预算匹配：预算内统一给满分，越便宜附加分越高
    if slots.budget_max is not None and shop.get("avg_price"):
        price = shop["avg_price"]
        if price <= slots.budget_max:
            total += weights["budget"]
            matched.append("budget")
            # 越便宜附加分越高
            price_bonus = max(0, 1.0 - price / slots.budget_max) * weights.get("budget_bonus", 0.03)
            total += price_bonus

    # 2. 校区匹配
    if slots.location:
        campus_text = f"{shop.get('campus', '')} {shop.get('area', '')}"
        if slots.location in campus_text:
            total += weights["location"]
            matched.append("location")

    # 3. 口味匹配
    if slots.taste:
        shop_tastes = _parse_json_field(shop.get("tastes", ""))
        if slots.taste in shop_tastes or slots.taste in str(shop_tastes):
            total += weights["taste"]
            matched.append("taste")

    # 4. 场景匹配（支持别名）
    if slots.scene:
        shop_scenes = _parse_json_field(shop.get("scenes", ""))
        aliases = scene_aliases.get(slots.scene, [slots.scene])
        if any(a in str(shop_scenes) for a in aliases):
            total += weights["scene"]
            matched.append("scene")

    # 5. 时间匹配
    if slots.time:
        open_str = shop.get("open_hours", "")
        if _is_open_during(open_str, slots.time, time_slots):
            total += weights["time"]
            matched.append("time")

    return min(total, 0.99), matched


def _parse_json_field(val) -> list:
    """安全解析 JSON 数组字段"""
    if not val:
        return []
    try:
        return json.loads(val) if isinstance(val, str) else val
    except (json.JSONDecodeError, TypeError):
        return [val]


def _is_open_during(open_hours: str, slot_name: str, time_slots: dict) -> bool:
    """判断店铺在指定时段是否营业（简单版本）"""
    if not open_hours:
        return True  # 没填营业时间则不筛选
    ranges = time_slots.get(slot_name)
    if not ranges:
        return True
    # 简化处理：只要时段起止时间与营业时间有重叠就算
    slot_start_h, slot_start_m = map(int, ranges[0].split(":"))
    slot_end_h, slot_end_m = map(int, ranges[1].split(":"))
    try:
        open_start, open_end = open_hours.split("-")
        oh, om = map(int, open_start.strip().split(":"))
        ch, cm = map(int, open_end.strip().split(":"))
        shop_open_min = oh * 60 + om
        shop_close_min = ch * 60 + cm
        # 跨午夜修正：打烊时间 < 开门时间说明营业到次日（如 10:00-02:00）
        if shop_close_min < shop_open_min:
            shop_close_min += 24 * 60
        slot_open_min = slot_start_h * 60 + slot_start_m
        slot_close_min = slot_end_h * 60 + slot_end_m
        # 有重叠
        return shop_open_min <= slot_close_min and shop_close_min >= slot_open_min
    except (ValueError, AttributeError):
        return True


def _build_reason(shop: dict, slots: ParsedSlots, matched: list[str], score: float) -> str:
    """生成人类可读的推荐理由"""
    parts = []
    field_names = {"budget": "预算匹配", "location": "校区匹配", "taste": "口味匹配", "scene": "场景匹配", "time": "营业时间匹配"}
    for m in matched:
        if m in field_names:
            parts.append(field_names[m])
    if not parts:
        return "综合推荐"
    return "，".join(parts) + f"（综合评分 {score:.2f}）"
