# CampusFoodAgent

Intelligent campus food recommendation AI Agent with FastAPI backend and WeChat MiniProgram frontend.

基于FastAPI与微信小程序的校园餐饮智能推荐Agent。

---

## Chapter 1 完成：项目脚手架

**目标**：创建最小可运行的 FastAPI 项目 —— 一个 `/api/v1/health` 端点，能访问 Swagger 文档，配置好 CORS 和 UTF-8 编码。

### 已创建的文件结构

```
backend/
├── .env                        # 环境变量（不提交 git）
├── .env.example                # .env 模板（可提交 git）
├── .python-version             # Python 版本：3.11
├── runtime.txt                 # Render 部署用：python-3.11.11
├── requirements.txt            # 依赖清单
├── pytest.ini                  # 测试配置
└── app/
    ├── __init__.py
    ├── main.py                 # ★ FastAPI 应用入口
    ├── api/
    │   └── __init__.py
    ├── models/
    │   └── __init__.py
    ├── services/
    │   └── __init__.py
    └── core/
        └── __init__.py
```

### main.py 包含

- **FastAPI 实例**：`title="成电吃什么 Agent API"`, `version="0.1.0"`
- **CORS 中间件**：允许 `localhost:3000` / `127.0.0.1:3000` 跨域访问
- **UTF-8 中间件**：`Utf8ResponseMiddleware` — 确保所有 JSON 响应带 `charset=utf-8`，防止中文乱码
- **健康检查端点**：`GET /api/v1/health` → `{"status": "ok"}`

### 如何运行

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

启动后访问：
- Swagger 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health

### 验证方法

1. 打开 `http://localhost:8000/docs`，应看到 Swagger 自动生成的 API 文档
2. 点击 `/api/v1/health` → "Try it out" → "Execute"，返回 `{"status": "ok"}`
3. 用 curl 验证中文编码：
   ```bash
   curl -i http://localhost:8000/api/v1/health
   # 应看到 Content-Type: application/json; charset=utf-8
   ```

### 章末检查清单

- [x] `uvicorn app.main:app --reload --port 8000` 启动成功（需先安装依赖）
- [x] `http://localhost:8000/docs` 能打开
- [x] `/api/v1/health` 返回 `{"status": "ok"}`
- [x] 响应头包含 `charset=utf-8`

---

## Chapter 2 完成：数据层

**目标**：创建 SQLite 数据库，建好所有表（9 张），用 CSV 种子数据填充 8 家店铺，并实现基本的店铺查询功能。

### 新增文件

```
backend/
├── data/
│   ├── schema.sql              # 9 张表的 DDL
│   └── shops_mock.csv          # 8 家种子店铺（清水河 7 家 + 沙河 1 家）
└── app/
    └── services/
        └── shop_repository.py  # ★ 数据库层（建表、种子导入、查询）
```

### schema.sql 包含的 9 张表

| 表名 | 用途 |
|---|---|
| `shops` | 店铺（名称、校区、区域、人均价格、口味/场景/标签、评分等） |
| `recommendation_logs` | 推荐请求日志 |
| `usage_events` | 用户行为埋点 |
| `feedback_submissions` | 用户反馈 |
| `user_favorites` | 用户收藏 |
| `user_preference_profiles` | 用户偏好设置 |
| `ad_slots` | 广告位 |
| `ad_click_events` | 广告点击事件 |
| `ad_settings` | 广告设置（键值对） |

### 种子数据（8 家店铺）

| ID | 店名 | 校区 | 区域 | 人均 | 口味 | 场景 |
|---|---|---|---|---|---|---|
| 1 | 学子餐厅 | 清水河 | 校内 | 12 | 清淡、家常 | 一个人、赶时间 |
| 2 | 清真食堂 | 清水河 | 校内 | 15 | 西北、清真 | 同学聚餐 |
| 3 | 老麻抄手 | 清水河 | 西门 | 18 | 麻辣、重口 | 一个人、夜宵 |
| 4 | 龙湖米线 | 清水河 | 龙湖 | 22 | 清淡、鲜美 | 一个人 |
| 5 | 川味小炒 | 沙河 | 校内 | 25 | 麻辣、重口、香辣 | 同学聚餐、晚餐 |
| 6 | 西门烤鱼 | 清水河 | 西门 | 45 | 麻辣、香辣 | 宿舍聚餐、晚餐 |
| 7 | 银桦餐厅 | 清水河 | 校内 | 10 | 清淡、家常 | 一个人、赶时间 |
| 8 | 龙湖火锅 | 清水河 | 龙湖 | 60 | 麻辣、重口 | 宿舍聚餐、夜宵 |

