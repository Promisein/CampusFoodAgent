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

---

## Chapter 5 完成：AI 引擎 — DeepSeek V4

**目标**：接入 DeepSeek V4 API，实现 AI 驱动的推荐路径。支持三种推荐模式：DeepSeek API 直调、DeepSeek Rerank（规则初排 + LLM 精排）、规则引擎兜底。

### 新增文件

```
backend/
├── .env                          # 新增 DeepSeek API 配置
├── .env.example                  # 新增 DeepSeek 密钥模板
└── app/
    ├── models/
    │   └── schemas.py            # 新增 DeepSeekRecommendRequest/Response
    ├── api/
    │   └── proxy_routes.py       # ★ /api/recommend（3 模式智能分发）
    └── services/
        ├── deepseek_service.py          # ★ DeepSeek V4 API 客户端
        ├── deepseek_rerank_service.py   # ★ Rerank 混合推荐（规则初排 + LLM 精排）
        ├── query_intent_service.py      # 查询意图分类关键词提取
        ├── user_profile.py              # 用户画像构建（从行为数据计算偏好）
        ├── usage_events.py              # 行为事件记录（占位，第 7 章实现）
        └── feedback_repository.py       # 用户反馈存储（占位，第 7 章实现）
```

### 架构总览：三种推荐模式

```
POST /api/recommend  (proxy_routes.py)
         │
         ├─ RECOMMEND_PROVIDER=deepseek_api ──→ deepseek_service.py
         │    query + 用户画像 + 意图关键词 → DeepSeek V4 API → 自然语言推荐
         │
         ├─ RECOMMEND_PROVIDER=deepseek_rerank ──→ deepseek_rerank_service.py
         │    ① 规则引擎初排 Top 30
         │    ② 构造 Prompt（候选店铺列表 + 用户需求）
         │    ③ DeepSeek V4 精排返回 JSON
         │    ④ 白名单过滤（防幻觉）→ 最终 Top 3
         │
         └─ 其他/未配置 ──→ 规则引擎兜底
              parser → recommender → Top K 打分结果
```

### 各模块详解

#### 1. deepseek_service.py — DeepSeek V4 API 客户端

调用 `POST https://api.deepseek.com/chat/completions`，实现：

- **统一标准响应**：始终返回 `{ok, answer, error, code, finish_reason}`，不绑定具体供应商格式
- **用户画像注入**：将用户偏好摘要和意图关键词合并到 System Prompt 中，提升推荐相关性
- **指数退避重试**：`time.sleep(2 ** attempt)`，第 1 次重试等 1s，第 2 次等 2s
- **可配置超时**：`DEEPSEEK_TIMEOUT_SECONDS`（默认 25s），应对长文本场景

#### 2. deepseek_rerank_service.py — Rerank 混合推荐（核心亮点）

这是面试最值得讲的模块。Pipeline：

```
全部店铺 ──规则引擎初排──→ Top 30 ──构造Prompt──→ DeepSeek V4 ──返回JSON──→ 白名单过滤 ──→ 最终 Top 3
```

关键函数：
- `ask_deepseek_rerank()` — 主流程编排
- `_build_candidate_text()` — 将候选店铺格式化为 LLM 可读的文本
- `_call_deepseek_api()` — 调 DeepSeek V4（非流式）
- `_sanitize_or_fallback()` — **安全边界**：白名单过滤 + JSON 解析失败回退
- `_fallback_to_rules()` — LLM 不可用时退回规则引擎

**白名单过滤（防幻觉机制）**：LLM 可能编造不存在的店名（如候选里只有"学子餐厅"但 LLM 回复"银杏餐厅"）。`_sanitize_or_fallback()` 从规则引擎的候选列表构建店名白名单，只保留真正存在的店铺。这是整个流程的**安全边界，不能删**。

#### 3. query_intent_service.py — 查询意图提取

用 7 大类关键词字典匹配用户查询中的食物分类意图：

| 分类 | 关键词示例 |
|---|---|
| 面食 | 面、拉面、刀削面、米线、抄手、饺子 |
| 米饭 | 盖饭、炒饭、拌饭、套餐、米饭 |
| 火锅 | 火锅、串串、冒菜、麻辣烫 |
| 川菜 | 川菜、炒菜、回锅肉、宫保、水煮 |
| 小吃 | 小吃、烧烤、炸鸡、奶茶 |
| 汤品 | 汤、炖、粥、砂锅 |
| 快餐 | 快餐、盒饭、便当、食堂 |

