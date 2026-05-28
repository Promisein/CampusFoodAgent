import re
from dataclasses import dataclass

from app.core.scoring_config import load_scoring_config


@dataclass
class ParsedSlots:
    budget_max: float | None = None
    location: str | None = None
    scene: str | None = None
    taste: str | None = None
    time: str | None = None


# ---- 规则字典 ----
_LOCATIONS = [
    ("清水河", ["清水河", "清水", "清溪"]),
    ("沙河", ["沙河"]),
]

_TASTES = [
    ("清淡", ["清淡", "不辣", "清谈", "不油"]),
    ("麻辣", ["麻辣", "辣", "重口", "重口味", "香辣"]),
    ("鲜美", ["鲜美", "鲜", "鲜香", "好吃"]),
]

_TIMES = [
    ("早餐", ["早餐", "早饭", "早上"]),
    ("午餐", ["午餐", "午饭", "中午"]),
    ("晚餐", ["晚餐", "晚饭", "晚上"]),
    ("夜宵", ["夜宵", "宵夜"]),
]


def _match_any(text: str, rule_list: list[tuple[str, list[str]]]) -> str | None:
    """遍历规则列表，返回第一个匹配的槽位名"""
    for slot_name, keywords in rule_list:
        for kw in keywords:
            if kw in text:
                return slot_name
    return None


def _build_scene_rules(scene_aliases: dict) -> list[tuple[str, list[str]]]:
    """将配置文件中的场景别名转换为解析器用的规则列表"""
    return [(name, aliases) for name, aliases in scene_aliases.items()]


def parse_query(query: str) -> ParsedSlots:
    # 1. 预算提取（正则）
    budget = None
    m = re.search(r"(\d{1,3})\s*(元|块)?\s*(以内|以下|左右|预算)?", query)
    if m:
        try:
            budget = float(m.group(1))
        except ValueError:
            pass

    # 2. 场景规则从配置文件加载（配置与代码统一维护）
    config = load_scoring_config()
    scene_rules = _build_scene_rules(config["scene_aliases"])

    # 3. 文本匹配提取
    location = _match_any(query, _LOCATIONS)
    scene = _match_any(query, scene_rules)
    taste = _match_any(query, _TASTES)
    time = _match_any(query, _TIMES)

    return ParsedSlots(
        budget_max=budget if budget and budget <= 500 else None,
        location=location,
        scene=scene,
        taste=taste,
        time=time,
    )
