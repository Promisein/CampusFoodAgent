# 第 5 章：AI 引擎

## 本章目标

接入讯飞大模型，实现 AI 驱动的推荐路径。完成两种模式：
1. **Workflow 模式**：调讯飞星辰工作流 API
2. **Spark Local 模式**：本地规则引擎初排 + LLM 精排

## 前置知识

- HTTP 请求是什么（知道怎么用 httpx 发请求）
- LLM API 的调用格式（System Prompt + User Message + 返回 JSON）
- 环境变量的概念（敏感信息不放代码里）

## 文件清单

```
backend/
├── .env                      # 新增讯飞 API 密钥
├── .env.example              # 新增密钥模板
└── app/
    ├── models/
    │   └── schemas.py        # 新增 Workflow 相关模型
    ├── api/
    │   └── proxy_routes.py   # ★ 新版 /api 路由（AI 路径）
    └── services/
        ├── xfyun_workflow_service.py   # ★ 讯飞 Workflow 客户端
        ├── spark_local_recommend_service.py  # ★ Spark 本地混合方案
        ├── query_intent_service.py      # 查询意图提取
        └── user_profile.py              # 用户画像构建
```

---

## 架构总览

```
POST /api/recommend (proxy_routes.py)
         │
         ├─ RECOMMEND_PROVIDER=workflow ──→ xfyun_workflow_service.py
         │    查询 → AGENT_USER_INPUT → 讯飞 Workflow API → 返回结果
         │
         ├─ RECOMMEND_PROVIDER=spark_local ──→ spark_local_recommend_service.py
         │    ① 规则引擎初排 Top 30
         │    ② 构造 Prompt 发给 Spark X LLM
         │    ③ LLM 精排返回 JSON
         │    ④ 输出清洗（去幻觉）
         │
         └─ 其他 ──→ 规则引擎兜底
```

---

## Step 1：配置环境变量

在 `.env` 和 `.env.example` 中新增：

```env
# 推荐提供者选择：workflow | spark_local
RECOMMEND_PROVIDER=workflow

# 讯飞星辰 Workflow API
XFYUN_API_KEY=your_api_key_here
XFYUN_API_SECRET=your_api_secret_here
XFYUN_APP_ID=7b367536
XFYUN_FLOW_ID=7436739079683477504
XFYUN_BASE_URL=https://xingchen-api.xf-yun.com
XFYUN_TIMEOUT_SECONDS=25
XFYUN_MAX_RETRIES=1

# 讯飞 Spark 直接 API
XFYUN_SPARKX2_ENDPOINT=https://spark-api-open.xf-yun.com/x2/chat/completions
XFYUN_SPARKX_API_PASSWORD=your_spark_password_here
XFYUN_SPARKX_MODEL=spark-x
XFYUN_SPARKX_TEMPERATURE=0.3
XFYUN_SPARKX_MAX_TOKENS=1800
```

---

## Step 2：讯飞 Workflow 客户端

创建 `backend/app/services/xfyun_workflow_service.py`：