### shop_repository.py 对外接口

| 函数 | 功能 |
|---|---|
| `fetch_active_shops()` | 获取全部店铺列表 |
| `fetch_shop_by_id(shop_id)` | 按 ID 查店铺 |
| `fetch_store_detail_by_name(name)` | 按名称查详情 |
| `suggest_store_names(keyword, limit=8)` | 店名模糊搜索（自动补全） |

### 关键设计点

- **双重检查锁（DCL）**：`_ensure_database()` 用 `threading.Lock` + 双重 `if` 确保多线程环境下只建库一次
- **WAL 模式**：`PRAGMA journal_mode=WAL` — 写不阻塞读，对 Web 服务很重要
- **`row_factory = sqlite3.Row`**：查询结果可以用 `row["name"]` 而非 `row[0]`，可读性好
- **`utf-8-sig` 编码读 CSV**：处理 Excel 导出的 BOM 头
- **每函数新开连接**：SQLite 不支持跨线程共享连接，不用单例 connection

### 验证结果

```
Shop count: 8
  ID=1 name=学子餐厅 campus=清水河 avg_price=12.0 area=校内
  ID=2 name=清真食堂 campus=清水河 avg_price=15.0 area=校内
  ID=3 name=老麻抄手 campus=清水河 avg_price=18.0 area=西门
  ID=4 name=龙湖米线 campus=清水河 avg_price=22.0 area=龙湖
  ID=5 name=川味小炒 campus=沙河 avg_price=25.0 area=校内
  ID=6 name=西门烤鱼 campus=清水河 avg_price=45.0 area=西门
  ID=7 name=银桦餐厅 campus=清水河 avg_price=10.0 area=校内
  ID=8 name=龙湖火锅 campus=清水河 avg_price=60.0 area=龙湖

Search result for 米线: ['龙湖米线']
Search result for 龙湖: ['龙湖米线', '龙湖火锅']
Second fetch: 8 shops (still 8 -- idempotent seed check passed)
```

### 章末检查清单

- [x] 能查到 8 家店铺（>= 5）
- [x] 每家店铺有 name/campus/area/avg_price/tastes/scenes 字段
- [x] 再次运行时不会重复导入数据（店铺数不变，验证通过）
- [x] `suggest_store_names("米线")` 返回 `['龙湖米线']`

---

## Chapter 3 完成：规则引擎

**目标**：实现"用户输入大白话 → 解析出结构化槽位 → 加权打分排序 → 返回推荐列表"的完整链路。这是整个项目的**核心算法**。

### 架构总览

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

### 新增文件

```
backend/
├── data/
│   └── scoring_config.yaml         # 权重 + 时段 + 场景别名配置
└── app/
    ├── core/
    │   └── scoring_config.py       # ★ 评分配置加载器（深度合并 + 默认值兜底）
    └── services/
        ├── parser.py               # ★ 查询解析器（关键词 + 正则）
        └── recommender.py          # ★ 推荐排序引擎（加权打分）
```

### parser.py — 查询解析器

将用户的大白话拆成 5 个结构化槽位的 `ParsedSlots` dataclass：

| 槽位 | 提取方式 | 示例 |
|---|---|---|
| `budget_max` | 正则匹配 `"25元"` / `"预算25"` | `25.0` |
| `location` | 关键词表匹配 清水河/沙河 | `"清水河"` |
| `scene` | 关键词表匹配 一个人/聚餐/约会 | `"一个人"` |
| `taste` | 关键词表匹配 清淡/麻辣/鲜美 | `"清淡"` |
| `time` | 关键词表匹配 早餐/午餐/晚餐/夜宵 | `None` |

### recommender.py — 推荐排序引擎

**打分公式**：五维加权叠加，每项匹配即得满分（二元匹配），总额外附加 `budget_bonus`，最终分数裁剪到 [0, 0.99]：

