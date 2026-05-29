"""用户行为事件记录（第 7 章完整实现，本章仅提供占位接口）"""


def list_recent_events(uid: str | None = None, user_id: str | None = None, days: int = 30, limit: int = 80) -> list[dict]:
    """获取最近事件（占位实现，第 7 章从 SQLite 读取）"""
    return []


def bind_anonymous_events_to_user(anonymous_id: str, user_id: str) -> None:
    """将匿名期间的事件绑定到登录用户（占位实现，第 7 章完整实现）"""
    pass