`build_query_with_intent_hint()` 自动为查询附加意图提示，如 `"想吃面"` → `"想吃面（想吃：面食）"`，注入到 LLM 请求中增强推荐准确性。

#### 4. user_profile.py — 用户画像构建

不靠用户手动填写，从历史行为数据中"算"出偏好：

- **数据来源**：最近 30 天行为事件 + 90 天反馈记录
- **口味加权**：评分 >= 4 → 权重 1.5x，评分 <= 2 → 权重 0.5x
- **输出格式**：`{hasProfile, summary, signals, stats}`
- `has_profile` 阈值：查询 >= 3 次 或 反馈 >= 2 次

画像以 `AGENT_USER_PROFILE_SUMMARY` 和 `AGENT_CATEGORY_KEYWORDS` 参数注入到 DeepSeek 的 System Prompt 中。

### 新增 API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| `POST` | `/api/recommend` | AI 推荐（3 模式自动分发） |

请求体（`DeepSeekRecommendRequest`）：

```json
{
  "query": "清水河吃面 20块",
  "uid": "anon_xxx",
  "top_k": 3
}
```

响应体（`DeepSeekRecommendResponse`）：

```json
{
  "ok": true,
  "answer": "...",
  "recommendations": [
    {"name": "老麻抄手", "reason": "...", "match_score": 0.87}
  ],
  "engine": "deepseek_rerank"
}
```

### 环境变量配置

```env
# 推荐模式选择
RECOMMEND_PROVIDER=deepseek_rerank   # deepseek_api | deepseek_rerank | (其他=规则兜底)

# DeepSeek V4 API
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=25
DEEPSEEK_MAX_RETRIES=1
DEEPSEEK_TEMPERATURE=0.3
DEEPSEEK_MAX_TOKENS=1800
```

### 验证方法

```bash
cd backend

# 1. 规则引擎兜底模式（无需 API Key）
RECOMMEND_PROVIDER="" uvicorn app.main:app --port 8000
# POST /api/recommend {"query": "清水河吃面 20块"} → 返回规则引擎结果

# 2. DeepSeek API 模式（需配置 DEEPSEEK_API_KEY）
RECOMMEND_PROVIDER=deepseek_api uvicorn app.main:app --port 8000
# POST /api/recommend → DeepSeek V4 生成自然语言推荐

# 3. DeepSeek Rerank 模式（需配置 DEEPSEEK_API_KEY）
RECOMMEND_PROVIDER=deepseek_rerank uvicorn app.main:app --port 8000
# POST /api/recommend → 规则初排 + LLM 精排
```

### 章末检查清单

- [x] 三种模式（deepseek_api / deepseek_rerank / 规则兜底）都能正常返回
- [x] 切换 `RECOMMEND_PROVIDER` 确实切换了引擎
- [x] DeepSeek Rerank 模式的输出清洗能过滤幻觉店名
- [x] 用户画像从历史数据中生成合理的摘要

---

## Chapter 6 完成：用户认证

**目标**：实现匿名优先 + 可选微信登录的用户身份体系，包括 JWT 签发/验证和匿名↔登录数据迁移。

### 新增文件

```
backend/
├── .env.example                  # 新增 AUTH_TOKEN_SECRET, 微信配置
└── app/
    ├── api/
    │   └── auth.py               # ★ require_authenticated_user 鉴权依赖
    ├── models/
    │   └── schemas.py            # 新增 WechatLoginRequest/Response, AuthMeResponse, ProfileSyncRequest
    ├── api/
    │   └── proxy_routes.py       # 新增 /auth/wechat-login, /auth/me, /profile/sync-local
    └── services/
        ├── auth_token_service.py  # ★ 手写 JWT HS256（签发 + 验证）
        ├── wechat_auth_service.py # ★ 微信 jscode2session → hashed userId → JWT
        └── favorites_repository.py # 用户收藏（占位，第 7 章实现）
```

### 新增 API 端点

| 方法 | 路径 | 鉴权 | 功能 |
|---|---|---|---|
| `POST` | `/api/auth/wechat-login` | 无 | 微信 code 换 JWT |
| `GET` | `/api/auth/me` | Bearer Token | 查看当前用户 |
| `POST` | `/api/profile/sync-local` | Bearer Token | 匿名数据迁移到登录账号 |

### auth_token_service.py — 手写 JWT HS256

三段式结构：`Header.Payload.Signature`

