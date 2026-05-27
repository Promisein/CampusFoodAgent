# 第 2 章：数据层

## 本章目标

创建 SQLite 数据库，建好所有表，用 CSV 种子数据填充店铺表，并实现基本的店铺查询功能。

## 前置知识

- SQL 基础（SELECT、INSERT、CREATE TABLE）
- SQLite 是什么（一个嵌入式的轻量数据库，不需要安装服务端）
- `sqlite3` Python 标准库的基本用法

## 文件清单

```
backend/
└── app/
    └── services/
        └── shop_repository.py    # ★ 数据库层（建表、种子、查询）
└── data/
    ├── schema.sql                # 建表 DDL
    └── shops_mock.csv            # 种子店铺数据
```

## 逐步实现

### Step 1：设计数据库表结构

创建 `backend/data/schema.sql`：

```sql
-- 核心表：店铺
CREATE TABLE IF NOT EXISTS shops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    campus          TEXT    NOT NULL,   -- 清水河 / 沙河
    area            TEXT,               -- 校内 / 西门 / 南门 / 龙湖
    poi_id          TEXT,               -- 腾讯地图 POI ID
    address         TEXT,               -- 详细地址
    phone           TEXT,               -- 联系电话
    category        TEXT,               -- 类别：川菜 / 面馆 / 火锅 ...
    avg_price       REAL,               -- 人均价格
    avg_price_min   REAL,
    avg_price_max   REAL,
    open_hours      TEXT,               -- 营业时间文本
    image_urls      TEXT,               -- 图片 URL（JSON 数组）
    latitude        REAL,               -- GPS 纬度
    longitude       REAL,               -- GPS 经度
    tastes          TEXT,               -- 口味标签（JSON 数组）
    scenes          TEXT,               -- 场景标签（JSON 数组）
    tags            TEXT,               -- 其他标签（JSON 数组）
    rating          REAL,               -- 评分
    review_count    INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

-- 推荐日志（记录每次推荐请求和结果）
CREATE TABLE IF NOT EXISTS recommendation_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_query     TEXT,
    parsed_json   TEXT,
    result_json   TEXT,
    engine        TEXT,
    created_at    TEXT    DEFAULT (datetime('now'))
);

-- 用户行为事件（埋点）
CREATE TABLE IF NOT EXISTS usage_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type    TEXT    NOT NULL,      -- query / click / view ...
    uid           TEXT,                  -- 设备匿名 ID
    user_id       TEXT,                  -- 登录用户 ID
    anonymous_id  TEXT,                  -- 前端生成的匿名 ID
    query_text    TEXT,
    shop_id       INTEGER,
    shop_name     TEXT,
    extra_json    TEXT,                  -- 扩展字段
    created_at    TEXT    DEFAULT (datetime('now'))
);

-- 用户反馈
CREATE TABLE IF NOT EXISTS feedback_submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_type   TEXT    NOT NULL,    -- new_store / dining_feedback
    store_name      TEXT,
    rating          INTEGER,
    scene_tags      TEXT,
    taste_tags      TEXT,
    recommend_dish  TEXT,
    comment         TEXT,
    uid             TEXT,
    user_id         TEXT,
    anonymous_id    TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- 用户收藏
CREATE TABLE IF NOT EXISTS user_favorites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT    NOT NULL,
    shop_id     INTEGER NOT NULL,
    shop_name   TEXT,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(user_id, shop_id)   -- 同一个用户不能重复收藏
);

-- 用户偏好设置
CREATE TABLE IF NOT EXISTS user_preference_profiles (
    user_id           TEXT PRIMARY KEY,
    campus            TEXT,
    taste_tags_json   TEXT,
    dislikes_json     TEXT,
    budget_preference TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- 广告位
CREATE TABLE IF NOT EXISTS ad_slots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    image_url     TEXT,
    landing_type  TEXT,               -- store_detail / miniprogram_path / url
    landing_value TEXT,
    is_active     INTEGER DEFAULT 1,
    starts_at     TEXT,
    ends_at       TEXT,
    created_at    TEXT    DEFAULT (datetime('now'))
);

-- 广告点击事件
CREATE TABLE IF NOT EXISTS ad_click_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id      INTEGER,
    uid          TEXT,
    user_id      TEXT,
    anonymous_id TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

-- 广告设置（键值对）
CREATE TABLE IF NOT EXISTS ad_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

**为什么不用 ORM？** 项目规模小（9 张表，几十家店），SQLite 单文件部署，手写 SQL 更直接。如果数据量大到需要 PostgreSQL 再用 ORM。

### Step 2：准备种子数据

创建 `backend/data/shops_mock.csv`，放 5-10 家真实的校内/周边店铺：

```csv
id,name,campus,area,avg_price,open_hours,tastes,scenes,tags,latitude,longitude,image_urls
1,学子餐厅,清水河,校内,12,06:30-21:00,"[""清淡"",""家常""]","[""一个人"",""赶时间""]","[""快餐"",""盖饭""]",30.7500,103.9300,"[]"
2,清真食堂,清水河,校内,15,07:00-20:30,"[""西北"",""清真""]","[""同学聚餐""]","[""拉面"",""大盘鸡""]",30.7505,103.9310,"[]"
3,老麻抄手,清水河,西门,18,09:00-22:00,"[""麻辣"",""重口""]","[""一个人"",""夜宵""]","[""抄手"",""面食""]",30.7480,103.9280,"[]"
4,龙湖米线,清水河,龙湖,22,10:00-21:30,"[""清淡"",""鲜美""]","[""一个人""]","[""米线"",""汤锅""]",30.7450,103.9250,"[]"
5,川味小炒,沙河,校内,25,10:30-21:00,"[""麻辣"",""重口"",""香辣""]","[""同学聚餐"",""晚餐""]","[""川菜"",""炒菜""]",30.6800,104.0500,"[]"
```

至少 5 家，覆盖两个校区，口味、场景、价格段各有差异——这样后面测试推荐引擎才有效果。

### Step 3：实现数据库层

创建 `backend/app/services/shop_repository.py`：

```python
import csv
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))
SCHEMA_PATH = str(Path(__file__).resolve().parents[2] / "data" / "schema.sql")
SEED_PATH = str(Path(__file__).resolve().parents[2] / "data" / "shops_mock.csv")