```python
import json
import os
import time
import httpx

XFYUN_BASE_URL = os.getenv("XFYUN_BASE_URL", "https://xingchen-api.xf-yun.com")
WORKFLOW_URL = f"{XFYUN_BASE_URL}/workflow/v1/chat/completions"
RESUME_URL = f"{XFYUN_BASE_URL}/workflow/v1/resume"


def _auth_header() -> dict:
    key = os.getenv("XFYUN_API_KEY", "")
    secret = os.getenv("XFYUN_API_SECRET", "")
    return {"Authorization": f"Bearer {key}:{secret}"}


def ask_workflow(
    query: str,
    uid: str = "",
    chat_id: str = "",
    history: list[dict] | None = None,
    parameters: dict | None = None,
    stream: bool = False,
) -> dict:
    """调用讯飞星辰 Workflow API，返回标准化响应"""
    merged_params = parameters or {}
    merged_params["AGENT_USER_INPUT"] = query

    payload = {
        "flow_id": os.getenv("XFYUN_FLOW_ID", ""),
        "uid": uid,
        "parameters": merged_params,
        "stream": stream,
    }
    if chat_id:
        payload["chat_id"] = chat_id
    if history:
        payload["history"] = history

    timeout = int(os.getenv("XFYUN_TIMEOUT_SECONDS", "25"))
    max_retries = int(os.getenv("XFYUN_MAX_RETRIES", "1"))

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(WORKFLOW_URL, headers=_auth_header(), json=payload)
                resp.raise_for_status()
                data = resp.json()

                # 提取响应内容
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    finish_reason = choices[0].get("finish_reason", "")
                else:
                    content = ""
                    finish_reason = ""

                return {
                    "ok": True,
                    "answer": content,
                    "raw": data,
                    "code": data.get("code", 0),
                    "chat_id": chat_id,
                    "finish_reason": finish_reason,
                }
        except httpx.HTTPError as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # 指数退避
        except Exception as e:
            last_error = str(e)
            break

    return {"ok": False, "answer": "", "raw": None, "error": last_error, "code": -1}


def resume_workflow(
    chat_id: str,
    event_id: str,
    event_type: str,
    content: str,
    uid: str = "",
) -> dict:
    """恢复被中断的 Workflow"""
    payload = {
        "flow_id": os.getenv("XFYUN_FLOW_ID", ""),
        "chat_id": chat_id,
        "uid": uid,
        "resume": {
            "event_id": event_id,
            "event_type": event_type,
            "content": content,
        },
    }

    timeout = int(os.getenv("XFYUN_TIMEOUT_SECONDS", "25"))
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(RESUME_URL, headers=_auth_header(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "answer": data.get("choices", [{}])[0].get("delta", {}).get("content", ""), "raw": data}
    except Exception as e:
        return {"ok": False, "answer": "", "raw": None, "error": str(e)}
```

**关键设计点：**

1. **`AGENT_USER_INPUT`** — 这是讯飞 Workflow 的固定参数名，用户输入必须通过这个字段传入（不是 `user_message` 也不是 `prompt`）
2. **指数退避重试** — `time.sleep(2 ** attempt)`，第 1 次重试等 1s，第 2 次等 2s，第 3 次等 4s
3. **中断/恢复** — Workflow 执行到 Q&A 节点时返回 `finish_reason: "interrupt"`，前端展示问题 → 用户回答 → 调 `resume_workflow` 继续

---

## Step 3：Spark Local 混合推荐（亮点模块）

创建 `backend/app/services/spark_local_recommend_service.py`。

这是面试最值得讲的模块。核心思路：

```
全部店铺 ──规则引擎初排──→ Top 30 ──构造Prompt──→ Spark X LLM ──返回JSON──→ 白名单过滤 ──→ 最终Top N
```

