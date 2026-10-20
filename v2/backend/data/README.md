# CampusFoodAgent v2 数据取舍说明

本文档说明本项目如何从 Yelp Open Dataset 中取舍数据，并解释每类数据进入或不进入首版链路的原因。

## 目标

CampusFoodAgent v2 的目标不是加载 Yelp 全量数据，而是构建一个本地可运行、面试可解释、证据可追溯的餐饮推荐 Agent。首版数据策略遵循三条原则：

1. 只保留能支撑推荐、RAG 证据和 Agent 工具调用的字段。
2. 先选择一个数据密度足够的城市，避免全量清洗和索引拖慢开发。
3. 所有取舍写入 `processed/data_manifest.json`，方便复现实验和面试说明。

## 原始数据位置

原始 Yelp 文件放在：

```text
backend/data/archive/
```

当前目录中包含：

```text
Dataset_User_Agreement.pdf
yelp_academic_dataset_business.json
yelp_academic_dataset_review.json
yelp_academic_dataset_user.json
yelp_academic_dataset_checkin.json
yelp_academic_dataset_tip.json
```

原始数据不应提交到仓库。仓库只提交处理代码、说明文档、测试和小型 fixture。

## 首版保留什么

### 1. Business：保留，作为核心商户库

源文件：

```text
yelp_academic_dataset_business.json
```

保留原因：

- 提供真实商户 ID、名称、城市、经纬度、类别、评分、评论数。
- 支撑硬约束过滤：城市、距离、是否营业、价格、餐饮类别。
- 支撑 RAG 中的结构化证据：类别、价格、营业时间、属性。

当前处理策略：

- 只保留 `categories` 包含 `Restaurants`、`Food`、`Coffee` 或 `Bars` 的商户。
- 只保留被选中城市内的餐饮/食品商户。
- 保留 `is_open` 字段，不在数据层直接删除关闭商户；在线推荐时由硬过滤决定是否可推荐。
- 标准化输出到 `processed/businesses.jsonl`。

输出字段：

```text
business_id
name
categories_raw
categories_normalized
latitude
longitude
city
state
stars
review_count
price_level
hours
attributes
is_open
data_version
```

### 2. Review：保留筛选后的子集，映射为交互和证据

源文件：

```text
yelp_academic_dataset_review.json
```

保留原因：

- Yelp review 是本项目最重要的历史交互来源。
- 可以映射为 `Interaction(event_type=review)`，用于用户画像、协同召回和离线评估。
- 评论文本可以作为代表评论，支撑推荐理由和 RAG 证据。

当前处理策略：

- 只保留已选城市、已选商户对应的 review。
- 脚本默认参数为：最多保留 `200000` 条 review、每个商户最多 `50` 条 interaction、每个商户最多 `10` 条 representative review。
- 当前在线使用的 Tampa 子集按 `data_manifest.json` 记录的显式参数生成：`100000` 条 review、每个商户最多 `40` 条 interaction、每个商户最多 `8` 条 representative review（对应 `limits.max_reviews_total`、`max_reviews_per_business`、`representative_reviews_per_business`）。
- 数据规模、处理上限和取舍口径一律以 `data_manifest.json` 为准，不引用脚本默认值。
- representative review 按 `useful`、评分和日期排序，用于第一版 RAG 证据。

Interaction 输出到：

```text
processed/interactions.jsonl
```

字段：

```text
interaction_id
user_id
business_id
event_type
event_time
rating
review_text
source
```

Representative review 输出到：

```text
processed/representative_reviews.jsonl
```

字段：

```text
review_id
business_id
user_id
rating
review_date
useful
text
source
```

## 首版舍弃什么

### 1. User：不进入首版运行链路

源文件：

```text
yelp_academic_dataset_user.json
```

舍弃原因：

- 文件体积很大，当前本地版本没有必要加载完整用户画像文件。
- 首版用户历史可以直接从保留下来的 review interaction 中构造。
- 文档中 User 的首要用途是公开统计和数据质量检查，不是 Agent 推荐链路的硬依赖。
- 面试表述上更清晰：用户画像来自目标城市内的历史交互快照，而不是依赖全量用户文件。

后续如果要做更完整的数据质量分析，可以单独抽取 user 统计字段，但不建议把原始 user 全量作为运行依赖。

### 2. Check-in：延后到热度和活跃时段特征

源文件：

```text
yelp_academic_dataset_checkin.json
```

舍弃原因：

- Check-in 对首版推荐、RAG 和 Agent 白名单不是必需项。
- 它适合用于第二阶段的地理热门、活跃时段或时间衰减特征。
- 首版先用商户评分、评论数、距离和 review 时间构造基础排序，降低中间件和清洗复杂度。

### 3. Tip：延后到短文本 RAG 补充

源文件：

```text
yelp_academic_dataset_tip.json
```

舍弃原因：

