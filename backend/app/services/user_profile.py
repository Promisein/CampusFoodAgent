"""
用户画像构建：从历史行为数据中"算"出用户偏好，不靠用户手动填写。
"""

import json

from app.services.usage_events import list_recent_events
from app.services.feedback_repository import get_feedback_by_user


def build_iterative_profile(uid: str | None = None, user_id: str | None = None) -> dict:
    """
    分析用户最近 30 天行为 + 90 天反馈，构建画像。
    返回格式：
    {
        "hasProfile": bool,
        "summary": "人类可读的偏好摘要",
        "signals": {"preferred_tastes": [...], "frequent_campus": "...", ...},
        "stats": {"total_queries": 0, "total_feedbacks": 0, "avg_rating": 0}
    }
    """
    # 获取最近事件
    events = list_recent_events(uid=uid, user_id=user_id, days=30, limit=80)
    feedbacks = get_feedback_by_user(uid=uid, user_id=user_id, days=90, limit=80)

    total_queries = sum(1 for e in events if e.get("event_type") == "query")
    total_feedbacks = len(feedbacks)
    avg_rating = (
        sum(f.get("rating", 0) for f in feedbacks) / len(feedbacks)
        if feedbacks else 0
    )

    # 汇总口味偏好
    taste_counter: dict[str, float] = {}
    for f in feedbacks:
        if f.get("taste_tags"):
            try:
                tags = json.loads(f["taste_tags"]) if isinstance(f["taste_tags"], str) else f["taste_tags"]
            except Exception:
                tags = []
            weight = 1.5 if f.get("rating", 0) >= 4 else (0.5 if f.get("rating", 0) <= 2 else 1.0)
            for tag in tags:
                taste_counter[tag] = taste_counter.get(tag, 0) + weight

    preferred = sorted(taste_counter.items(), key=lambda x: -x[1])[:5]

    has_profile = total_queries >= 3 or total_feedbacks >= 2

    return {
        "hasProfile": has_profile,
        "summary": _build_summary(preferred, total_queries, total_feedbacks),
        "signals": {
            "preferred_tastes": [p[0] for p in preferred],
            "total_queries": total_queries,
            "total_feedbacks": total_feedbacks,
        },
        "stats": {
            "total_queries": total_queries,
            "total_feedbacks": total_feedbacks,
            "avg_rating": round(avg_rating, 2),
        },
    }


def _build_summary(preferred: list, total_queries: int, total_feedbacks: int) -> str:
    """生成人类可读的偏好摘要"""
    if not preferred:
        return f"新用户（{total_queries}次查询，{total_feedbacks}次反馈）"
    taste_names = [p[0] for p in preferred[:3]]
    return f"偏好口味：{'、'.join(taste_names)}。{total_queries}次查询，{total_feedbacks}次反馈"
