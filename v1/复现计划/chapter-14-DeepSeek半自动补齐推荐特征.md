# Chapter 14：DeepSeek 半自动补齐推荐特征

## 目标

本章目标是在第 13 章“高德 POI 数据源”的基础上，使用 DeepSeek 对缺失的推荐特征进行半自动补齐。

高德地图解决了“有哪些店、在哪里”的问题，但它无法稳定提供：

- 人均价格
- 口味标签
- 场景标签
- 推荐理由
- 是否适合推荐
- 适合什么预算
- 适合几个人吃
- 是否适合夜宵 / 聚餐 / 一人食

这些特征才是推荐系统真正用于排序和解释的核心数据。

本章最终效果：

- 能扫描 `shops` 表中缺失推荐特征的店铺。
- 能构造 DeepSeek Prompt，让模型生成候选特征。
- 候选特征先进入“待确认”状态，不直接污染正式推荐字段。
- 人工确认后，再写入 `shops.tastes`、`shops.scenes`、`shops.tags`、`avg_price` 等字段。
- 给每家店计算一个 `data_quality_score`，用于判断是否进入推荐池。

## 本章定位

第 13 章完成的是：

```text
高德 POI → shops 基础字段
```

第 14 章要完成的是：

```text
shops 基础字段 → DeepSeek 生成候选推荐特征 → 人工确认 → 推荐可用数据
```

注意：

DeepSeek 不是事实来源，它只是“特征生成助手”。

所以不能让 DeepSeek 直接决定最终数据，而是让它生成候选值，再由你确认。

## 为什么不能直接让 DeepSeek 改正式字段

因为 DeepSeek 可能会：

- 编造不存在的人均价格。
- 把咖啡店误判成适合正餐。
- 只根据店名猜错口味。
- 对同类店生成过于相似的标签。
- 把不适合推荐的 POI 也当成饭馆。

所以本章必须采用：

```text
LLM 生成候选 → 写入 draft / pending → 人工确认 → 正式入库
```

这比“让 AI 直接写数据库”更专业。

## 需要补齐哪些特征

### 1. 价格特征

字段：

```text
avg_price
avg_price_min
avg_price_max
```

作用：

- 支持预算过滤。
- 支持“20 元以内”“便宜点”“性价比高”的查询。

DeepSeek 可以根据店名、类别、地点给出估计值，但必须标记为“估算”。

建议价格范围：

```text
食堂：8 - 18
米线 / 面 / 粉：12 - 25
快餐 / 盖饭：15 - 30
奶茶 / 咖啡：10 - 30
火锅 / 烧烤：35 - 80
聚餐餐厅：40 - 100
甜品：12 - 35
```

### 2. 口味特征

字段：

```text
tastes
```

建议候选值：

```text
清淡
麻辣
微辣
重口
鲜香
酸辣
甜口
咸鲜
家常
油香
咖啡
奶香
冰爽
```

作用：

- 支持“想吃清淡”“想吃辣”“不想太油”的推荐。

### 3. 场景特征

字段：

```text
scenes
```

建议候选值：

```text
一人食
同学聚餐
情侣约饭
赶时间
夜宵
早餐
午餐
晚餐
下午茶
宿舍外卖
健身餐
低预算
高性价比
校内就近
西门周边
龙湖周边
```

作用：

- 支持“一个人吃”“聚餐”“赶时间”“晚上吃点东西”的推荐。

### 4. 普通标签

字段：

```text
tags
```

建议候选值：

```text
高德POI
食堂
咖啡
奶茶
米线
面食
粉面
快餐
川菜
烧烤
火锅
炸鸡
甜品
小吃
盖饭
性价比
出餐快
适合学生
```

作用：

- 支持召回、筛选和推荐理由生成。

### 5. 推荐可用性

建议新增概念：

```text
is_recommendable
data_quality_score
feature_source
feature_review_status
```

如果暂时不改 `shops` 表，也可以先放在一个新表里。

含义：

```text
is_recommendable        是否进入正式推荐池
data_quality_score      数据质量分
feature_source          特征来源，例如 manual / deepseek_draft / amap
feature_review_status   pending / approved / rejected
```

## 推荐新增数据表

为了避免 DeepSeek 直接污染 `shops`，建议新增一张候选特征表：

```sql
CREATE TABLE IF NOT EXISTS shop_feature_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL,
    shop_name TEXT NOT NULL,
    avg_price REAL,
    avg_price_min REAL,
    avg_price_max REAL,
    tastes_json TEXT,
    scenes_json TEXT,
    tags_json TEXT,
    confidence REAL,
    reason TEXT,
    source TEXT DEFAULT 'deepseek',
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(shop_id, source)
);
```

状态说明：

```text
pending   DeepSeek 已生成，等待人工确认
approved  人工确认，可以写入 shops
rejected  人工拒绝，不使用
```

## 推荐新增文件

建议新增：

