import json
import os
from copy import deepcopy
from pathlib import Path

import yaml

_DEFAULT_CONFIG = {
    "weights": {
        "base_score": 0.15, "budget": 0.22, "location": 0.18,
        "taste": 0.18, "scene": 0.22, "time": 0.20, "budget_bonus": 0.03,
    },
    "time_slot_ranges": {
        "早餐": ["06:00", "10:00"], "午餐": ["11:00", "14:00"],
        "晚餐": ["17:00", "21:00"], "夜宵": ["21:00", "26:00"],
    },
    "scene_aliases": {
        "一个人": ["一个人", "单人", "赶时间", "健身餐"],
        "同学聚餐": ["同学聚餐", "约饭", "朋友聚会"],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典：override 覆盖 base 中的同名字段"""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_scoring_config() -> dict:
    """加载评分配置，YAML 优先，JSON fallback，最终用默认兜底"""
    config_path = os.getenv(
        "SCORING_CONFIG_PATH",
        str(Path(__file__).resolve().parents[2] / "data" / "scoring_config.yaml"),
    )

    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            if config_path.endswith(".json"):
                file_config = json.load(f)
            else:
                file_config = yaml.safe_load(f) or {}
        return _deep_merge(_DEFAULT_CONFIG, file_config)

    return _DEFAULT_CONFIG
