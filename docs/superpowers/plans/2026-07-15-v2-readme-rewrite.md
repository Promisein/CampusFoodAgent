# CampusFoodAgent v2 README 中文重写实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `v2/README.md` 重写为可运行、可追溯、明确区分现状与规划的中文项目入口。

**Architecture:** README 采用“先运行、后架构与路线”的信息结构。当前代码能够证明的能力单独列为“已实现”，方案中的目标能力单独列为“规划中”，并把八份重构材料的核心内容归纳到双项目定位、CampusFoodAgent 架构、三层评估和开发路线中。

**Tech Stack:** Markdown、PowerShell、FastAPI、Pydantic、pytest、Yelp Open Dataset。

## Global Constraints

- README 主体使用中文，命令、接口、类型名与必要技术名保留英文。
- 页首必须写明“最后更新：2026年7月15日”，方案来源必须写明“2026年6月18日”。
- 只把代码和测试能够证明的功能写成已实现；未完成能力必须明确标记为规划中。
- 不填写尚未运行的实验数字，不声称线上 CTR、A/B 测试、真实 GPS 或实时个性化。
- 仅修改 `v2/README.md` 及本实施计划，不覆盖工作区既有变更。

---

### Task 1: 重写中文 README

**Files:**
- Modify: `v2/README.md`

**Interfaces:**
- Consumes: `v2/backend/app/main.py` 中的三个 `/api/v2` 接口、`RecommendationRequest` 字段、数据整理命令、测试命令和八份重构材料。
- Produces: 中文项目入口，供开发运行、项目维护和面试说明使用。

- [x] **Step 1: 用“先运行、后方案”结构替换英文 README**

README 必须依次覆盖：标题与日期、项目定位、当前完成度、快速开始、API、当前推荐链路、数据策略、目标架构、模块边界、评估计划、路线图、双项目关系、可信度与面试表述、方案来源。

- [x] **Step 2: 写明当前实现与目标架构的边界**

已实现范围固定为：fixture 推荐、硬过滤、关键词与结构化评分、代表评论证据、FastAPI 接口、Yelp 单城市整理、manifest 和现有测试。目标范围固定为：画像快照、多路召回、RRF、LightGBM、混合 RAG、受控工具、反馈事件与降级。

- [x] **Step 3: 保留可直接使用的 PowerShell 命令**

命令包括依赖安装、Uvicorn 启动、pytest、Yelp 数据整理和 `Invoke-RestMethod` 示例；路径从仓库根目录开始，避免依赖用户机器上的绝对项目路径。

### Task 2: 静态与运行验证

**Files:**
- Verify: `v2/README.md`
- Test: `v2/backend/tests/`

**Interfaces:**
- Consumes: Task 1 生成的 README。
- Produces: 日期、中文、内容覆盖、链接、格式和现有测试的验证结果。

- [x] **Step 1: 检查日期、状态标签与方案覆盖**

Run:

```powershell
rg -n '2026年7月15日|2026年6月18日|已实现|规划中|recsys_pipeline|推荐层|RAG 层|Agent 层|双项目重构方案' v2/README.md
```

Expected: 所有关键词均至少出现一次，且已实现/规划中存在独立说明。

- [x] **Step 2: 检查 Markdown 与本地链接**

Run:

```powershell
git diff --check -- v2/README.md
rg -n '^#{1,6} ' v2/README.md
rg -n '\[[^]]+\]\(([^)]+)\)' v2/README.md
```

Expected: `git diff --check` 无输出；标题层级清晰；仓库内相对链接目标存在，外部方案路径明确标为本机来源路径。

- [x] **Step 3: 运行 v2 后端测试**

Run:

```powershell
Set-Location v2/backend
python -m pytest tests/ -v
```

Expected: 9 个现有测试全部通过。

- [x] **Step 4: 复核任务范围**

Run:

```powershell
git status --short
git diff -- v2/README.md
```

Expected: README 差异只涉及本次中文重写；工作区其他既有移动、删除和未跟踪文件保持不变。