- `issue_access_token(user_id)` — 签发，默认 7 天有效期
- `verify_access_token(token)` — 验证签名 + 检查过期，失败抛 `AuthTokenError`
- `extract_bearer_token(authorization)` — 从 `Authorization: Bearer <token>` 头提取 token
- `hmac.compare_digest()` 防时序攻击

### wechat_auth_service.py — 微信登录

- `login_with_wechat_code(code, anonymous_id)` → `{access_token, userId, ...}`
- openid 通过 `sha256(salt:openid)[:24]` 哈希为内部 `wx_` 前缀 userId，保护原始 openid
- `WechatAuthError` 统一错误处理

### auth.py — FastAPI 鉴权依赖

```python
from app.api.auth import require_authenticated_user

@router.get("/protected")
def protected(user_id: str = Depends(require_authenticated_user)):
    ...
```

- 使用 `Header(None)` 自动注入 Authorization 头
- Token 无效 → 401，过期 → 401

### 环境变量配置

```env
# JWT 密钥
AUTH_TOKEN_SECRET=dev-secret-change-me

# 微信小程序
WECHAT_MINIPROGRAM_APPID=your_wechat_appid
WECHAT_MINIPROGRAM_SECRET=your_wechat_secret
WECHAT_AUTH_TOKEN_TTL_SECONDS=604800
WECHAT_AUTH_TIMEOUT_SECONDS=8
WECHAT_USER_ID_SALT=chedian-salt
```

### 验证结果

```bash
# JWT 签发/验证
python -c "
from app.services.auth_token_service import issue_access_token, verify_access_token
token = issue_access_token('test_user_123')
claims = verify_access_token(token)
print(claims['sub'])  # test_user_123
"

# auth/me 不带 token → 401
curl -i http://localhost:8000/api/auth/me
# → 401

# auth/me 带有效 token → 200
curl -i http://localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
# → {"userId": "...", "authenticated": true}
```

### 章末检查清单

- [x] JWT 签发和验证正常（签发 → 验证 → 过期拦截）
- [x] `/api/auth/me` 不带 token 返回 401，带有效 token 返回 200
- [x] 微信登录入口能正常校验参数（未配置 appid 时返回明确错误）
- [x] 登录后数据同步端点需要鉴权

---

## Chapter 7 完成：配套功能

**目标**：补全后端 5 个配套模块——反馈、收藏、广告、事件追踪、热门排行。每个模块独立可测。

### 新增/重写文件

```
backend/
└── app/
    ├── api/
    │   └── routes.py              # 新增 7 个端点，热门排行升级为事件驱动
    ├── models/
    │   └── schemas.py             # 新增 8 个请求/响应模型
    └── services/
        ├── feedback_repository.py  # ★ 重写：save_feedback + get_feedback_by_user
        ├── favorites_repository.py # ★ 重写：add/remove/list + OR IGNORE 幂等
        ├── ad_repository.py        # ★ 广告位查询 + 点击追踪 + 种子数据
        ├── usage_events.py         # ★ 重写：log/list/bind 事件追踪
        └── hot_ranking.py          # ★ 基于查询事件统计的实时热门排行
```

### 五个模块

#### 1. 反馈（feedback_repository.py）
- `save_feedback()` — 写入 `feedback_submissions` 表，支持 `dining_feedback` / `new_store` 两种类型
- `get_feedback_by_user()` — 按 uid 或 user_id 查询历史反馈

#### 2. 收藏（favorites_repository.py）
- `add_favorite()` — `INSERT OR IGNORE` 保证幂等（UNIQUE 约束防重复）
- `remove_favorite()` — 按 user_id + shop_id 删除
- `list_favorites()` — 按用户查询所有收藏
- `add_favorite_if_not_exists()` — 按店名查 shop_id 后插入，用于 sync-local

#### 3. 广告（ad_repository.py）
- `list_public_ad_slots()` — 查询当前生效中的广告位（is_active=1 + 时间范围检查）
- `log_ad_click_event()` — 记录广告点击
- `seed_default_ads()` — 首次访问时插入 3 条默认广告（双重检查锁，只插一次）

#### 4. 事件追踪（usage_events.py）
- `log_usage_event()` — 记录通用行为事件到 `usage_events` 表
- `list_recent_events()` — 按时间窗口查询用户事件
- `bind_anonymous_events_to_user()` — 登录后将匿名事件绑定到 userId
- **埋点 try/except 吞异常**：埋点失败不阻塞主流程

#### 5. 热门排行（hot_ranking.py）
- `get_today_hot_rankings()` — 从 `usage_events` 表统计今日查询次数最高的店铺
- 升级了 `/api/v1/rankings/today`：有事件数据时用真实统计，无数据时回退评分排序