```python
import json
import os
import httpx

from app.services.parser import parse_query
from app.services.recommender import recommend as rule_recommend


def ask_spark_local_recommend(query: str, uid: str = "", **kwargs) -> dict:
    # Step 1：规则引擎初排 Top 30
    slots = parse_query(query)
    candidates = rule_recommend(slots, top_k=30)
    if not candidates:
        return {"ok": False, "answer": "暂无匹配的店铺推荐", "recommendations": []}

    # Step 2：构造 Prompt
    candidate_text = _build_candidate_text(candidates)
    system_prompt = """你是成电校园餐饮推荐助手。根据用户需求，从候选店铺列表中选出最合适的 3 家。
输出格式（严格 JSON）：
{"recommendations": [
  {"name": "店名", "reason": "推荐理由", "match_score": 0.0-1.0}
]}
只输出 JSON，不要任何其他文字。只从候选列表中选，不要编造店名。"""

    user_prompt = f"用户需求：{query}\n\n候选店铺列表：\n{candidate_text}"

    # Step 3：调 Spark API
    raw_output = _call_spark_api(system_prompt, user_prompt)

    # Step 4：输出清洗
    return _sanitize_or_fallback(raw_output, candidates)


def _build_candidate_text(candidates: list[dict]) -> str:
    """将候选店铺列表格式化为 LLM 可读的文本"""
    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"{i+1}. {c['name']} | {c['campus']} | "
            f"人均¥{c['avg_price']} | 标签:{c.get('tags','')} | "
            f"评分:{c['score']}"
        )
    return "\n".join(lines)


def _call_spark_api(system_prompt: str, user_prompt: str) -> str:
    """调 Spark X API（非流式）"""
    endpoint = os.getenv("XFYUN_SPARKX2_ENDPOINT", "")
    password = os.getenv("XFYUN_SPARKX_API_PASSWORD", "")
    model = os.getenv("XFYUN_SPARKX_MODEL", "spark-x")
    temperature = float(os.getenv("XFYUN_SPARKX_TEMPERATURE", "0.3"))
    max_tokens = int(os.getenv("XFYUN_SPARKX_MAX_TOKENS", "1800"))

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {password}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _sanitize_or_fallback(raw_output: str, candidates: list[dict]) -> dict:
    """
    输出清洗：防止 LLM 编造候选列表里不存在的店名。
    如果清洗后不足 1 条，回退到规则引擎结果。
    """
    # 提取候选店名的白名单
    valid_names = {c["name"] for c in candidates}

    # 尝试解析 LLM 返回的 JSON
    try:
        # LLM 可能返回 ```json ... ``` 包裹的文本
        text = raw_output.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]  # 去第一行 ```json
            if text.endswith("```"):
                text = text[:-3]
        parsed = json.loads(text)
        items = parsed.get("recommendations", [])
    except (json.JSONDecodeError, AttributeError):
        # JSON 解析失败 → 回退规则引擎
        return _fallback_to_rules(candidates)

    # 白名单过滤：只保留在候选中的店名
    clean = [item for item in items if item.get("name", "") in valid_names]

    if len(clean) < 1:
        return _fallback_to_rules(candidates)

    return {
        "ok": True,
        "answer": raw_output,
        "recommendations": clean[:3],
        "engine": "spark_local",
    }


def _fallback_to_rules(candidates: list[dict]) -> dict:
    """LLM 输出不可用时回退规则引擎"""
    return {
        "ok": True,
        "answer": "(规则引擎结果)",
        "recommendations": candidates[:3],
        "engine": "rule-based-fallback",
    }
```

**为什么要做输出清洗？**
LLM 会"幻觉"——比如候选里只有"学子餐厅"，但 LLM 可能回复"银杏餐厅"（它从训练数据中编的）。白名单过滤就是：**只有我们数据库里真实存在的店名才能出现在推荐结果里**。

---

## Step 4：查询意图提取 + 用户画像

创建 `backend/app/services/query_intent_service.py`：

```python
"""从用户查询中提取分类意图关键词"""

_CATEGORY_KEYWORDS = {
    "面食": ["面", "拉面", "刀削面", "拌面", "凉面", "米线", "抄手", "饺子"],
    "米饭": ["盖饭", "炒饭", "拌饭", "套餐", "盖浇", "米饭"],
    "火锅": ["火锅", "串串", "冒菜", "麻辣烫", "串串香"],
    "川菜": ["川菜", "炒菜", "回锅肉", "宫保", "水煮", "麻婆"],
    "小吃": ["小吃", "烧烤", "炸鸡", "奶茶", "奶茶店", "冰粉", "凉皮"],
    "汤品": ["汤", "炖", "粥", "砂锅", "炖盅", "汤锅"],
    "快餐": ["快餐", "盒饭", "便当", "食堂"],
}


def extract_query_intents(query: str) -> list[str]:
    """提取查询中的分类意图"""
    found = []
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                found.append(category)
                break
    return found


def build_query_with_intent_hint(query: str) -> str:
    """构建带意图增强的查询文本"""
    intents = extract_query_intents(query)
    if not intents:
        return query
    return f"{query}（想吃：{'、'.join(intents)}）"