```text
backend/app/services/feature_gap_service.py
backend/app/services/deepseek_feature_service.py
backend/app/services/feature_draft_repository.py
backend/scripts/generate_shop_features.py
backend/scripts/apply_feature_drafts.py
backend/tests/test_feature_generation.py
```

职责：

```text
feature_gap_service.py
  - 扫描 shops 表
  - 找出缺少 avg_price / tastes / scenes / tags 的店
  - 计算 data_quality_score

deepseek_feature_service.py
  - 构造 Prompt
  - 调用 DeepSeek
  - 解析 JSON
  - 做候选值白名单过滤

feature_draft_repository.py
  - 保存 shop_feature_drafts
  - 查询 pending drafts
  - approve / reject drafts

generate_shop_features.py
  - 命令行入口
  - 批量生成候选特征
  - 支持 dry-run

apply_feature_drafts.py
  - 将 approved drafts 写入 shops
```

## 特征缺失判断

一条店铺如果满足下面任意条件，就认为需要补特征：

```text
avg_price IS NULL
tastes 为空数组
scenes 为空数组
tags 为空数组或只有 ["高德POI", typecode]
category 不为空但没有业务标签
```

伪代码：

```python
def needs_feature_completion(shop):
    if shop["avg_price"] is None:
        return True
    if json_list_empty(shop["tastes"]):
        return True
    if json_list_empty(shop["scenes"]):
        return True
    if only_amap_tags(shop["tags"]):
        return True
    return False
```

## 数据质量分

建议设计一个简单的数据质量分：

```text
基础字段完整度：40 分
推荐字段完整度：50 分
人工确认加分：10 分
```

示例：

```text
有 name                 +10
有 category             +10
有 address              +10
有 longitude/latitude   +10
有 avg_price            +15
有 tastes               +10
有 scenes               +10
有 tags                 +10
人工确认 approved       +10
```

判断：

```text
>= 70   可以进入推荐池
40-69   可以作为候选，但推荐权重降低
< 40    不进入推荐池
```

## DeepSeek Prompt 设计

输入给 DeepSeek 的信息必须只包含数据库已有信息：

```text
店名
地址
类别
区域
高德 typecode
校区
经纬度
```

不要让 DeepSeek 自称知道真实评价和真实价格。

Prompt 示例：

```text
你是校园餐饮推荐系统的数据标注助手。

请根据以下店铺基础信息，为它生成“候选推荐特征”。
注意：
1. 你只能根据店名、类别、地址进行合理推断。
2. 不要编造真实评分、真实评论数、真实营业时间。
3. 人均价格只能给估算范围。
4. tastes、scenes、tags 必须从给定白名单中选择。
5. 输出必须是合法 JSON，不要输出 Markdown。

店铺信息：
- name: {name}
- campus: {campus}
- area: {area}
- address: {address}
- category: {category}
- tags: {tags}

口味白名单：
["清淡","麻辣","微辣","重口","鲜香","酸辣","甜口","咸鲜","家常","油香","咖啡","奶香","冰爽"]

场景白名单：
["一人食","同学聚餐","情侣约饭","赶时间","夜宵","早餐","午餐","晚餐","下午茶","宿舍外卖","健身餐","低预算","高性价比","校内就近","西门周边","龙湖周边"]

标签白名单：
["食堂","咖啡","奶茶","米线","面食","粉面","快餐","川菜","烧烤","火锅","炸鸡","甜品","小吃","盖饭","性价比","出餐快","适合学生"]

请输出：
{
  "avg_price": number,
  "avg_price_min": number,
  "avg_price_max": number,
  "tastes": [],
  "scenes": [],
  "tags": [],
  "confidence": number,
  "reason": "一句话说明你的判断依据"
}
```

## 输出校验规则

DeepSeek 输出后，后端必须做校验：

```text
必须是 JSON
avg_price 必须在 1-200 之间
avg_price_min <= avg_price <= avg_price_max
tastes 必须来自口味白名单
scenes 必须来自场景白名单
tags 必须来自标签白名单
confidence 必须在 0-1 之间
reason 长度不能太长
```

如果不符合：

```text
丢弃非法字段
或者整条 draft 标记为 rejected
```

## 命令设计

### 1. 查看缺失特征的店

```powershell
cd backend
python scripts/generate_shop_features.py --list-gaps --limit 30
```

输出示例：

```text
shop_id=81 name=瑞幸咖啡(电子科技大学清水河校区店) missing=avg_price,tastes,scenes
shop_id=82 name=茶百道(电子科大西门店) missing=avg_price,tastes,scenes
```

### 2. dry-run 生成候选特征

```powershell
python scripts/generate_shop_features.py --limit 10 --dry-run
```

只打印，不写库。

### 3. 正式生成 pending drafts

```powershell
python scripts/generate_shop_features.py --limit 30
```

写入：

```text
shop_feature_drafts
```

### 4. 查看待确认候选

```powershell
python scripts/apply_feature_drafts.py --list-pending --limit 30
```

### 5. 批量确认高置信候选