### 新增 API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| `POST` | `/api/v1/feedback` | 提交反馈 |
| `POST` | `/api/v1/favorites` | 添加收藏 |
| `GET` | `/api/v1/favorites?user_id=...` | 查询收藏 |
| `DELETE` | `/api/v1/favorites` | 取消收藏 |
| `GET` | `/api/v1/ads/slots` | 获取广告位 |
| `POST` | `/api/v1/events/ad-click` | 广告点击 |
| `POST` | `/api/v1/events/track` | 事件追踪 |

### 章末检查清单

- [x] 反馈能正常写入（返回插入 ID）
- [x] 收藏增删查正常，重复收藏幂等
- [x] 广告位能展示、点击能记录
- [x] 事件追踪不阻塞主流程（埋点 try/except）
- [x] 热门排行从真实事件数据中统计，无数据时回退评分排序

---

## 知识点总结

### Chapter 1 — 项目脚手架
- FastAPI 应用结构、CORS 中间件、自定义中间件（UTF-8 编码）
- 环境变量管理（`.env` / `python-dotenv`）
- 用 `TestClient` 写 API 测试

### Chapter 2 — 数据层
- SQLite WAL 模式（写不阻塞读）
- Double-Checked Locking（线程安全的数据库初始化）
- `row_factory = sqlite3.Row`（字典式访问查询结果）
- CSV 种子数据导入（`utf-8-sig` 处理 BOM 头）
- 无 ORM 的手写 SQL（适合小表场景）

### Chapter 3 — 规则引擎
- 加权打分模型设计（多维度 + 附加分）
- 关键词匹配 + 正则提取的 NLP 解析器
- 场景别名系统（同义词归一化，支持 YAML 配置）
- 跨午夜营业时间判断（`close_min < open_min → close_min += 1440`）
- 预算评分直觉：预算内统一满分 + 越便宜附加分越高

### Chapter 4 — API 路由 v1
- FastAPI APIRouter（模块化路由组织）
- Pydantic v2 模型定义 + `field_validator(mode="before")` 处理 JSON 字符串→数组转换
- `response_model` 统一输出过滤（防止内部字段泄露）
- HTTPException 异常处理（404 / 422）
- TestClient 集成测试

### Chapter 5 — AI 引擎
- **LLM API 调用**：OpenAI 兼容的 chat/completions 格式，System/User/Assistant 多轮消息结构
- **Rerank 架构模式**：规则引擎初排 + LLM 精排是业界常用的混合方案，兼顾速度与质量
- **防幻觉（Anti-Hallucination）**：LLM 会编造不存在的信息。白名单过滤是安全边界——只允许推荐数据库里真实存在的店铺
- **指数退避重试**：`sleep(2^attempt)` 避免瞬时失败导致的服务不可用，是生产环境的必备模式
- **用户画像注入**：将用户历史行为"翻译"成人可读的偏好文本，注入 System Prompt，让 LLM 推荐更个性化
- **查询意图增强**：用关键词字典提取分类意图，追加到查询中，提升 LLM 理解准确度
- **Provider 模式**：通过环境变量切换推荐引擎，不影响路由层代码，方便 A/B 测试和灰度发布
- **JSON 输出清洗**：LLM 可能返回 Markdown 包裹的 JSON（```json...```），需要做容错解析

### Chapter 6 — 用户认证
- **JWT 三段式结构**：`base64(Header).base64(Payload).HMAC-SHA256(签名)`，手写实现可深入理解原理
- **HMAC-SHA256 签名验证**：`hmac.compare_digest()` 防时序攻击（恒定时间比较）
- **Base64 URL Safe 编码**：去掉 `=` 填充，替换 `+/` 为 `-_`，URL 中不用转义
- **FastAPI 依赖注入鉴权**：`Depends(require_authenticated_user)` + `Header(None)` 自动注入 Authorization 头
- **openid 哈希保护**：`sha256(salt:openid)[:24]` 单向不可逆，防止拖库后泄露原始 openid
- **OAuth code2session 流程**：wx.login() → code → 微信服务器 → openid → 自己的 JWT
- **匿名优先身份体系**：先分配匿名 ID，登录后通过 `/profile/sync-local` 合并数据