```

创建 `backend/app/services/user_profile.py`：

```python
"""
用户画像构建：从历史行为数据中"算"出用户偏好，不靠用户手动填写。
"""

from app.services.usage_events import list_recent_events
from app.services.feedback_repository import get_feedback_by_user


def build_iterative_profile(uid: str | None = None, user_id: str | None = None) -> dict:
    """
    分析用户最近 30 天行为 + 90 天反馈，构建画像。
    返回格式：
    {
        "hasProfile": bool,
        "summary": "人类可读的偏好摘要",
        "signals": {"preferred_tastes": [...], "frequent_campus": "...", ...},
        "stats": {"total_queries": 0, "total_feedbacks": 0, "avg_rating": 0}
    }
    """
    # 获取最近事件
    events = list_recent_events(uid=uid, user_id=user_id, days=30, limit=80)
    feedbacks = get_feedback_by_user(uid=uid, user_id=user_id, days=90, limit=80)

    total_queries = sum(1 for e in events if e.get("event_type") == "query")
    total_feedbacks = len(feedbacks)
    avg_rating = (
        sum(f.get("rating", 0) for f in feedbacks) / len(feedbacks)
        if feedbacks else 0
    )

    # 汇总口味偏好
    taste_counter: dict[str, float] = {}
    for f in feedbacks:
        if f.get("taste_tags"):
            try:
                tags = json.loads(f["taste_tags"]) if isinstance(f["taste_tags"], str) else f["taste_tags"]
            except Exception:
                tags = []
            weight = 1.5 if f.get("rating", 0) >= 4 else (0.5 if f.get("rating", 0) <= 2 else 1.0)
            for tag in tags:
                taste_counter[tag] = taste_counter.get(tag, 0) + weight

    preferred = sorted(taste_counter.items(), key=lambda x: -x[1])[:5]

    has_profile = total_queries >= 3 or total_feedbacks >= 2

    return {
        "hasProfile": has_profile,
        "summary": _build_summary(preferred, total_queries, total_feedbacks),
        "signals": {
            "preferred_tastes": [p[0] for p in preferred],
            "total_queries": total_queries,
            "total_feedbacks": total_feedbacks,
        },
        "stats": {
            "total_queries": total_queries,
            "total_feedbacks": total_feedbacks,
            "avg_rating": round(avg_rating, 2),
        },
    }


def _build_summary(preferred: list, total_queries: int, total_feedbacks: int) -> str:
    """生成人类可读的偏好摘要"""
    if not preferred:
        return f"新用户（{total_queries}次查询，{total_feedbacks}次反馈）"
    taste_names = [p[0] for p in preferred[:3]]
    return f"偏好口味：{'、'.join(taste_names)}。{total_queries}次查询，{total_feedbacks}次反馈"
```

**用户画像怎么被用到的？**
注入到 `parameters.AGENT_USER_PROFILE_SUMMARY` 字段，随 Workflow 请求一起发给讯飞。Workflow 内部的 LLM 在生成推荐时会参考这段用户偏好摘要。

---

## Step 5：写 proxy_routes.py

创建 `backend/app/api/proxy_routes.py`，这是 `/api` 下的新路由：

```python
import os
from fastapi import APIRouter

from app.models.schemas import (
    WorkflowRecommendRequest,
    WorkflowRecommendResponse,
)
from app.services.parser import parse_query
from app.services.recommender import recommend as rule_recommend
from app.services.query_intent_service import build_query_with_intent_hint, extract_query_intents
from app.services.user_profile import build_iterative_profile
from app.services.xfyun_workflow_service import ask_workflow
from app.services.spark_local_recommend_service import ask_spark_local_recommend

proxy_router = APIRouter()


