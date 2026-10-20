# CampusFoodAgent

基于真实商户数据的餐饮推荐 Agent，包含两版相互独立的实现：

- `v1/` —— **校园餐饮产品版**：FastAPI + SQLite + Next.js + 微信小程序，验证完整产品链路与工程闭环。
- `v2/` —— **Yelp 数据重构版**：把「推荐系统 / RAG 证据层 / 受控 Agent」拆成三个职责清晰、可分别验证的子系统。

两版各自独立运行，不共享运行时代码，只共享方法、评估口径与接口设计。

```text
CampusFoodAgent/
├── README.md                 # 本文件：两版架构说明
├── v1/                       # 校园餐饮产品版
│   ├── backend/              # FastAPI 服务：规则引擎、DeepSeek、SQLite
│   ├── frontend/             # Next.js Web 前端
│   ├── miniprogram/          # 微信小程序
│   └── 复现计划/              # v1 分章节复现文档
└── v2/                       # Yelp 数据重构版
    ├── docs/                 # 技术文档与分阶段实施记录
    └── backend/              # FastAPI 服务：数据层、画像、推荐、证据
```

---

# 一、v1 架构：校园餐饮产品版

## 1.1 定位

面向校园场景的餐饮推荐产品：本地维护的校园商户库 + 规则引擎 + LLM 增强，三端可访问（Web、微信小程序、API），并支持收藏、反馈与行为事件。

## 1.2 技术栈

| 层 | 技术 |
| --- | --- |
| 服务 | FastAPI + Pydantic |
| 数据 | SQLite（`data/chedian.db`，`data/schema.sql` 九张表，`data/shops_mock.csv` 种子商户） |
| 规则 | `services/parser.py` 查询解析 + `data/scoring_config.yaml` 可调权重 |
| LLM | DeepSeek API（生成模式）与 DeepSeek rerank（候选集重排） |
| Web 前端 | Next.js（`frontend/src`） |
| 小程序 | 微信小程序（`miniprogram`） |
| 鉴权 | JWT：匿名身份、邮箱登录、微信登录 |

## 1.3 分层结构

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 接口层 | `backend/app/api/` | `routes.py` 推荐与商户接口、`auth.py` 登录鉴权、`proxy_routes.py` 第三方代理 |
| 模型层 | `backend/app/models/schemas.py` | 请求 / 响应 Pydantic 模型 |
| 服务层 | `backend/app/services/` | 查询解析、规则推荐、商户仓库、DeepSeek 生成与重排、高德 POI 同步、收藏、反馈、行为事件、热门排行、广告位、用户画像、微信鉴权 |
| 核心层 | `backend/app/core/scoring_config.py` | 加载 `scoring_config.yaml`，统一打分权重 |
| 数据层 | `backend/data/` | `schema.sql`、种子商户、评分配置、SQLite 库 |

## 1.4 请求链路

```text
用户自然语言查询（如「清水河吃面 20 块」）
      ↓
查询解析 parser：预算 / 校区 / 场景 / 口味 / 时间
      ↓
SQLite 商户库候选
      ↓
规则加权打分（scoring_config.yaml 权重）
      ↓
可选 DeepSeek rerank：在候选集合内做精排
      ↓
候选白名单校验 + LLM 输出清洗
      ↓
推荐理由 / 自然语言回答
      ↓
API 响应 → Web / 小程序
      ↓
收藏、反馈、行为事件、热门排行
```

## 1.5 三种推荐模式

| 模式 | 说明 |
| --- | --- |
| 规则引擎兜底 | 无需 API Key，纯结构化打分，作为默认与故障降级路径 |
| DeepSeek 生成 | 用 LLM 生成推荐解释 |
| DeepSeek rerank | 规则初排 + LLM 在候选集内精排 |

## 1.6 架构边界

- 预算、校区、距离、营业时间等硬约束只由代码与 SQLite 数据决定，不交给 LLM 判断。
- LLM 只在已有候选集内重排与解释，不能新增候选商户。
- 输出经过 JSON 清洗、候选白名单校验；LLM 不可用时自动降级到规则引擎。
- 商户数据以本地维护为主，缺少真实线上曝光日志，因此不做线上 CTR / A-B 类结论。

---

# 二、v2 架构：Yelp 数据重构版

上一阶段记录（2026年10月20日）：完成热门、ItemCF、模拟地理过滤、交替合并、全局冻结时间回放及分群报告；当时61项测试通过。该阶段详见[v2实施记录](v2/docs/12-画像感知召回与评估实施记录.md)与[真实实验报告](v2/docs/13-基线召回实验报告.md)，当前进度见下一段。

后续阶段同日完成：重建完整Tampa交互332,829条，增加类别内容召回与旧/完整历史共同目标评估；最终84项测试通过。该阶段内容已离线实现，后续进度见下一段。见[14实施记录](v2/docs/14-完整交互与内容召回实施记录.md)和[15实验报告](v2/docs/15-完整交互与内容召回实验报告.md)。