```
总分 = 基础分(0.15)
     + 预算匹配 × 0.22    （预算内统一满分，越便宜附加分越高）
     + 校区匹配 × 0.18    （校区名出现在 campus/area 字段）
     + 口味匹配 × 0.18    （tastes JSON 数组中匹配）
     + 场景匹配 × 0.22    （scenes JSON 数组中匹配，支持别名展开）
     + 时间匹配 × 0.20    （营业时间与时段有重叠）
     + 预算附加分(0.03)   （仅当预算匹配时）
```

排序规则：分数降序 → 价格升序（同分时便宜的排前面）→ ID 升序。

**`_build_reason()`** 为每个结果生成人类可读的推荐理由，例如 `"预算匹配，校区匹配，口味匹配，场景匹配（综合评分 0.95）"`。

### scoring_config.yaml — 可调权重配置

```yaml
weights:
  base_score: 0.15    # 基础分（每家店都有）
  budget: 0.22        # 预算权重
  location: 0.18      # 校区权重
  taste: 0.18         # 口味权重
  scene: 0.22         # 场景权重（最高，因为场景是聚餐/夜宵这类强需求）
  time: 0.20          # 时间权重
  budget_bonus: 0.03  # 预算内附加分

time_slot_ranges:     # 时段定义（26 代表次日凌晨 2 点）
  早餐: ["06:00", "10:00"]
  午餐: ["11:00", "14:00"]
  晚餐: ["17:00", "21:00"]
  夜宵: ["21:00", "26:00"]

scene_aliases:        # 场景别名——把用户各种说法映射到标准场景
  一个人: ["一个人", "单人", "赶时间", "健身餐", "随便吃点"]
  同学聚餐: ["同学聚餐", "约饭", "朋友聚会", "聚餐", "宿舍聚餐"]
  约会: ["约会", "情侣", "两个人"]
```

### scoring_config.py — 配置加载器

- **深度合并**：YAML/JSON 配置与硬编码默认值做 `_deep_merge()`，用户只改了 weights 不影响 time_slot_ranges 和 scene_aliases
- **环境变量覆盖路径**：`SCORING_CONFIG_PATH` 可指定外部配置文件
- **支持 YAML + JSON**：文件名以 `.json` 结尾用 JSON 解析，否则用 YAML

### 验证结果

```
=== Test 1: 清水河，预算25，一个人想吃清淡的 ===
Parsed: budget=25.0, location=清水河, scene=一个人, taste=清淡, time=None
  龙湖米线 | Y22.0 | score=0.9536 | 预算/校区/口味/场景 四维匹配
  学子餐厅 | Y12.0 | score=0.8656 | 预算/校区/口味/场景 四维匹配
  银桦餐厅 | Y10.0 | score=0.848  | 预算/校区/口味/场景 四维匹配

=== Test 2: 沙河 同学聚餐 吃辣 ===
Parsed: budget=None, location=沙河, scene=同学聚餐, taste=麻辣, time=None
  川味小炒 | Y25.0 | score=0.73 | 校区/口味/场景 三维匹配
  (西门烤鱼、龙湖火锅 | score=0.55 | 口味/场景 两维匹配)

=== Test 3: 吃早餐 ===
Parsed: budget=None, location=None, scene=None, taste=None, time=早餐
  学子/银桦/清真 | score=0.35 | 仅时间匹配

=== Test 4: 空查询 ===
Parsed: all None → 全部返回，仅基础分 0.15，按价格升序

=== Test 5: 清水河西门 夜宵 重口 预算30 ===
Parsed: budget=30.0, location=清水河, taste=麻辣, time=夜宵
  老麻抄手 | Y18.0 | score=0.872 | 预算/校区/口味/时间 四维匹配
  川味小炒 | Y25.0 | score=0.7433 | 预算/口味/时间 三维匹配
  龙湖米线 | Y22.0 | score=0.7213 | 预算/校区/时间 三维匹配
```

### 章末检查清单

- [x] 输入 query 能正确提取 budget/location/scene/taste/time
- [x] 不同的 query 返回不同的排序结果
- [x] 改 `scoring_config.yaml` 的权重后，推荐结果会发生变化
- [x] `top_k=3` 返回不超过 3 家店
- [x] 空 query 返回默认排序的全部店铺

---

## Chapter 3 代码审查 + 修复

以下四个问题在代码审查中被发现并已修复：

