"""Scan shops for missing recommendation features and compute data quality scores."""
import json


# ---- 白名单 ----
TASTE_WHITELIST = {
    "清淡", "麻辣", "微辣", "重口", "鲜香", "酸辣",
    "甜口", "咸鲜", "家常", "油香", "咖啡", "奶香", "冰爽",
}

SCENE_WHITELIST = {
    "一人食", "同学聚餐", "情侣约饭", "赶时间", "夜宵",
    "早餐", "午餐", "晚餐", "下午茶", "宿舍外卖", "健身餐",
    "低预算", "高性价比", "校内就近", "西门周边", "龙湖周边",
}

TAG_WHITELIST = {
    "食堂", "咖啡", "奶茶", "米线", "面食", "粉面", "快餐",
    "川菜", "烧烤", "火锅", "炸鸡", "甜品", "小吃", "盖饭",
    "性价比", "出餐快", "适合学生",
}

AMAP_AUTO_TAGS = {"高德POI"}


def _json_list_parse(raw: str | None) -> list:
    """安全解析 JSON 数组字段."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _is_auto_tag(tag: str) -> bool:
    """判断单个 tag 是否为高德自动标签（"高德POI" 或纯数字 typecode）."""
    if tag in AMAP_AUTO_TAGS:
        return True
    # typecode 如 "050100"、"050200" 等是纯数字
    return tag.isdigit()


def _only_amap_tags(tags_str: str | None) -> bool:
    """tags 只有高德自动标签（无人工/DeepSeek 标签）."""
    tags = _json_list_parse(tags_str)
    if not tags:
        return True
    non_amap = [t for t in tags if not _is_auto_tag(t)]
    return len(non_amap) == 0


def needs_feature_completion(shop: dict) -> bool:
    """判断一条店铺是否需要补推荐特征."""
    if shop.get("avg_price") is None:
        return True
    if not _json_list_parse(shop.get("tastes")):
        return True
    if not _json_list_parse(shop.get("scenes")):
        return True
    if _only_amap_tags(shop.get("tags")):
        return True
    return False


def list_missing_fields(shop: dict) -> list[str]:
    """列出店铺缺失的特征字段."""
    missing = []
    if shop.get("avg_price") is None:
        missing.append("avg_price")
    if not _json_list_parse(shop.get("tastes")):
        missing.append("tastes")
    if not _json_list_parse(shop.get("scenes")):
        missing.append("scenes")
    if _only_amap_tags(shop.get("tags")):
        missing.append("tags")
    return missing


def compute_data_quality_score(shop: dict) -> int:
    """
    计算数据质量分（0-100）。
    基础字段完整度 40 分 + 推荐字段完整度 50 分 + 人工确认加分 10 分。
    """
    score = 0

    # 基础字段（40 分）
    if shop.get("name"):
        score += 10
    if shop.get("category"):
        score += 10
    if shop.get("address"):
        score += 10
    if shop.get("latitude") is not None and shop.get("longitude") is not None:
        score += 10

    # 推荐字段（50 分）
    if shop.get("avg_price") is not None:
        score += 15
    if _json_list_parse(shop.get("tastes")):
        score += 10
    if _json_list_parse(shop.get("scenes")):
        score += 10
    # tags 不只高德自动标签
    if not _only_amap_tags(shop.get("tags")):
        score += 10
    # 有 rating 加 5
    if shop.get("rating") is not None:
        score += 5

    # 人工确认加分（10 分）：这里保守处理，有业务标签即算
    has_manual = shop.get("avg_price") is not None and \
        _json_list_parse(shop.get("tastes")) and \
        _json_list_parse(shop.get("scenes"))
    if has_manual:
        score += 10

    return min(score, 100)


def is_recommendable(shop: dict) -> bool:
    """判断店铺是否可以进入推荐池."""
    return compute_data_quality_score(shop) >= 70
