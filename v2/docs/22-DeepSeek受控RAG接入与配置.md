# DeepSeek受控RAG接入与配置

2026年10月20日，API0.5.0、rag_v1。已实现“评论句子检索 → 白名单上下文 → DeepSeek结构化引用计划 → 严格校验 → 中文受控渲染 → 故障模板降级”。当前没有真实API密钥，因此尚未完成真实DeepSeek联网验收；离线结果见[23验收报告](23-RAG离线验收与边界报告.md)。

## 密钥填写位置

本机已准备`C:\Users\Jianing\Desktop\CampusFoodAgent\v2\backend\.env`。只需把下面这一行等号后面填上DeepSeek控制台创建的密钥：

```dotenv
DEEPSEEK_API_KEY=在这里填实际密钥
```

其余默认配置已经设置：

```dotenv
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
RAG_ENABLED=true
RAG_TIMEOUT_SECONDS=12
RAG_MAX_TOKENS=1800
RAG_MAX_CONTEXT_CHARS=24000
RAG_MAX_RESTAURANTS=5
```

不用把密钥写进Python、页面、请求JSON或聊天记录。`.env`已被Git忽略，仓库只保存空值示例`.env.example`。不要把实际密钥填进示例文件。操作系统同名环境变量优先于.env；即使环境变量值为空，也会覆盖文件。

按2026-10-20核对的[DeepSeek官方接入说明](https://api-docs.deepseek.com/)，当前模型名为deepseek-flash，官方HTTP接口为`https://api.deepseek.com/chat/completions`。模型名可在.env更新。使用现有httpx调用，无新增SDK依赖。

在v2/backend运行：

```powershell
# 只检查配置状态，不发送网络请求
.\.venv\Scripts\python.exe -B -m app.rag.check

# 填密钥后执行一次真实合成场景调用，会使用API额度
.\.venv\Scripts\python.exe -B -m app.rag.check --live

# 启动服务；旧进程运行时先结束旧服务再启动
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

检查命令输出configured=true只表示存在配置，不表示密钥、余额或模型权限已验证。真实检查应得到mode=deepseek_plan、status=generated。401/403、429、超时或格式错误会输出简短原因，不回显服务商响应正文、密钥或请求头。真实检查只使用合成商户，不发送用户画像。

打开http://127.0.0.1:8100/demo，勾选“生成带引用的说明”。无密钥时会显示本地模板；密钥有效且引用计划通过校验时显示DeepSeek模式。配置每次生成时读取，填写后下一次请求即可生效；重启服务也可以。

## 接口

POST `/api/v2/recommend`新增可选布尔字段`generate_answer`，默认false，原推荐结果与排序不改变。示例：

```json
{
  "query": "咖啡，安静",
  "latitude": 27.9506,
  "longitude": -82.4572,
  "radius_km": 5,
  "max_price_level": 2,
  "top_k": 5,
  "generate_answer": true
}
```

响应新增answer，包含mode、status、reason、text、items、citations、覆盖数量、provider_attempted、model和usage。false时answer=null。`/api/v2/rag/status`及system/status返回启用/配置状态与模型名，不返回密钥，也不会发起试探调用。

## 实现方法

1. 推荐系统先完成合法候选、排序和Top K。RAG不参与新增商户、放宽约束或改排序。
2. 在每家返回商户的代表评论内分句，用BM25及已支持的中英文主题词检索，最多取2个不同评论来源，摘录最长500字符。引用始终保留business_id、review_id和原文子串。
3. 生成有界上下文：查询最多1000字符，默认前5家商户及24,000字符总预算；事实包括名称、数据坐标距离、价格等级、快照评分和类别。未覆盖餐厅数量会明确说明。专用user_id、精确请求经纬度、历史画像及API Key不进入提示；用户主动写入查询的信息和距离等派生事实仍会随上下文发送。
4. DeepSeek只返回JSON里的business_id、fact_ids、citation_ids。按官方[JSON Output说明](https://api-docs.deepseek.com/guides/json_mode/)设置response_format=json_object并提供JSON示例，关闭thinking，限制输出与超时，不自动重试。
5. Pydantic拒绝多余字段；程序验证餐厅集合与顺序、事实ID、引用ID、商户归属、去重及有相关评论时必须引用。自由解释句、伪造事实和外部引用不会进入回答。
6. 由程序把已选事实转成固定中文句子、附上评论原文及引用编号。密钥缺失、禁用、网络异常、401/429、截断、空响应或非法计划使用同一上下文的本地模板。

代码位于app/rag/settings.py、context.py、generation.py。演示页对回答和引用使用textContent渲染；凭证不进入页面、事件库或源码。自动化测试强制空环境密钥，并用MockTransport模拟网络，避免开发者以后填入密钥后意外付费。

## 能力边界

这是“模型选择/组织事实与引用＋程序受控渲染”的RAG，不是自由语言改写。这样可以机械校验输出来源，代价是语言表达较固定。没有宣称通过字符串或引用ID就能证明自然语言语义蕴含。

negative_cue、mixed_cues、mention_only只是规则线索，不是训练过的NLI或情感模型。not quiet可以被召回，但会保留否定提示；相关评论不能保证餐厅安静、适合约会或满足饮食安全。评论可能矛盾、过时或含注入指令，始终作为不可信引用数据处理。

新生成使用当前代表评论快照；没有改变历史排序特征或重跑历史test调参。营业标记不代表现实现在营业，价格等级不代表实际人均金额。真实DeepSeek的响应、额度、模型权限、延迟和质量必须在填入密钥后另做联网验收。