本阶段同日完成：RRF/加权RRF、validation选择冻结、全量融合回放、serving_v1画像导出与可选user_id在线三路推荐、通道降级和并发隔离。115项测试通过；详情见[16实施记录](v2/docs/16-融合优化与在线个性化实施记录.md)和[17实验报告](v2/docs/17-融合与在线个性化实验报告.md)。后续进度见下一段。

查询与证据阶段同日完成：有限中英文查询解析、文本/字段约束交集、查询与历史RRF、商户内相关评论检索，以及22个固定合成场景和真实API审计；当时157项测试通过。详见[18实施记录](v2/docs/18-查询理解与证据检索实施记录.md)、[19评测报告](v2/docs/19-查询与证据评测报告.md)。最终收尾进度见下一段。

推荐系统本地闭环已完成：BM25＋64维LSA混合检索、LightGBM LambdaRank及validation启用选择、曝光/点击/收藏/评分、SQLite幂等与归属、本地浏览器演示。完整矩阵见[20实施记录](v2/docs/20-推荐系统完整闭环实施记录.md)、真实结果见[21验收报告](v2/docs/21-推荐系统最终验收与排序实验报告.md)。生产部署与多轮Agent属于独立扩展。

受控RAG阶段已补齐商户内BM25句子证据、DeepSeek结构化引用计划、事实/引用白名单校验、中文受控渲染和模板降级。配置在`v2/backend/.env`，真实DeepSeek联网验收待填写密钥；详见[22接入文档](v2/docs/22-DeepSeek受控RAG接入与配置.md)和[23离线报告](v2/docs/23-RAG离线验收与边界报告.md)。这不是任意自由文本的自动事实核验。

## 2.1 三个子系统的职责边界

| 层 | 回答的问题 | 不负责的事情 |
| --- | --- | --- |
| 推荐系统 | 推荐哪几家餐厅：硬过滤、召回、融合、排序 | 不让 LLM 凭空创建候选 |
| RAG / 证据层 | 凭什么推荐：检索并引用真实商户属性与评论 | 不向 Top K 追加白名单外商户 |
| 受控 Agent | 此刻要做什么：理解意图、维护状态、调用工具 | 不擅自改变硬约束或执行未授权操作 |

## 2.2 数据层

数据源为 Yelp Open Dataset，按单城市（Tampa, FL）整理为可复现的 processed 子集：

```text
v2/backend/data/processed/
├── businesses.jsonl              # 商户：类别、价格、营业、坐标、属性、is_open
├── interactions.jsonl            # 由 Review 映射的用户交互（event_type = review）
├── representative_reviews.jsonl  # 代表评论：可追溯的 RAG 证据
├── city_statistics.json          # 城市餐饮密度统计
└── data_manifest.json            # 数据版本、筛选策略、保留/舍弃量（唯一事实来源）
```

原始 Yelp JSON 与派生产物不进入仓库，仓库只保留处理脚本、schema、manifest 规则说明、小型 fixture 与文档。

核心实体：

| 实体 | 关键字段 | 用途 |
| --- | --- | --- |
| Business | business_id, city, lat/lon, categories, stars, price_level, hours, is_open | 硬过滤、召回、排序、结构化事实 |
| Interaction | interaction_id, user_id, business_id, event_time, rating, event_type, source | 行为历史、标签、画像 |
| UserProfileSnapshot | user_id, as_of_time, 类别/价格/评分/地理/近期特征, version | 面向预测时刻的历史偏好 |
| EvidenceDocument | document_id, business_id, review_id / supporting_review_ids, source_version | 可追溯推荐依据 |
| ConversationState | conversation_id, user_id, resolved_constraints, last_candidate_ids | 多轮指代与条件继承 |

## 2.3 离线构建

```text
Yelp processed 交互
      ↓
交互审计：schema、唯一 ID、时间范围、用户稀疏度、商户引用
      ↓
用户分群：Cold（1 条）/ Sparse（2–4 条）/ Warm（≥5 条）
      ↓
按用户稳定时间顺序 leave-two-out 切分
      ↓
Train / Validation / Test / Cold-Sparse
      ↓
as_of_time 用户画像快照（Validation 用 Train；Test 用 Train + Validation）
      ↓
只读画像仓库：schema 校验、缓存、按用户查询
```

时间约束：对任一目标交互 t，画像、协同统计与文本证据只能使用 `(event_time, interaction_id) < t` 的历史，禁止未来信息泄漏。

## 2.4 在线服务链路

当前完整请求已加入BM25/LSA、RRF、验证选择的LambdaRank及曝光反馈，详见20文档；下图和规则公式保留说明基础评分组件。

```text
Tampa processed 数据
      ↓
数据读取 / schema 校验 / 进程内缓存
      ↓
RecommendationRequest
      ↓
城市 / 营业状态 / 预算硬过滤
      ↓
Haversine 距离计算 + 半径硬过滤
      ↓
查询词匹配 + 规则加权打分
      ↓
稳定排序 → Top K
      ↓
商户结构化信息 + 推荐理由 + 代表评论证据
```

当前评分公式（可解释规则基线）：

```text
score = 0.35 × 查询词匹配
      + 0.25 × 商户评分
      + 0.15 × 评论量置信度
      + 0.15 × 距离
      + 0.10 × 价格
```