### Chapter 7 — 配套功能
- **INSERT OR IGNORE 幂等性**：`UNIQUE(user_id, shop_id) + OR IGNORE` 让重复请求不报错，前端可安全重试
- **DELETE 请求带 JSON body**：FastAPI 的 Pydantic 模型可自动解析 DELETE 请求体，但 TestClient 需用 `client.request("DELETE", ...)`
- **埋点 fire-and-forget**：`try/except` 吞异常，宁可漏日志也不阻塞主流程
- **事件驱动排行榜**：从 `usage_events` 表 `GROUP BY shop_name ORDER BY COUNT(*)` 统计热门，有数据用真实统计否则回退评分排序
- **广告种子数据**：首次访问时用 `COUNT(*) = 0` 检查 + 插入默认数据，双重检查保证不重复
- **热门排行标签容错**：`shop["category"] or "美食"` 处理 NULL 字段，避免 Pydantic 校验失败

### Chapter 7 代码审查修复

以下三个问题在代码审查中被发现并已修复：

1. **收藏接口加鉴权** — `/api/v1/favorites` 三个端点改为 `user_id: str = Depends(require_authenticated_user)`，从 JWT token 获取 userId 而非信任前端传来的 body/query 参数
2. **seed_default_ads() 移至启动** — 从 `get_today_rankings()` 和 `get_ad_slots()` 中移除，改为 `@app.on_event("startup")` 启动事件
3. **AdSlotsResponse 强类型** — `slots: list[dict]` → `slots: list[AdSlotItem]`，广告端点构造 `AdSlotItem(**s)` 返回

### Chapter 8 — Next.js 前端
- **Next.js App Router**：`"use client"` 标记客户端组件，`layout.tsx` 根布局，`page.tsx` 首页路由
- **匿名优先身份体系**：前端生成 `anon_<ts36><random>` ID，localStorage 持久化，Token 过期前 30s 自动降级
- **Blob UTF-8 编码**：`TextEncoder → Blob` 比直接传 JSON 字符串更可靠地保留中文
- **防抖**：250ms debounce 减少输入时无效 API 请求
- **骨架屏 Shimmer**：`linear-gradient + animation` 模拟内容加载占位

### Chapter 9 — 微信小程序 MVP
- **wx.request 封装**：小程序不支持 `fetch`，必须用 `wx.request`，用 Promise 包装回调式 API
- **wx.StorageSync**：同步读写本地存储，适合启动时读取身份，类似 `localStorage`
- **WXML 表达式限制**：模板不能 `.toFixed()` / `.includes()`，需在 JS 端预处理 view model
- **View Model 模式**：`buildRecommendationViewModels()` 把原始数据 + UI 状态（收藏/加载）合并，WXML 纯展示
- **微信登录闭环**：`wx.login() → /api/auth/wechat-login → JWT → wx.StorageSync`

### Chapter 11 — 多端账号体系
- **PBKDF2 HMAC-SHA256**：标准库 `hashlib.pbkdf2_hmac` + `hmac.compare_digest` 防时序攻击
- **密码存储格式**：`pbkdf2_sha256$iterations$salt$hash`，自描述、可扩展
- **双表账号设计**：`users`（统一身份）+ `wechat_identities`（微信绑定），比单表塞所有字段更易扩展
- **user_id 命名空间**：`em_<uuid>` 和 `wx_<hash>` 前缀区分来源，不混用
- **email UNIQUE 约束**：数据库层防止重复注册，比应用层检查更可靠
- **登录后状态联动**：JWT 写入 → 加载收藏列表 → 卡片收藏按钮自动可用，一条链

## Chapter 8 完成：Next.js 前端

**目标**：用 Next.js 15 搭建 Web 前端，实现搜索框 → 推荐卡片 → 反馈收藏的完整交互链路。

### 新建文件

```
frontend/
├── package.json                    # Next.js 15 + React 18 + TypeScript
├── next.config.mjs                 # reactStrictMode: true
├── tsconfig.json                   # bundler mode, @/* path alias
├── .env.local                      # NEXT_PUBLIC_API_BASE_URL
├── .env.local.example
└── src/
    ├── app/
    │   ├── globals.css             # 银杏主题色系 + 玻璃态卡片 + 骨架屏 + 响应式
    │   ├── layout.tsx              # 根布局（zh-CN, metadata）
    │   └── page.tsx                # 主页面（搜索/推荐/排行/登录/反馈）
    ├── components/
    │   └── FeedbackPanel.tsx       # 反馈弹窗（评分/菜品/标签/留言）
    └── lib/
        ├── api.ts                  # fetch 封装（Blob UTF-8, Bearer token, 业务 API）
        └── identity.ts             # 匿名身份管理（localStorage, Token 过期检测）
```

