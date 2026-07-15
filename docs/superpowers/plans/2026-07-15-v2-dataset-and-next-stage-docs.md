# CampusFoodAgent v2 数据集与下一阶段文档实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `v2/docs/` 下创建准确的数据集说明和仅覆盖 Tampa processed 数据接入 API 的分段实施计划。

**Architecture:** 两份文档按“事实”和“行动”分离。数据集文档从 manifest、JSONL schema 和整理脚本提取事实；下一阶段文档采用四个顺序验收门，每段完成后停止，不把后续推荐、RAG 或 Agent 能力提前纳入。

**Tech Stack:** Markdown、Yelp JSONL、FastAPI、Pydantic、pytest、PowerShell、Conda Python 3.11.15。

## Global Constraints

- 主体使用中文，字段、路径、接口和技术名保留英文。
- 两份文档都标注 `2026年7月15日`。
- 数据规模固定引用 manifest：3,805 家商户、100,000 条交互、29,092 条代表评论。
- 数据规模结论为“足够支撑研一阶段的学习、复现和项目实现”，不引入生产级规模要求。
- 下一阶段只覆盖 Tampa processed 数据接入 API。
- 每个实施分段必须有独立验收条件和停止点。
- 命令显式使用 `D:\anaconda3\envs\chedian-eat-agent\python.exe` 并设置 `PYTHONNOUSERSITE=1`。
- 不修改 v2 业务代码、测试或数据文件。

---

### Task 1: 创建数据集说明

**Files:**
- Create: `v2/docs/01-数据集说明.md`
- Read: `v2/backend/data/processed/data_manifest.json`
- Read: `v2/backend/data/processed/businesses.jsonl`
- Read: `v2/backend/data/processed/interactions.jsonl`
- Read: `v2/backend/data/processed/representative_reviews.jsonl`
- Read: `v2/backend/app/data_pipeline/curate_yelp.py`

**Interfaces:**
- Consumes: manifest 中的规模、限制、保留/排除来源和输出路径；三类 JSONL 的实际字段。
- Produces: 数据来源、处理过程、字段字典、文件关系、用途和适用性说明。

- [x] **Step 1: 创建 `v2/docs/` 和数据集文档**

文档章节顺序固定为：文档日期、数据集定位、处理流程、实际规模、文件结构、Business 特征、Interaction 特征、RepresentativeReview 特征、manifest 作用、数据关系、各类特征用途、适合完成的实验、5060 8GB 适用性、使用边界和事实来源。

- [x] **Step 2: 写入准确的数据规模和处理上限**

必须包含：Tampa, FL；3,805 家商户；2,596 家营业商户；1,209 家关闭商户；100,000 条交互；29,092 条代表评论；每商户最多 40 条交互；每商户最多 8 条代表评论；Business/Review 保留，User/Check-in/Tip 本阶段排除。

- [x] **Step 3: 写入三个实体的字段字典与用途**

字段必须与实际 JSONL 一致。Business 说明结构化过滤、地理、热度和内容特征；Interaction 说明画像、ItemCF、标签与时间切分；RepresentativeReview 说明关键词/向量检索、证据和推荐解释。

### Task 2: 创建下一阶段实施计划

**Files:**
- Create: `v2/docs/02-下一阶段实施计划.md`
- Read: `v2/backend/app/main.py`
- Read: `v2/backend/app/models.py`
- Read: `v2/backend/app/recommender.py`
- Read: `v2/backend/tests/`

**Interfaces:**
- Consumes: 当前三个 API、fixture 推荐逻辑、processed 文件和现有 9 项测试。
- Produces: 只覆盖真实 Tampa 数据接入的四段执行文档。

- [x] **Step 1: 写入阶段目标、范围和非目标**

目标固定为让数据状态与推荐接口逐步读取 processed 数据。非目标固定为用户画像、多路召回、RRF、LightGBM、完整 RAG、Agent、前端和部署。

- [x] **Step 2: 写入四个顺序验收门**

四段依次为：真实数据读取层；数据状态接口；真实推荐接口；集成收尾。每段写明目标、修改文件、输入输出、不做内容、测试命令、验收条件和停止点。

- [x] **Step 3: 写入执行纪律与环境命令**

明确上一段测试未通过不得进入下一段；所有命令使用目标 Conda Python；每段只提交本段文件；不在本计划中提前实现后续阶段。

### Task 3: 验证文档

**Files:**
- Verify: `v2/docs/01-数据集说明.md`
- Verify: `v2/docs/02-下一阶段实施计划.md`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的文档。
- Produces: 数字、字段、范围、格式和任务文件边界的验证结果。

- [x] **Step 1: 检查日期、数字、字段和阶段关键词**

Run:

```powershell
rg -n '2026年7月15日|3,805|100,000|29,092|business_id|interaction_id|review_id|第一段|第二段|第三段|第四段|停止点' v2/docs
```

Expected: 两份文档日期存在；数据数字和三个实体主键存在；四段及停止点全部存在。

- [x] **Step 2: 检查下一阶段范围**

Run:

```powershell
rg -n '非目标|用户画像|多路召回|LightGBM|完整 RAG|Agent' v2/docs/02-下一阶段实施计划.md
```

Expected: 后续能力只出现在非目标说明，不出现在四段实施任务中。

- [x] **Step 3: 检查 Markdown 和改动范围**

Run:

```powershell
git diff --check -- v2/docs
git status --short -- v2/docs
```

Expected: 无空白错误；`v2/docs/` 只包含两份目标文档。

- [x] **Step 4: 复核业务文件没有被修改**

Run:

```powershell
git status --short -- v2/backend
```

Expected: 本任务没有新增或修改 `v2/backend` 下的代码、测试和数据文件。
