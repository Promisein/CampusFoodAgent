# 第 7 章：配套功能

## 本章目标

补全后端剩下的功能模块：反馈、收藏、广告、事件追踪、热门排行。

这些模块逻辑相对独立，每个都是"接请求 → 验证参数 → 写数据库"的套路。本章可以并行开发，也可以按需实现。

## 文件清单

```
backend/
└── app/
    ├── api/
    │   ├── routes.py           # 新增反馈/收藏/广告/事件的端点
    │   └── proxy_routes.py      # 部分端点在此也有副本
    └── services/
        ├── feedback_repository.py    # 反馈
        ├── favorites_repository.py   # 收藏
        ├── ad_repository.py          # 广告
        ├── usage_events.py           # 事件追踪
        └── hot_ranking.py            # 热门排行
```

---

## 模块一：用户反馈

创建 `backend/app/services/feedback_repository.py`：

```python
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def save_feedback(
    feedback_type: str,         # "new_store" | "dining_feedback"
    store_name: str,
    rating: int | None = None,
    scene_tags: str | None = None,
    taste_tags: str | None = None,
    recommend_dish: str | None = None,
    comment: str | None = None,
    uid: str | None = None,
    user_id: str | None = None,
    anonymous_id: str | None = None,
) -> int:
    """
    保存用户反馈。返回新记录的 ID。
    feedback_type = "new_store" 表示推荐新店，"dining_feedback" 表示吃后评价
    """
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO feedback_submissions
               (feedback_type, store_name, rating, scene_tags, taste_tags,
                recommend_dish, comment, uid, user_id, anonymous_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (feedback_type, store_name, rating, scene_tags, taste_tags,
             recommend_dish, comment, uid, user_id, anonymous_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_feedback_by_user(
    uid: str | None = None,
    user_id: str | None = None,
    days: int = 90,
    limit: int = 80,
) -> list[dict]:
    """获取指定用户的反馈历史"""
    conn = _connect()
    try:
        conditions = []
        params = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        elif uid:
            conditions.append("uid = ?")
            params.append(uid)
        else:
            return []

        conditions.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM feedback_submissions WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def suggest_store_names(keyword: str, limit: int = 8) -> list[str]:
    """店名模糊搜索，用于前端自动补全"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DISTINCT name FROM shops WHERE name LIKE ? LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        conn.close()
```

在 `routes.py` 或 `proxy_routes.py` 中添加端点：

```python
@router.post("/feedback")
def submit_feedback(req: FeedbackRequest):
    fid = save_feedback(
        feedback_type=req.feedbackType,
        store_name=req.storeName,
        rating=req.rating,
        scene_tags=req.sceneTags,
        taste_tags=req.tasteTags,
        recommend_dish=req.recommendDish,
        comment=req.comment,
        uid=req.uid,
        user_id=req.userId,
        anonymous_id=req.anonymousId,
    )
    return {"ok": True, "id": fid}
```

---

## 模块二：收藏

创建 `backend/app/services/favorites_repository.py`：

