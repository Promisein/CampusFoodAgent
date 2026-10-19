# 第 3 章：规则引擎

## 本章目标

实现"用户输入大白话 → 解析出结构化槽位 → 加权打分排序 → 返回推荐列表"的完整链路。

这是整个项目的**核心算法**，也是你面试时要能讲清楚的部分。

## 前置知识

- 什么是正则表达式（re 模块）
- 加权评分的基本思路

## 文件清单

```
backend/
└── app/
    ├── core/
    │   ├── __init__.py
    │   └── scoring_config.py      # ★ 评分权重加载器
    └── services/
        ├── parser.py               # ★ 查询解析器
        └── recommender.py          # ★ 推荐排序引擎
└── data/
    └── scoring_config.yaml         # 权重配置文件
```

## 架构总览

```
用户输入 "清水河，预算25，一个人想吃清淡的"
        │
        ▼
   parser.py
   提取 → {budget_max: 25, location: "清水河", taste: "清淡", scene: "一个人"}
        │
        ▼
   recommender.py
   从 SQLite 取全部店铺 → 逐家打分 → 按分数排序 → 取 Top 3
        │
        ▼
   返回: [{店名, 评分, 推荐理由}, ...]
```

---

## Step 1：评分权重配置

创建 `backend/data/scoring_config.yaml`：

```yaml
weights:
  base_score: 0.15
  budget: 0.22
  location: 0.18
  taste: 0.18
  scene: 0.22
  time: 0.20
  budget_bonus: 0.03

# 时段定义（小时用 24 小时制，但这里允许 26 代表次日凌晨 2 点）
time_slot_ranges:
  早餐: ["06:00", "10:00"]
  午餐: ["11:00", "14:00"]
  晚餐: ["17:00", "21:00"]
  夜宵: ["21:00", "26:00"]

# 场景别名：把用户的各种说法映射到标准场景
scene_aliases:
  一个人: ["一个人", "单人", "赶时间", "健身餐", "随便吃点"]
  同学聚餐: ["同学聚餐", "约饭", "朋友聚会", "聚餐", "宿舍聚餐"]
  约会: ["约会", "情侣", "两个人"]
```

**为什么权重加起来不是 1.0？**
- 五维权重 + base_score + budget_bonus 是并行叠加，不是归一化。最终分数会裁剪到 [0, 0.99]
- 每个维度的满分是 1.0，加权后叠加。实际 score = weighted_sum + budget_bonus，上限 0.99

---

## Step 2：写评分配置加载器

创建 `backend/app/core/scoring_config.py`：

```python
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
```

**设计要点**：深度合并默认值兜底——即使配置文件写错了/删了部分字段，程序也不会崩。

---

## Step 3：查询解析器

创建 `backend/app/services/parser.py`：

```python
import re
from dataclasses import dataclass


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

_SCENES = [
    ("一个人", ["一个人", "单人", "自己", "随便", "简单"]),
    ("同学聚餐", ["聚餐", "约饭", "聚会", "室友", "同学", "朋友", "宿舍"]),
    ("约会", ["约会", "情侣", "两个人", "对象"]),
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


def parse_query(query: str) -> ParsedSlots:
    # 1. 预算提取（正则）
    budget = None
    m = re.search(r"(\d{1,3})\s*(元|块)?\s*(以内|以下|左右|预算)?", query)
    if m:
        try:
            budget = float(m.group(1))
        except ValueError:
            pass

    # 2. 文本匹配提取
    location = _match_any(query, _LOCATIONS)
    scene = _match_any(query, _SCENES)
    taste = _match_any(query, _TASTES)
    time = _match_any(query, _TIMES)

    return ParsedSlots(
        budget_max=budget if budget and budget <= 500 else None,
        location=location,
        scene=scene,
        taste=taste,
        time=time,
    )
```

**为什么用关键词匹配而不是 LLM？**
- 快速（毫秒级）、免费、结果稳定可解释
- 校园餐饮场景的词汇很集中（就那些），关键词覆盖 90% 的情况
- LLM 是增强，不是替代——这是混合推荐的核心理念

---

## Step 4：推荐排序引擎

创建 `backend/app/services/recommender.py`：

```python
import json
from datetime import datetime

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

    # 1. 预算匹配
    if slots.budget_max is not None and shop.get("avg_price"):
        price = shop["avg_price"]
        if price <= slots.budget_max:
            budget_score = max(0, 1.0 - (slots.budget_max - price) / slots.budget_max)
            total += budget_score * weights["budget"]
            matched.append("budget")

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

    # 预算内附加分
    if "budget" in matched and shop["avg_price"] <= slots.budget_max:
        total += weights.get("budget_bonus", 0.03)

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
```

**打分公式**：
```
总得分 = 基础分(0.15)
       + 预算匹配 × 0.22
       + 校区匹配 × 0.18
       + 口味匹配 × 0.18
       + 场景匹配 × 0.22
       + 时间匹配 × 0.20
       + 预算内附加分(0.03，仅预算内)
```

**为什么匹配到就是满分而不是梯度分？**
- 当前数据量小（几十家店），二元匹配（0/1）就已经够区分
- 梯度分需要更细致的标签体系，当前 JSON 标签字段只记录了"有没有"这个维度

---

## Step 5：验证

```bash
cd backend
python -c "
from app.services.parser import parse_query
from app.services.recommender import recommend

# 测试解析
q = '清水河，预算25，一个人想吃清淡的'
slots = parse_query(q)
print(f'解析结果: budget={slots.budget_max}, location={slots.location}, scene={slots.scene}, taste={slots.taste}, time={slots.time}')

# 测试推荐
results = recommend(slots)
for r in results:
    print(f'  {r[\"name\"]} | ¥{r[\"avg_price\"]} | {r[\"score\"]} | {r[\"reason\"]}')
"
```

换几个 query 测试：
- `"沙河 同学聚餐 吃辣"` — 应该返回沙河的辣味店铺
- `"吃早餐"` — 应该返回营业时间覆盖早餐的店铺
- `"随便"` — 应该返回所有店铺

---

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| 所有店铺得分一样 | 匹配条件太宽泛，每项都匹配了 | 增加更细粒度的标签 |
| 部分店铺永远不出现 | 某些维度权重太低/标签缺失 | 检查 CSV 中的 tastes/scenes 字段是否正确 |
| 预算解析不了 "25 元" | 正则没覆盖这种说法 | 加测试用例，调正则 |
| 配置改了不生效 | 缓存了旧配置 | `load_scoring_config()` 每次请求都读文件，不缓存 |

## 章末检查

- [ ] 输入 query 能正确提取 budget/location/scene/taste/time
- [ ] 不同的 query 返回不同的排序结果
- [ ] 改 `scoring_config.yaml` 的权重后，推荐结果发生变化
- [ ] `top_k=3` 返回不超过 3 家店
- [ ] 空 query 返回默认排序的全部店铺
