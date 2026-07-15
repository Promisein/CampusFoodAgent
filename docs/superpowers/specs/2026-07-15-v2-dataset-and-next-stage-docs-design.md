# CampusFoodAgent v2 数据集与下一阶段文档设计

> 设计日期：2026年7月15日

## 目标

在 `v2/docs/` 下创建两份相互独立的中文文档：一份说明当前已经处理完成的数据集，另一份只规划最近一个开发阶段。文档服务于研一阶段的学习、复现和分段实现，不使用生产级或大规模系统标准扩大范围。

## 文件边界

### `v2/docs/01-数据集说明.md`

只记录当前数据事实，不写开发任务。内容包括：

1. Yelp Open Dataset 来源与 Tampa 单城市子集定位；
2. Business 和 Review 的处理过程及保留/排除来源；
3. 3,805 家商户、100,000 条交互、29,092 条代表评论等实际规模；
4. `Business`、`Interaction`、`RepresentativeReview` 和 manifest 的字段、含义及用途；
5. 五个 processed 文件之间的数据关系；
6. 数据可以支撑的地理过滤、画像、ItemCF、排序、RAG 和离线评估用途；
7. 对 RTX 5060 8GB 学习环境的适用性；
8. 处理上限、用户稀疏、字段缺失等需要在实验报告中说明的边界。

数据规模结论固定为：当前规模足够完成学习、复现和面试项目，不要求扩展到全量数据。

### `v2/docs/02-下一阶段实施计划.md`

只覆盖“把 Tampa processed 数据接入 v2 在线 API”。不规划用户画像、多路召回、LightGBM、完整 RAG、Agent、前端或部署。

采用四段验收门：

1. **真实数据读取层**：读取并校验 processed 商户、代表评论和 manifest；保留 fixture，不改变推荐 API。
2. **数据状态接入**：让 `/api/v2/dataset/status` 反映 processed 数据集及真实数量；推荐接口仍不切换。
3. **真实推荐接入**：将 Tampa 商户、距离/城市/价格/营业硬过滤和代表评论证据接入 `/api/v2/recommend`。
4. **集成收尾**：增加端到端测试、空结果和缺失字段行为，更新 README 当前状态。

每一段必须包含目标、修改文件、输入输出、明确不做、测试命令、验收条件和完成后停止点。上一段未验收时不得进入下一段。

## 内容依据

文档数字和字段以以下文件为事实来源：

- `v2/backend/data/processed/data_manifest.json`
- `v2/backend/data/processed/businesses.jsonl`
- `v2/backend/data/processed/interactions.jsonl`
- `v2/backend/data/processed/representative_reviews.jsonl`
- `v2/backend/app/data_pipeline/curate_yelp.py`
- `v2/backend/data/README.md`

## 写作规则

- 主体使用中文，字段名、路径、命令和技术名保留英文；
- 两份文档都标注 `2026年7月15日`；
- 已处理数据与未来功能明确分开；
- 不把 processed 数据写成全量 Yelp；
- 不因数据年代或规模引入与学习复现目标无关的生产要求；
- 不填写尚未运行的模型指标；
- 命令显式使用 `D:\anaconda3\envs\chedian-eat-agent\python.exe` 并设置 `PYTHONNOUSERSITE=1`。

## 验收标准

1. `v2/docs/` 下只新增两份目标文档；
2. 数据文档中的规模与 manifest 一致；
3. 字段与 JSONL 实际 schema 一致；
4. 下一阶段文档只包含真实数据接入，并明确四个停止点；
5. 文档不包含未完成或无法执行的占位描述；
6. Markdown 标题、表格、代码块和相对路径通过静态检查；
7. 不修改 v2 业务代码、数据文件或测试。
