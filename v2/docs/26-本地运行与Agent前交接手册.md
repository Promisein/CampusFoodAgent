# 本地运行与Agent前交接手册

本手册对应2026年10月20日的本地离线推荐演示。质量结果见[25最终验收](25-Agent编排前最终质量验收.md)，数据与历史排序结论沿用20–23文档。

## 启动

在`C:\Users\Jianing\Desktop\CampusFoodAgent\v2\backend`执行：

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

打开`http://127.0.0.1:8100/demo`。使用Tampa默认坐标，先输入咖啡、户外早餐或约会意大利菜，再测试“50元以内”“现在营业”等应澄清的条件。数据来自历史快照，不代表当前门店事实。

密钥仅放`backend/.env`的`DEEPSEEK_API_KEY`。`/api/v2/rag/status`检查配置，不做付费探测。演示页勾选生成说明会按配置调用DeepSeek；关闭说明可只看推荐和证据。API的`generate_answer`默认false。

需要重建环境时使用Python3.11创建项目内.venv，再安装requirements.lock.txt；本机正常环境已就绪，不需要为了运行重复安装。processed、serving_v1、search_v1、ranking_v1等本地产物不在Git中，换机器需按既有文档准备数据并重建。

## 验证与回放

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q
.\.venv\Scripts\python.exe -B -m pip check

# 无付费调用；另存快照以免影响已标注的最终快照
.\.venv\Scripts\python.exe -B -m app.evaluation.query_quality --output-dir data/derived/query_quality_replay

# 已有最终快照的代理银标评分，标签不是人工金标
.\.venv\Scripts\python.exe -B -m app.evaluation.query_quality --output-dir data/derived/query_quality_final --labels data/derived/pre_agent_v1/final_agent_silver.csv

# 同一批生成场景离线回放，不读.env，不调用服务商
.\.venv\Scripts\python.exe -B -m app.evaluation.pre_agent --silver-labels data/derived/pre_agent_v1/final_agent_silver.csv
```

只有需要额外真实验收时才显式使用下列命令，每次最多5条，会使用API额度；本阶段已完成一轮，不需要再运行才能使用演示页：

```powershell
.\.venv\Scripts\python.exe -B -m app.evaluation.pre_agent --live --output-dir data/derived/pre_agent_comparison_live_repeat --silver-labels data/derived/pre_agent_v1/final_agent_silver.csv
```

可用`--query-ids q11 q13`缩小到指定场景。真实输出含非确定性与耗时，不应声称逐字可复现。重新生成最终快照会改变标注绑定，评测开发应输出新目录，保留基线、原始表及清单。

## 常见情况

| 现象 | 解释与处理 |
| --- | --- |
| configured=true但仍模板 | 看answer.reason；配置存在不代表本次成功。401/403检查密钥权限，429检查额度/限流，timeout按模板继续；不要反复自动重试 |
| live_probe=not_performed_by_status | 状态接口没有额外调用服务商，属于正常行为 |
| 找不到/加载不了模型 | 在system/status看history/search/ranker是否available；缺失或校验失败时走既有降级，按对应构建文档修复产物 |
| 证据不足 | 当前代表评论未检索到相关句子；不能推断餐厅满足或不满足软偏好 |
| mention_only/negative_cue | 相关性或规则线索，不是语义保证；应核对原文与代理/人工复核依据 |
| 超过5条推荐但只解释前5家 | 默认上下文覆盖上限，后续卡片明确标注未覆盖；不是餐厅丢失 |
| 表格导入失败 | 不改只读字段、不混用快照、不重复记录；仅填合法标签、reviewer、note，保留UTF-8 |
| 反馈/收藏失效 | 查看events状态与SQLite可写性；仅本地演示身份，无登录认证，反馈不会自动训练模型 |
| 8100端口占用 | 核对正在运行的项目服务进程后停止旧服务再启动，不要结束未确认用途的Python进程 |

## Agent下一阶段可接入的现有能力

现有Python/API能力已经能够完成搜索推荐、读取历史画像、取同商户证据、生成说明、记录收藏/评分和查看历史。它们还不是一套LLM自主工具调用循环。

进入Agent阶段应沿用这些边界：位置/城市/半径/价格/类别由代码过滤；无法验证的条件先澄清；生成只解释返回白名单内商户；收藏等写操作绑定当前曝光和演示身份；缺模型、证据或服务商响应时明确降级。保持现有API行为与回归用例，另加多轮状态、工具参数校验、最大步数、超时/费用预算及端到端工具轨迹。

Agent完成前不应宣称已有长期记忆、自主规划、多轮偏好更新、生产认证或线上反馈学习。独立人工评测和生产化可以在后续单独推进，不用伪造这些指标来满足阶段进度。
