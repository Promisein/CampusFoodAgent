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

-- 系统用户（邮箱用户 + 微信用户）
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE,
    password_hash   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- 微信身份与系统用户的绑定关系
CREATE TABLE IF NOT EXISTS wechat_identities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    openid_hash     TEXT NOT NULL UNIQUE,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