```powershell
python scripts/apply_feature_drafts.py --approve-confidence 0.75
```

说明：

只把 `confidence >= 0.75` 的 draft 标记为 approved。

### 6. 写入 shops 正式字段

```powershell
python scripts/apply_feature_drafts.py --apply-approved
```

写入字段：

```text
avg_price
avg_price_min
avg_price_max
tastes
scenes
tags
```

## 人工确认建议

不要一次确认所有。

推荐流程：

```text
每次生成 20-30 家
人工快速看一遍
明显错误的 reject
基本合理的 approve
再 apply-approved 写入 shops
```

优先补这些店：

```text
有 poi_id
有 category
有 address
有经纬度
店名明确
属于食堂 / 咖啡 / 奶茶 / 米线 / 快餐 / 小吃 / 火锅 / 烧烤
```

暂时不要补：

```text
店名模糊
类别是“餐饮相关场所”
看起来不是饭馆
地址很奇怪
重复店
```

## 覆盖范围目标

你现在数据库大约 100+ 家店。

建议第 14 章目标：

```text
核心高质量推荐池：30-50 家
可推荐数据池：80-120 家
低质量 POI 暂不推荐
```

需要覆盖的类别：

```text
食堂
快餐盖饭
米线粉面
川菜炒菜
火锅
烧烤
炸鸡
咖啡
奶茶
甜品
小吃
早餐
夜宵
聚餐餐厅
低预算餐厅
```

每类至少目标：

```text
食堂：8-15 家
快餐盖饭：10-20 家
粉面米线：10-20 家
咖啡奶茶甜品：10-20 家
火锅烧烤聚餐：8-15 家
小吃夜宵：10-20 家
```

## 推荐系统如何使用这些特征

补齐后，规则推荐可以更稳定地处理：

```text
预算：avg_price
口味：tastes
场景：scenes
类别：tags / category
位置：campus / area / longitude / latitude
质量：data_quality_score
```

建议后续推荐只优先使用：

```text
data_quality_score >= 70
或 feature_review_status = approved
```

这样可以避免刚从高德同步来的低质量 POI 直接进入推荐结果。

## 测试要求

### 单元测试

测试：

```text
缺失字段识别
data_quality_score 计算
DeepSeek JSON 解析
白名单过滤
非法价格过滤
非法标签过滤
draft 保存
approved draft 写入 shops
rejected draft 不写入 shops
```

### 不要真实调用 DeepSeek

测试里用假响应：

```python
fake_llm_output = {
    "avg_price": 18,
    "avg_price_min": 12,
    "avg_price_max": 25,
    "tastes": ["清淡", "家常"],
    "scenes": ["一人食", "午餐", "低预算"],
    "tags": ["米线", "快餐", "适合学生"],
    "confidence": 0.82,
    "reason": "店名包含米线，价格估计适合学生日常一人食。"
}
```

## 手动验收

1. 查看缺失字段：

```powershell
python scripts/generate_shop_features.py --list-gaps --limit 20
```

2. dry-run：

```powershell
python scripts/generate_shop_features.py --limit 5 --dry-run
```

3. 正式生成候选：

```powershell
python scripts/generate_shop_features.py --limit 20
```

4. 查看 pending：

```powershell
python scripts/apply_feature_drafts.py --list-pending --limit 20
```

5. 确认高置信：

```powershell
python scripts/apply_feature_drafts.py --approve-confidence 0.75
```

6. 应用到正式表：

```powershell
python scripts/apply_feature_drafts.py --apply-approved
```

7. 查看结果：

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/chedian.db'); print(c.execute('select name, avg_price, tastes, scenes, tags from shops where avg_price is not null limit 10').fetchall())"
```

## 简历表达

完成本章后，可以写：

```text
设计 LLM 辅助的数据标注流程，基于 DeepSeek 对高德 POI 店铺生成候选推荐特征，包括人均价格、口味标签、场景标签和业务标签，并通过白名单校验、置信度评分和人工审核机制保证数据质量。
```

更完整一点：

```text
构建“高德 POI + DeepSeek 半自动标注 + 人工确认”的推荐数据建设流程，将原始地图 POI 转化为可用于规则召回、排序和推荐理由生成的结构化特征，提升推荐系统的数据覆盖率和可解释性。
```

## 本章知识点

- LLM 辅助数据标注
- 推荐特征工程
- 数据质量分
- 人工审核工作流
- JSON 输出约束
- 白名单过滤
- 置信度机制
- draft / approved 双阶段写入
- 外部数据与模型推断数据的边界

## 完成标准

本章完成后，应满足：

- 能扫描缺失推荐特征的店铺。
- 能让 DeepSeek 生成候选特征。
- 候选特征不会直接覆盖正式 `shops` 字段。
- 有 pending / approved / rejected 状态。
- 人工确认后才能写入正式字段。
- 非法标签会被过滤。
- 价格估计有合理范围。
- 推荐系统能优先使用高质量店铺。
- 新增测试通过。