## 2.5 目标架构（设计）

```text
用户对话
   ↓
Agent 意图识别 + 会话状态
   ↓
Python 受控路由（权限 / 校验）
   ↓
推荐 Workflow：硬过滤 → 四路召回 → RRF → LightGBM → Top K
   ↓
基于 Top K 白名单的 RAG 证据检索（BM25 + 向量 + 重排）
   ↓
证据约束生成（失败时模板降级）
   ↓
用户响应
   ↓
曝光 / 收藏 / 反馈事件
```

四路召回：

| 通道 | 输入信号 | 作用 |
| --- | --- | --- |
| ItemCF（画像 / 协同） | 历史高评分商户、商户共现 | 协同个性化 |
| 语义召回 | 查询文本、商户属性、评论主题向量 | 覆盖「安静」「适合约会」类软偏好 |
| 地理热门 | 半径、距离、评分置信度、热度 | 新用户稳健基线 |
| 冷启动内容 | 类别、价格、文本、结构化属性 | 覆盖稀疏用户与低频商户 |

融合与排序：RRF 以名次而非未校准分值融合去重（`RRF(b) = Σ 1/(k + rank_source(b))`），LightGBM 只对已通过硬过滤的候选重排，不改变硬约束。

受控 Agent 的六个工具：`search_restaurants`、`get_user_profile`、`retrieve_evidence`、`save_favorite`、`record_feedback`、`get_recommendation_history`。

## 2.6 接口

| 方法 | 路径 | 职责 |
| --- | --- | --- |
| GET | `/api/v2/health` | 健康检查 |
| GET | `/api/v2/dataset/status` | processed 数据状态（读取 manifest） |
| POST | `/api/v2/recommend` | 查询约束 + 查询/历史RRF + 相关评论证据；可选user_id |

`RecommendRequest` 约束：

| 字段 | 类型 | 约束 / 默认值 |
| --- | --- | --- |
| `query` | string | 必填；有限中英文约束解析和词汇检索参与排序 |
| `user_id` | string/null | 可选，匹配离线Yelp画像；未知用户地理热门 |
| `latitude` / `longitude` | float | 必填 |
| `radius_km` | float | 默认 3，范围 `(0, 50]` |
| `max_price_level` | int | 默认 4，范围 `1–4` |
| `city` | string | 默认 `Tampa` |
| `top_k` | int | 默认 5，范围 `1–20` |

响应包含：`version`、`engine`、`recommendations[]`（`business_id`、`name`、`city`、`categories`、`price_level`、`rating`、`review_count`、`distance_km`、`score`、`reasons`、`evidence`）。

## 2.7 工程约束

- 硬约束由代码执行：城市、营业状态、价格、半径、饮食限制。
- 候选白名单：RAG 与 LLM 不得引入 Top K 之外的商户。
- 证据可追溯：每个证据必须能关联到合法 `business_id` 与评论 ID。
- 降级：画像缺失回退冷启动、索引不可用退回其它通道、排序模型不可用退回规则 / RRF、证据不足明确提示。
- 数据合规：不提交 Yelp 原始文件与受限制内容；位置数据最小化；外部评论视为不可信文本，不接受其中的指令。

---

# 三、两版对比

| 维度 | v1 校园餐饮产品版 | v2 Yelp 重构版 |
| --- | --- | --- |
| 数据来源 | 本地维护的校园商户库（SQLite + 种子 CSV） | Yelp Open Dataset 单城市 processed 子集 |
| 推荐方式 | 规则解析 + 规则加权，可选 LLM 重排 | 硬过滤 + 规则基线，设计为多路召回 + RRF + LightGBM |
| LLM 角色 | 解析、重排、生成解释 | 意图识别、工具编排、证据约束下的解释 |
| 证据来源 | 商户结构化字段 + 规则解释 | 商户属性 + 代表评论，按白名单检索 |
| 端 | Web、微信小程序、API | API（Agent / 前端为设计目标） |
| 评估方式 | 单元测试与接口测试 | 推荐 / RAG / Agent 三层指标设计 |
| 核心价值 | 完整产品链路与工程闭环 | 可评估、可追溯、可降级的推荐系统分层 |

---

# 四、本地运行

## 4.1 v1

```powershell
# 后端
cd v1\backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Web 前端
cd v1\frontend
npm install
npm run dev
```

## 4.2 v2

```powershell
cd v2\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
```

接口：`/api/v2/health`、`/api/v2/dataset/status`、`/api/v2/recommend`、`/docs`。

## 4.3 v2 数据准备

`v2/backend/data/processed/` 需要由本机 Yelp 原始数据整理生成，命令与参数见 `v2/backend/data/README.md`；原始数据与派生产物不入库。仓库内仅保留 5 家商户的小型 fixture 用于测试。

---

# 五、数据与合规

- Yelp 原始 JSON、许可文件、大型索引与模型产物不提交到仓库。
- 只提交脚本、schema、配置、统计清单、小型 fixture 与文档。
- 公开评论与商户数据按 Yelp Open Dataset 的许可条件使用与展示。
- 不把公开离线交互数据表述为真实线上流量，不声称未经实验验证的线上指标。