_lock = threading.Lock()
_db_ready = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # 让查询结果可以用 row["name"] 访问
    conn.execute("PRAGMA journal_mode=WAL")  # 提升并发性能
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_database():
    """首次调用时建表 + 导种子数据（线程安全）"""
    global _db_ready
    if _db_ready:
        return
    with _lock:
        if _db_ready:
            return

        conn = _connect()
        try:
            # 1. 执行 schema.sql 建表
            with open(SCHEMA_PATH, encoding="utf-8") as f:
                conn.executescript(f.read())

            # 2. 导入 CSV 种子数据（只导一次）
            cur = conn.execute("SELECT COUNT(*) as cnt FROM shops")
            if cur.fetchone()["cnt"] == 0:
                with open(SEED_PATH, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # 跳过 id 字段，让数据库自增
                        values = {k: v for k, v in row.items() if k != "id"}
                        columns = ", ".join(values.keys())
                        placeholders = ", ".join("?" * len(values))
                        conn.execute(
                            f"INSERT INTO shops ({columns}) VALUES ({placeholders})",
                            list(values.values()),
                        )
            conn.commit()
        finally:
            conn.close()
        _db_ready = True


def fetch_active_shops() -> list[dict]:
    """获取全部活跃店铺"""
    _ensure_database()
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM shops ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_shop_by_id(shop_id: int) -> dict | None:
    """根据 ID 查店铺"""
    _ensure_database()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch_store_detail_by_name(name: str) -> dict | None:
    """根据店名查详情"""
    _ensure_database()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM shops WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def suggest_store_names(keyword: str, limit: int = 8) -> list[str]:
    """店名模糊搜索（自动补全用）"""
    _ensure_database()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT name FROM shops WHERE name LIKE ? LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        conn.close()
```

**关键设计点：**

1. **`_ensure_database()` 带双重检查锁（DCL）**：确保多线程并发时只建一次表、只导一次数据
2. **`row_factory = sqlite3.Row`**：让查询结果能用 `row["name"]` 而不是只能 `row[0]`，可读性好很多
3. **WAL 模式**：写不阻塞读，读不阻塞写，对 Web 服务很重要
4. **`encoding="utf-8-sig"`** 读 CSV：Excel 导出的 CSV 可能带 BOM 头（`\ufeff`），用 `utf-8-sig` 自动处理
5. **每个函数都新开连接**：因为 SQLite 不支持跨线程共享连接。不要用单例 connection

### Step 4：验证

```bash
cd backend
python -c "
from app.services.shop_repository import fetch_active_shops
shops = fetch_active_shops()
print(f'共 {len(shops)} 家店铺')
for s in shops:
    print(f'  {s[\"name\"]} | {s[\"campus\"]} | ¥{s[\"avg_price\"]} | {s[\"tastes\"]}')
"
```

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| CSV 导入后第一行列名变成了数据 | UTF-8 BOM 头没处理 | `encoding="utf-8-sig"` |
| `database is locked` | 多线程同时写 SQLite | 写操作加重试逻辑，或开启 WAL |
| `no such table: shops` | `_ensure_database()` 没被调用 | 所有查询函数第一行调用它 |
| CSV 字段含逗号解析错位 | CSV 格式不规范 | 确保 CSV 中带逗号的字段用双引号包裹 |

## 章末检查

- [ ] 能查到 5+ 家店铺
- [ ] 每家店铺有 name/campus/area/avg_price/tastes/scenes 字段
- [ ] 再次运行时不会重复导入数据（店铺数不变）
- [ ] `suggest_store_names("米线")` 返回匹配的店名