```python
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def add_favorite(user_id: str, shop_id: int, shop_name: str = "") -> bool:
    """添加收藏。已存在则忽略（幂等）"""
    conn = _connect()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO user_favorites (user_id, shop_id, shop_name)
               VALUES (?, ?, ?)""",
            (user_id, shop_id, shop_name),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_favorite(user_id: str, shop_id: int) -> bool:
    """取消收藏"""
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM user_favorites WHERE user_id = ? AND shop_id = ?",
            (user_id, shop_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_favorites(user_id: str) -> list[dict]:
    """获取用户收藏列表"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM user_favorites WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

**为什么用 `INSERT OR IGNORE`？**
- `UNIQUE(user_id, shop_id)` 约束保证了不能重复收藏
- `OR IGNORE` 让重复请求不会报错，前端可以放心调（幂等性）

---

## 模块三：广告系统

创建 `backend/app/services/ad_repository.py`：

```python
import os
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_public_ad_slots(limit: int = 5) -> list[dict]:
    """获取当前生效中的广告位"""
    conn = _connect()
    try:
        now = datetime.now().isoformat()
        rows = conn.execute(
            """SELECT * FROM ad_slots
               WHERE is_active = 1
                 AND (starts_at IS NULL OR starts_at <= ?)
                 AND (ends_at IS NULL OR ends_at >= ?)
               ORDER BY id LIMIT ?""",
            (now, now, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def log_ad_click_event(slot_id: int, uid: str = "", user_id: str = "", anonymous_id: str = ""):
    """记录广告点击"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO ad_click_events (slot_id, uid, user_id, anonymous_id) VALUES (?, ?, ?, ?)",
            (slot_id, uid, user_id, anonymous_id),
        )
        conn.commit()
    finally:
        conn.close()


def seed_default_ads():
    """如果没有广告数据，插入默认广告位"""
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) as cnt FROM ad_slots").fetchone()["cnt"]
        if count == 0:
            defaults = [
                ("校内食堂一卡通充值", None, "store_detail", "学子餐厅", 1),
                ("西门夜宵一条街", None, "store_detail", "老麻抄手", 1),
                ("轻食沙拉外卖", None, "store_detail", "龙湖米线", 1),
            ]
            for title, img, ltype, lval, active in defaults:
                conn.execute(
                    "INSERT INTO ad_slots (title, image_url, landing_type, landing_value, is_active) VALUES (?, ?, ?, ?, ?)",
                    (title, img, ltype, lval, active),
                )
            conn.commit()
    finally:
        conn.close()
```

在 `routes.py` 中添加广告端点：

```python
@router.get("/ads/slots")
def get_ad_slots(limit: int = Query(default=5, ge=1, le=20)):
    slots = list_public_ad_slots(limit=limit)
    return {"slots": slots}

@router.post("/events/ad-click")
def log_ad_click(req: AdClickEventRequest):
    log_ad_click_event(slot_id=req.slotId, uid=req.uid, user_id=req.userId, anonymous_id=req.anonymousId)
    return {"ok": True}
```

---

## 模块四：事件追踪

创建 `backend/app/services/usage_events.py`：

```python
"""通用用户行为事件追踪（埋点）"""
import json
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_usage_event(
    event_type: str,
    uid: str = "",
    user_id: str = "",
    anonymous_id: str = "",
    query_text: str = "",
    shop_id: int | None = None,
    shop_name: str = "",
    extra: dict | None = None,
):
    """记录通用使用事件"""
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO usage_events (event_type, uid, user_id, anonymous_id, query_text, shop_id, shop_name, extra_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_type, uid, user_id, anonymous_id, query_text, shop_id, shop_name, json.dumps(extra or {})),
        )
        conn.commit()
    except Exception:
        pass  # 埋点失败不阻塞主流程
    finally:
        conn.close()


def list_recent_events(
    uid: str | None = None,
    user_id: str | None = None,
    days: int = 30,
    limit: int = 80,
) -> list[dict]:
    """获取用户最近的事件"""
    conn = _connect()
    try:
        conditions = []
        params = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        elif uid:
            conditions.append("uid = ?")
            params.append(uid)
        else:
            return []

        conditions.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM usage_events WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def bind_anonymous_events_to_user(anonymous_id: str, user_id: str):
    """将匿名数据绑定到登录用户"""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE usage_events SET user_id = ? WHERE anonymous_id = ? AND user_id IS NULL",
            (user_id, anonymous_id),
        )
        conn.commit()
    finally:
        conn.close()
```

**为什么埋点 try/except 吞异常？**
埋点是辅助功能，不能因为埋点失败导致推荐请求也跟着报错。宁可漏一条日志，也不能让用户看到 500。

---

## 模块五：热门排行

创建 `backend/app/services/hot_ranking.py`：

```python
"""基于查询事件分析的热门关键词排行"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))

def get_today_hot_rankings(limit: int = 5) -> list[dict]:
    """统计今日最常被查询的店铺"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT shop_name, COUNT(*) as query_count
               FROM usage_events
               WHERE event_type = 'query'
                 AND shop_name IS NOT NULL AND shop_name != ''
                 AND created_at >= date('now')
               GROUP BY shop_name
               ORDER BY query_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        items = []
        for i, row in enumerate(rows):
            shop = conn.execute(
                "SELECT * FROM shops WHERE name = ?", (row["shop_name"],)
            ).fetchone()
            items.append({
                "rank": i + 1,
                "name": row["shop_name"],
                "tag": shop["category"] if shop else "美食",
                "avg_price": shop["avg_price"] if shop else None,
                "query_count": row["query_count"],
            })

        return items
    finally:
        conn.close()
```

---

## 本章验证

每个模块独立验证：

```bash
# 1. 反馈
curl -X POST http://localhost:8000/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"feedbackType":"dining_feedback","storeName":"学子餐厅","rating":5,"comment":"好吃"}'

# 2. 收藏
curl -X POST http://localhost:8000/api/v1/favorites \
  -H "Content-Type: application/json" \
  -d '{"user_id":"anon_test123","shop_id":1,"shop_name":"学子餐厅"}'

curl http://localhost:8000/api/v1/favorites?user_id=anon_test123

# 3. 广告
curl http://localhost:8000/api/v1/ads/slots

# 4. 事件
curl -X POST http://localhost:8000/api/v1/events/track \
  -H "Content-Type: application/json" \
  -d '{"event_type":"query","uid":"test","query_text":"清水河"}'

# 5. 排行
curl http://localhost:8000/api/v1/rankings/today
```

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| 收藏返回 401 | 收藏端点可能加了鉴权依赖 | 如果是匿名用户，用 `user_id` 参数而非 `Authorization` 头 |
| 热门排行为空 | 没有查询事件数据 | 先调几次 `/events/track` 造数据 |
| ad_slots 返回空 | 没有种子数据 | 调 `seed_default_ads()` |

## 章末检查

- [ ] 反馈能正常写入和查询
- [ ] 收藏增删查都正常
- [ ] 广告位能展示、点击能记录
- [ ] 事件追踪不阻塞主流程
- [ ] 热门排行从真实事件数据中统计