### #1 场景识别疏漏 — parser.py 与 scoring_config.yaml 不同步

**问题**：`scoring_config.yaml` 中 `scene_aliases` 已包含 "赶时间"、"健身餐"、"宿舍聚餐" 等别名，但 `parser.py` 的 `_SCENES` 列表是独立硬编码的，未同步更新。导致 "早餐 10 元以内 赶时间" 这类语句的场景槽位为空。

**修复**：`parser.py` 的 `parse_query()` 改为动态调用 `load_scoring_config()` 获取 `scene_aliases`，再通过 `_build_scene_rules()` 转为规则列表。现在只需维护 YAML 配置一个来源，代码自动同步。

### #2 预算评分逻辑反直觉

**问题**：原公式 `budget_score = max(0, 1.0 - (budget_max - price) / budget_max)` 导致价格越接近预算上限得分越高。预算 25 元时，25 元的店铺得分 > 12 元的店铺，这与用户"预算内越便宜越好"的直觉相悖。

**修复**：改为预算内所有店铺统一获得满分权重（0.22），再按便宜程度附加梯度奖励：`price_bonus = (1 - price/budget_max) * budget_bonus`。越便宜附加分越高，自然排在前面。

### #3 跨天营业时间判断缺陷

**问题**：龙湖火锅营业时间 `10:00-02:00`（次日凌晨），但 `_is_open_during()` 将关门时间 `02:00` 直接转为 120 分钟，小于开门时间 600 分钟，导致与夜宵时段（21:00-26:00 = 1260-1560 分钟）的时间重叠判断 `shop_close_min(120) >= slot_open_min(1260)` 为 False。

**修复**：增加跨午夜修正逻辑——`shop_close_min < shop_open_min` 时关门时间自动加 1440 分钟（24 小时），正确表示跨日营业。

### #4 测试覆盖（57 个用例）

```
backend/tests/
├── __init__.py
├── test_parser.py      # 36 个测试
│   ├── TestParseBudget (8)
│   ├── TestParseLocation (5)
│   ├── TestParseTaste (6)
│   ├── TestParseScene (8)   ← 含 赶时间/健身餐/宿舍聚餐 回归测试
│   ├── TestParseTime (6)
│   └── TestParseEdgeCases (3)
└── test_recommender.py # 21 个测试
    ├── TestRecommendClearLightFood (2)
    ├── TestRecommendSpicyParty (2)
    ├── TestOvernightOpenHours (4)    ← 含跨午夜营业回归测试
    ├── TestRecommendTopK (3)
    ├── TestRecommendEmptyQuery (1)
    ├── TestRecommendScoreRange (2)
    ├── TestRecommendReason (2)
    ├── TestRecommendResultStructure (1)
    └── TestBudgetScoring (4)         ← 含预算评分回归测试
```

---

## Chapter 4 完成：API 路由 v1

**目标**：把规则引擎暴露为 REST API，创建完整的 MVP 端点集合。

### 新增文件

```
backend/
└── app/
    ├── models/
    │   └── schemas.py        # ★ 7 个 Pydantic 请求/响应模型
    └── api/
        └── routes.py          # ★ 6 个 MVP REST 端点
```

### schemas.py — Pydantic 数据模型

| 模型 | 用途 |
|---|---|
| `RecommendRequest` | 推荐请求：`query`（必填，min_length=1）+ `top_k`（1-10，默认 3） |
| `ParsedSlotsResponse` | 解析结果：budget_max / location / scene / taste / time |
| `ShopResult` | 单个推荐结果：shop_id / name / campus / area / avg_price / score / reason |
| `RecommendMeta` | 元数据：total_candidates / returned / engine |
| `RecommendResponse` | 推荐完整响应 = parsed + recommendations + meta |
| `HealthResponse` | 健康检查响应 |
| `HotRankingItem` / `HotRankingResponse` | 热门排行 |

### routes.py — 6 个 API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| `GET` | `/api/v1/health` | 健康检查 |
| `POST` | `/api/v1/recommend` | 核心推荐（输入 query → 返回解析 + 推荐 + 元数据） |
| `GET` | `/api/v1/stores/detail?name=...` | 按店名查店铺详情 |
| `GET` | `/api/v1/stores/suggest?keyword=...` | 店名模糊搜索（自动补全） |
| `GET` | `/api/v1/rankings/today` | 热门排行（按评分降序 Top 5） |

