"""从用户查询中提取分类意图关键词"""

_CATEGORY_KEYWORDS = {
    "面食": ["面", "拉面", "刀削面", "拌面", "凉面", "米线", "抄手", "饺子"],
    "米饭": ["盖饭", "炒饭", "拌饭", "套餐", "盖浇", "米饭"],
    "火锅": ["火锅", "串串", "冒菜", "麻辣烫", "串串香"],
    "川菜": ["川菜", "炒菜", "回锅肉", "宫保", "水煮", "麻婆"],
    "小吃": ["小吃", "烧烤", "炸鸡", "奶茶", "奶茶店", "冰粉", "凉皮"],
    "汤品": ["汤", "炖", "粥", "砂锅", "炖盅", "汤锅"],
    "快餐": ["快餐", "盒饭", "便当", "食堂"],
}


def extract_query_intents(query: str) -> list[str]:
    """提取查询中的分类意图"""
    found = []
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                found.append(category)
                break
    return found


def build_query_with_intent_hint(query: str) -> str:
    """构建带意图增强的查询文本"""
    intents = extract_query_intents(query)
    if not intents:
        return query
    return f"{query}（想吃：{'、'.join(intents)}）"