@proxy_router.post("/recommend")
def post_recommend(req: WorkflowRecommendRequest):
    provider = os.getenv("RECOMMEND_PROVIDER", "workflow").strip().lower()

    # 构建用户画像（两种模式共用）
    profile = build_iterative_profile(uid=req.uid, user_id=req.userId)

    if provider == "workflow":
        # ===== AI Workflow 模式 =====
        enhanced_query = build_query_with_intent_hint(req.query)

        # 注入 AGENT_* 参数
        params = {
            "AGENT_USER_PROFILE_SUMMARY": profile.get("summary", ""),
            "AGENT_CATEGORY_KEYWORDS": ",".join(extract_query_intents(req.query)),
        }
        # 合并前端传来的参数
        if req.parameters:
            params.update(req.parameters)

        result = ask_workflow(
            query=enhanced_query,
            uid=req.uid or req.anonymousId or "",
            chat_id=req.chatId or "",
            history=req.history,
            parameters=params,
        )
        return WorkflowRecommendResponse(
            ok=result["ok"],
            answer=result.get("answer", ""),
            finishReason=result.get("finish_reason", ""),
            error=result.get("error"),
            code=result.get("code", 0),
        )

    elif provider in ("spark_local", "spark"):
        # ===== Spark Local 模式 =====
        result = ask_spark_local_recommend(
            query=req.query,
            uid=req.uid or req.anonymousId or "",
            profile=profile,
            user_id=req.userId,
        )
        return WorkflowRecommendResponse(
            ok=result["ok"],
            answer=result.get("answer", ""),
            recommendations=result.get("recommendations", []),
        )

    else:
        # ===== 规则引擎兜底 =====
        slots = parse_query(req.query)
        results = rule_recommend(slots, top_k=req.top_k or 3)
        return WorkflowRecommendResponse(
            ok=True,
            answer="",
            recommendations=[
                {
                    "name": r["name"],
                    "reason": r["reason"],
                    "match_score": r["score"],
                }
                for r in results
            ],
        )
```

在 `backend/app/models/schemas.py` 中新增相关模型：

```python
class WorkflowRecommendRequest(BaseModel):
    query: str = Field(..., min_length=1)
    uid: Optional[str] = None
    anonymousId: Optional[str] = None
    userId: Optional[str] = None
    chatId: Optional[str] = None
    top_k: Optional[int] = Field(default=3, ge=1, le=10)
    stream: bool = False
    history: Optional[list[dict]] = None
    parameters: Optional[dict] = None


class WorkflowRecommendResponse(BaseModel):
    ok: bool
    answer: str = ""
    error: Optional[str] = None
    code: int = 0
    finishReason: str = ""
    recommendations: list[dict] = []
```

在 `main.py` 中挂载 proxy_router：
```python
from app.api.proxy_routes import proxy_router
app.include_router(proxy_router, prefix="/api", tags=["workflow-proxy"])
```

---

## Step 6：验证

```bash
cd backend
# 先验证规则引擎兜底（不设 API key）
RECOMMEND_PROVIDER="" uvicorn app.main:app --port 8000
# 用 Swagger 调 POST /api/recommend
```

如果配置了真的 API key：
```bash
RECOMMEND_PROVIDER=workflow uvicorn app.main:app --port 8000
# 应该返回 LLM 生成的推荐
```

---

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| Workflow 返回空结果 | 已发布版本与编辑器草稿不同步 | 去讯飞控制台检查是否发布了最新版本 |
| Workflow 返回 20900 错误 | API Key/Secret 不正确 | 检查环境变量，确认 `Bearer {KEY}:{SECRET}` 格式 |
| Spark 返回的 JSON 解析不了 | LLM 输出掺杂了 Markdown、中文标点 | `_sanitize` 里做更鲁棒的清理 |
| Spark 编造不存在的店名 | LLM 幻觉 | 白名单过滤是整个流程的最后防线，**不能删** |

## 章末检查

- [ ] 三种模式（workflow / spark_local / 规则兜底）都能正常返回
- [ ] 切换 `RECOMMEND_PROVIDER` 确实切换了引擎
- [ ] Spark 模式的输出清洗能过滤幻觉店名
- [ ] 用户画像从历史数据中生成合理的摘要