### main.py 变更

- 移除了直接在 `main.py` 中定义的 `/api/v1/health` 端点
- 新增 `app.include_router(router, prefix="/api/v1", tags=["mvp"])` 挂载路由
- 所有端点统一通过 APIRouter 管理，main.py 只负责应用启动和中间件

### API 验证结果

```
1. GET  /health              → 200 {"status": "ok"}
2. POST /recommend           → 200 {
     "parsed": {"budget_max": 25.0, "location": "清水河",
                "scene": "一个人", "taste": "清淡", "time": null},
     "recommendations": [
       {"name": "银桦餐厅", "score": 0.968, "avg_price": 10.0, ...},
       {"name": "学子餐厅", "score": 0.9656, "avg_price": 12.0, ...},
       {"name": "龙湖米线", "score": 0.9536, "avg_price": 22.0, ...}
     ],
     "meta": {"total_candidates": 8, "returned": 3, "engine": "rule-based"}
   }
3. GET  /stores/detail       → 200 {"data": {"name": "学子餐厅", ...}}
4. GET  /stores/suggest      → 200 {"suggestions": ["龙湖米线", "龙湖火锅"]}
5. GET  /rankings/today      → 200 返回 5 家店铺
6. GET  /stores/detail (404) → 404 {"detail": "店铺不存在"}
7. GET  /docs                → 200 Swagger UI 正常访问
```

### 如何运行

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

然后打开 http://localhost:8000/docs 用 Swagger 测试所有端点。

### 章末检查清单

- [x] 所有端点能在 Swagger 文档中看到
- [x] `POST /api/v1/recommend` 返回 parsed + recommendations + meta 三部分
- [x] `GET /api/v1/stores/detail?name=...` 返回完整店铺信息
- [x] `GET /api/v1/stores/suggest?keyword=...` 返回店名列表
- [x] `GET /api/v1/rankings/today` 返回热门排行

---

## Chapter 4 代码审查 + 修复

以下四个问题在代码审查中被发现并已修复：

### #1 stores/detail 暴露了数据库原始字段

**问题**：`GET /stores/detail` 直接返回 SQLite 查出的原始 dict，暴露了 `created_at`、`updated_at`、`poi_id` 等内部字段，且 `tastes` / `scenes` / `tags` / `image_urls` 是 JSON 字符串（如 `'["清淡","家常"]'`）而非真正的数组。

**修复**：新增 `StoreDetailResponse` Pydantic 模型，用 `field_validator` 把 JSON 字符串自动解析为 Python list，同时只对外暴露 17 个消费者需要的字段，内部字段自动过滤。

### #2 stores/suggest 和 rankings/today 缺少 response_model

**问题**：`health` 和 `recommend` 有显式 `response_model`，但 `stores/suggest` 和 `rankings/today` 没有，Swagger 文档不够清晰，且缺少输出过滤保护。

**修复**：新增 `StoreSuggestResponse` 模型，`stores/suggest` 和 `rankings/today` 端点均加上了 `response_model`。现在 6 个端点全部统一有 Pydantic 模型约束。

### #3 热门排行是"伪排行"

当前 `rating` 字段基本为 NULL，排序结果接近原始顺序。第四章的实现是**预留排行榜接口**，在数据充实之前不宣称有排序算法。routes.py 的 docstring 也已标注"简易实现"。

### #4 API 层测试（16 个用例）

```
backend/tests/
└── test_api.py          # ★ 新增
    ├── TestHealthAPI (1)
    ├── TestRecommendAPI (6)     ← 含空 query 422、top_k 越界 422
    ├── TestStoreDetailAPI (3)   ← 含 404、空 name 422、字段白名单校验
    ├── TestStoreSuggestAPI (4)  ← 含精确匹配/部分匹配/无结果/空 keyword 422
    └── TestRankingsAPI (2)      ← 含结构校验、排序验证
```

### 总测试覆盖：73 个用例

| 文件 | 数量 | 覆盖层 |
|---|---|---|
| `test_parser.py` | 36 | 查询解析 |
| `test_recommender.py` | 21 | 推荐引擎 |
| `test_api.py` | 16 | HTTP 接口 |