### 前端功能清单

| 功能 | 说明 |
|------|------|
| 搜索框 | textarea + Ctrl+Enter 提交，250ms 防抖店名自动补全 |
| 快捷提示 | 4 个预设查询按钮，点击快速填充 |
| 推荐卡片 | 玻璃态卡片展示店铺名称/匹配度/推荐理由/校区/价格 |
| 骨架屏 | 加载时显示 shimmer 动画骨架占位 |
| 热门排行 | 首页加载今日热门排行，点击可填充搜索 |
| WeChat 登录 | 弹窗输入 wx.login() code → 换取 JWT → 升级身份 |
| 反馈弹窗 | 星级评分 + 推荐菜品 + 场景/口味标签 + 留言 |
| 匿名身份 | 首次访问生成 `anon_<ts36><random>` ID，localStorage 持久化 |
| Token 管理 | 自动检测即将过期（提前 30s），过期降级匿名 |
| UTF-8 保障 | Blob + TextEncoder 确保中文不被 fetch 破坏 |

### 关键设计决策

- **无页面路由**：整个 App 就是单页（`page.tsx`），所有交互通过组件显示/隐藏切换，不需要 Next.js Router
- **Blob UTF-8 编码**：用 `new TextEncoder().encode(json)` 创建 Blob，显式设置 `charset=utf-8`，避免浏览器 fetch 破坏中文
- **两阶段 API 地址解析**：先查 `NEXT_PUBLIC_API_BASE_URL` 环境变量，再检测 `localhost` 兜底，最后 fallback 到 Render 生产地址
- **匿名优先 + 静默升级**：token 过期自动降级为匿名，不影响未登录用户的正常使用

### 验证方法

```bash
cd frontend
npm install
npm run dev
# 打开 http://localhost:3000

# 确保后端在 8000 端口运行：
cd backend
uvicorn app.main:app --reload --port 8000
```

1. 搜索框输入"清水河，一个人吃清淡的"→ 点生成推荐 → 看到推荐卡片
2. 点反馈按钮 → 弹出表单 → 提交后关闭
3. 打开浏览器 DevTools → Network 标签 → 确认请求正确发送到 `localhost:8000`

### 章末检查

- [x] `next build` 编译成功（无 TypeScript 错误）
- [x] 搜索框输入后能调用 API 获取推荐结果
- [x] 快捷提示按钮能快速填充输入
- [x] 加载中有骨架屏 loading 状态
- [x] 错误时显示错误信息而非白屏
- [x] 中文显示正常无乱码（Blob + TextEncoder + charset=utf-8）
- [x] 反馈弹窗能打开并提交
- [x] 热门排行在首页加载
- [x] 店名自动补全下拉提示

---

## Chapter 9 完成：微信小程序 MVP 接入

**目标**：在微信开发者工具中跑通小程序推荐主链路 —— 输入需求 → 调后端 → 展示推荐卡片。

### 新建/修改文件

```
miniprogram/
├── app.js                          # ★ 启动时初始化匿名身份
├── app.json                        # ★ 导航栏标题/银杏主题色
├── app.wxss                        # ★ CSS 变量全局主题
├── utils/
│   ├── util.js                     # （模板保留）
│   ├── config.js                   # ★ 后端 API 地址（开发/生产）
│   ├── identity.js                 # ★ 匿名身份管理（wx.StorageSync）
│   └── api.js                      # ★ wx.request 封装 + 推荐/收藏/登录 API
└── pages/
    └── index/
        ├── index.js                # ★ 首页逻辑（搜索/推荐/收藏/登录预留）
        ├── index.wxml              # ★ 首页模板（搜索框/推荐卡片）
        ├── index.wxss              # ★ 首页样式（银杏玻璃态）
        └── index.json              # （模板保留）
```

### 小程序功能

| 功能 | 说明 |
|------|------|
| 搜索框 | textarea 输入自然语言需求，自动撑高 |
| 快捷提示 | 4 个预设 prompt 按钮，一键填充 |
| 推荐卡片 | 店名/收藏按钮/匹配度/推荐理由/校区/人均价格 |
| 收藏按钮 | ☆/★ 切换，状态通过 view model 驱动（`isFavorite`/`isFavLoading`），收藏后不整页重刷 |
| 微信登录 | `wx.login()` → `/api/auth/wechat-login` → JWT 持久化 → 自动拉收藏列表 |
| 匿名身份 | 首次启动生成 `anon_<ts36><random>`，`wx.StorageSync` 持久化 |
| Token 管理 | 提前 30s 过期降级，`onLoad()` 有 token 才拉收藏，避免无效请求 |