- Tip 可以作为短文本证据，但不是主文档中定义的核心实体。
- 第一版 RAG 先使用 business profile 和 representative review，证据来源更简单、更容易追溯。
- 后续可以把 tip 作为 `document_type=tip_evidence` 加入混合检索。

## 城市选择策略

默认不手动指定城市，而是扫描 `business.json` 后自动选择：

1. 餐饮/食品商户数量最多的城市。
2. 如果数量相近，选择开放商户评论数更多的城市。

这样符合架构文档中“选择过程基于数据统计，而不是先指定城市再强行使用”的要求。

当前在线使用的 Tampa 子集是用显式城市参数生成的：`data_manifest.json` 的 `selected_city` 记录为 Tampa, FL，`selection_policy.city` 记录为 “explicitly requested by config”，并且服务默认城市与之一致。复现该子集时需要手动指定城市，例如 Tampa：

```powershell
cd C:\Users\Jianing\Desktop\CampusFoodAgent\v2\backend
python -m app.data_pipeline.curate_yelp `
  --archive-dir data/archive `
  --output-dir data/processed `
  --city Tampa `
  --state FL `
  --max-reviews-total 100000 `
  --max-reviews-per-business 40 `
  --representative-reviews-per-business 8
```

如果不指定城市，使用自动选择：

```powershell
cd C:\Users\Jianing\Desktop\CampusFoodAgent\v2\backend
python -m app.data_pipeline.curate_yelp `
  --archive-dir data/archive `
  --output-dir data/processed
```

## 输出文件

运行后生成：

```text
backend/data/processed/
  businesses.jsonl
  interactions.jsonl
  representative_reviews.jsonl
  city_statistics.json
  data_manifest.json
```

其中：

- `businesses.jsonl`：目标城市餐饮/食品商户。
- `interactions.jsonl`：由 Yelp review 映射的历史交互。
- `representative_reviews.jsonl`：每个商户有限条高价值评论证据。
- `city_statistics.json`：城市餐饮密度统计。
- `data_manifest.json`：本次取舍、限制、保留量和舍弃量。

## Manifest 记录内容

`data_manifest.json` 会记录：

```text
data_version
selected_city
selection_policy
limits
kept
discarded
retained_raw_sources
excluded_raw_sources
outputs
```

面试或复现实验时，优先引用 manifest 中的数字，不手写估算值。

## 当前默认取舍总结

| 数据 | 首版处理 | 原因 |
| --- | --- | --- |
| Business | 保留目标城市餐饮/食品商户 | 商户库、硬过滤、结构化证据核心 |
| Review | 保留目标商户子集并限量 | 交互、画像、代表评论证据核心 |
| User | 不保留全量 | 可由 review 交互派生用户历史 |
| Check-in | 暂不保留 | 第二阶段热度和活跃时段特征 |
| Tip | 暂不保留 | 第二阶段短文本 RAG 补充 |

## 面试表述

2026年10月20日新增离线目录：`derived/baseline_recall_v1/`，包含全局截止点画像、ItemCF邻居、候选trace、指标、报告和输入/代码SHA256。不覆盖`time_split_v1`或`profile_v1`；完整产物不提交仓库。复现与结果见`v2/docs/12-画像感知召回与评估实施记录.md`和`13-基线召回实验报告.md`。

同日下一阶段新增`derived/tampa_full_reviews_v1/`（同一商户集合全部332,829条紧凑交互）和`derived/fullcity_content_v1/`（共同目标旧/新历史及类别内容对照）。省略评论正文的新交互仅用于离线研究，不直接替代在线processed。目录以完整版本切换发布，保留`.目录名.previous-*`备份；读入完整数据时校验manifest中的产物哈希。详见14/15文档。

可以这样说明：

> Yelp 全量数据超过本地演示和第一阶段建模需求。我先按城市和餐饮类别做统计，选择餐饮商户与评论覆盖足够的单城市子集；Business 作为结构化商户库，Review 映射为统一 Interaction，并保留代表评论作为 RAG 证据。User 全量文件不进入主链路，用户画像从历史 review 交互快照构造；Check-in 和 Tip 延后到热度特征和短文本证据扩展。所有过滤前后规模、保留来源和舍弃原因写入 manifest，保证可复现和可追溯。


2026年10月20日本阶段新增`derived/fusion_v1/`（validation选参冻结、融合回放）和`derived/serving_v1/`（120,220个全历史用户画像及三路模型）。在线商户与代表评论仍取processed；个性化请求只读serving快照，不现场训练或读取全量Review。构建命令、快照边界和重载方式见16文档；聚合结果见17文档。画像/模型/用户级trace保持本地，不提交Git。

查询阶段新增版本化小型人工数据`fixtures/query_cases_v1.json`和`derived/query_v1`评测产物。不需要复制或覆盖processed、完整交互或serving快照；真实历史数据不用于捏造查询标签。复现：`python -B -m app.evaluation.query_study`，见18/19文档。