### 关键设计决策

- **原生 JS 开发**：不引入 TypeScript / Taro / uni-app，保持小程序轻量
- **匿名优先**：不强制登录，`app.js` 启动即初始化匿名 ID，后续所有埋点/推荐请求自动携带
- **双端共用身份模型**：`identity.js` 与 Web 端 `identity.ts` 结构一致（`anonymousId / userId / accessToken / tokenExpiresAt`），登录后均可绑定匿名行为
- **View Model 预处理**：`buildRecommendationViewModels()` 在 JS 端把推荐原始数据转为 WXML 友好的 view model（`shopId`/`isFavorite`/`isFavLoading`/`matchPercent`），WXML 模板只做纯展示，零字段计算
- **收藏状态增量刷新**：`refreshRecommendationFavoriteState()` 收藏操作后只更新 `favIds` + 重建 view model，不重新请求推荐接口
- **微信登录闭环**：`wx.login()` → `api.wechatLogin(code)` → `saveAuthenticatedIdentity()` → `loadFavorites()`，登录完直接同步收藏状态，Web 端的"粘贴 code"调试入口不再需要
- **按需加载收藏**：`onLoad()` 先检查 `getAuthToken()`，有 token 才调 `/api/v1/favorites`，未登录不浪费请求

### 运行方式

```bash
# 1. 启动后端
cd backend
uvicorn app.main:app --reload --port 8000

# 2. 微信开发者工具 → 导入项目 → 选择 miniprogram/ 目录

# 3. 开发阶段勾选：详情 → 本地设置 → 不校验合法域名

# 4. 输入测试 query → 点生成推荐 → 看到卡片
```

### 章末检查

- [x] 微信开发者工具能打开 `miniprogram/`
- [x] 首页不再是模板 `Hello World`
- [x] 首页能输入自然语言需求
- [x] 能请求后端 `/api/recommend`
- [x] 能展示推荐卡片（店名/理由/匹配度/校区/价格）
- [x] 匿名 ID 能写入并从 `wx.StorageSync` 读取
- [x] `deepseek_rerank` 模式下不会显示原始 JSON（`match_score` 预处理为字符串百分比）
- [x] 收藏按钮已实现，未登录时有清晰 toast 提示
- [x] `wx.login()` 完整登录闭环（获取 code → 换 JWT → 持久化 → 加载收藏）

---

## Chapter 11 完成：多端账号体系升级

**目标**：Web 端支持邮箱注册/登录，小程序端继续微信登录，统一 JWT 鉴权，为后续账号绑定预留数据结构。

### 新增文件

```
backend/
├── app/services/
│   ├── password_service.py       # ★ PBKDF2 HMAC-SHA256 密码哈希
│   └── account_service.py        # ★ 邮箱用户 CRUD + 微信用户占位
└── tests/
    └── test_chapter11.py          # 15 个测试（密码/注册/登录/收藏鉴权）

backend/data/schema.sql           # +2 表
frontend/src/
├── app/
│   ├── page.tsx                  # + 登录/注册/登出面板
│   └── globals.css               # + 登录状态/切换链接样式
└── lib/
    └── api.ts                    # + emailRegister/emailLogin
```

### 后端新增接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/auth/email-register` | 邮箱 + 密码注册，返回 JWT |
| POST | `/api/auth/email-login` | 邮箱 + 密码登录，返回 JWT |

### 新增数据表

```sql
users (id, email UNIQUE, password_hash, created_at, updated_at)
wechat_identities (id, user_id FK→users, openid_hash UNIQUE, created_at)
```

### 关键设计决策

- **PBKDF2 标准库实现**：`hashlib.pbkdf2_hmac("sha256", ...)` + `hmac.compare_digest()` 常量时间比较，存储格式 `pbkdf2_sha256$iterations$salt$hash`，无额外依赖
- **user_id 命名空间**：邮箱用户 `em_<uuid16>`，微信用户 `wx_<sha256[:24]>`，通过前缀区分来源
- **双表设计**：`users` 作为统一身份主体，`wechat_identities` 存微信绑定关系，后续加 QQ/手机号登录只需加新关联表
- **微信登录同步写入**：`wechat_auth_service.py` 内部调用 `ensure_wechat_user()` + `save_wechat_identity()` 写入 users 表和 wechat_identities 表，为 Phase 2 账号绑定做准备
- **密码不存明文**：全程只有哈希，即使数据库泄露也无法还原密码
- **Web 登录面板**：登录/注册切换弹窗，Enter 提交，登录后自动加载收藏列表，登出清空状态

### Phase 1 vs Phase 2

| | Phase 1（已完成） | Phase 2（规划） |
|---|---|---|
| Web 邮箱注册/登录 | 完成 | — |
| JWT 统一鉴权 | 完成 | — |
| 密码哈希存储 | 完成 | — |
| 微信用户写入 users | 幂等占位 | — |
| wechat_identities 记录 | 写入 openid_hash | — |
| 微信绑定邮箱 | — | `/api/auth/bind-email` |
| 数据合并 | — | 收藏/反馈/行为归属迁移 |

### 测试覆盖（15 tests）

| 测试类 | 覆盖内容 |
|--------|----------|
| TestPasswordService (5) | 哈希验证回环、错误密码拒绝、不同盐值、坏格式、空密码 |
| TestEmailRegister (4) | 注册成功、重复邮箱 409、短密码 422、无效邮箱 422 |
| TestEmailLogin (4) | 登录成功、错误密码 401、不存在用户 401、空字段 422 |
| TestAuthWithEmailToken (2) | 邮箱 token 访问 auth/me、邮箱 token 收藏店铺 |

---

## Chapter 12 完成：Web 个人中心

**目标**：在 Next.js Web 前端新增 `/profile` 个人中心页面，展示用户信息与收藏列表，支持取消收藏和退出登录。

### 新增/修改文件

```
frontend/src/
├── app/
│   ├── profile/
│   │   └── page.tsx              # ★ 个人中心页面（3 种状态）
│   ├── page.tsx                  # + 个人中心入口链接 + logoutIdentity 复用
│   └── globals.css               # + 个人中心/收藏列表/空状态样式
└── lib/
    ├── identity.ts               # + logoutIdentity() 统一退出登录
    └── api.ts                    # + getMe() 验证 JWT token
```

### 页面三种状态

| 状态 | 触发条件 | 展示内容 |
|------|----------|----------|
| 加载中 | 进入页面后请求 `/api/auth/me` | 骨架屏 loading |
| 未登录 | 无 token 或 token 失效 | 匿名提示 + 去登录按钮 + 返回推荐页 |
| 已登录 | token 有效 | userId + 账号类型 + 收藏列表 + 退出登录 |

### 核心交互

- **token 校验**：进入 `/profile` 先调 `GET /api/auth/me`，不信任 localStorage
- **token 失效处理**：校验失败自动调用 `logoutIdentity()` 清理登录态
- **收藏列表**：调 `GET /api/v1/favorites`，展示店名/收藏日期/shop_id
- **取消收藏**：调 `DELETE /api/v1/favorites`，成功后本地移除该项，失败保留原列表并提示
- **退出登录**：复用 `logoutIdentity()` 清除 localStorage + 重置页面状态
- **空收藏**：显示"还没有收藏饭馆" + "去首页推荐"按钮
- **页面导航**：首页 composer footer 新增"个人中心"入口，个人中心有"返回推荐页"链接

### 关键设计决策

- **不信任前端 localStorage**：每次进入 `/profile` 都调 `/api/auth/me` 验证 token 有效性，防止展示"假登录"状态
- **复用已有接口**：不新增后端接口，只消费已有的 `/api/auth/me`、`/api/v1/favorites`（GET/DELETE）
- **账号类型识别**：通过 userId 前缀自动判断（`em_` = 邮箱账号，`wx_` = 微信账号）
- **统一登出**：`logoutIdentity()` 同时被首页和个人中心复用，保证登出行为一致

### 章末检查清单

- [x] 打开 `/profile` 不报错
- [x] 未登录访问 `/profile` 显示登录引导
- [x] 邮箱登录后访问 `/profile` 能看到自己的 `userId`
- [x] 收藏饭馆后访问 `/profile` 能看到收藏列表
- [x] 在 `/profile` 取消收藏后，列表会更新
- [x] token 失效时，不会继续展示"已登录"假状态
- [x] 首页可以进入个人中心，个人中心可以返回首页
- [x] `next build` 编译成功，3 个路由全部正常

### 本章知识点

- Next.js App Router 页面拆分（`/` + `/profile`）
- 前端登录态恢复与 JWT token 校验
- 受保护接口调用（`getMe` / `fetchFavorites` / `removeFavorite`）
- 个人中心页面状态设计（loading / not-logged-in / logged-in）
- 空状态、错误状态、加载状态处理
- 用户收藏数据的前后端闭环
