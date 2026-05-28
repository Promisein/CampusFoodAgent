# 第 5 章：AI 引擎

## 本章目标

接入 DeepSeek V4，实现 AI 驱动的推荐路径。完成两种 AI 模式：
1. **DeepSeek API 模式**：直接调用 DeepSeek API，由模型生成推荐回答
2. **DeepSeek Rerank 模式**：本地规则引擎初排 + DeepSeek V4 精排

## 前置知识

- HTTP 请求是什么（知道怎么用 httpx 发请求）
- LLM API 的调用格式（System Prompt + User Message + 返回 JSON）
- 环境变量的概念（敏感信息不放代码里）

## 文件清单

```
backend/
├── .env                      # 新增 DeepSeek API 密钥
├── .env.example              # 新增密钥模板
└── app/
    ├── models/
    │   └── schemas.py        # 新增 DeepSeek 相关模型
    ├── api/
    │   └── proxy_routes.py   # ★ 新版 /api 路由（AI 路径）
    └── services/
        ├── deepseek_service.py        # ★ DeepSeek API 客户端
        ├── deepseek_rerank_service.py # ★ DeepSeek V4 本地混合推荐方案
        ├── query_intent_service.py    # 查询意图提取
        └── user_profile.py            # 用户画像构建
```

> 本章文档只预留 `deepseek_service.py` 与 `deepseek_rerank_service.py` 的接口设计；真正代码实现按本章步骤创建。

---

## 架构总览

```
POST /api/recommend (proxy_routes.py)
         │
         ├─ RECOMMEND_PROVIDER=deepseek_api ──→ deepseek_service.py
         │    查询 + 用户画像 + 意图关键词 → DeepSeek API → 返回结果
         │
         ├─ RECOMMEND_PROVIDER=deepseek_rerank ──→ deepseek_rerank_service.py
         │    ① 规则引擎初排 Top 30
         │    ② 构造 Prompt 发给 DeepSeek V4
         │    ③ LLM 精排返回 JSON
         │    ④ 输出清洗（去幻觉）
         │
         └─ 其他 ──→ 规则引擎兜底
```

---

## Step 1：配置环境变量

在 `.env` 和 `.env.example` 中新增：

```env
# 推荐提供者选择：deepseek_api | deepseek_rerank
RECOMMEND_PROVIDER=deepseek_api

# DeepSeek V4 API
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4
DEEPSEEK_TIMEOUT_SECONDS=25
DEEPSEEK_MAX_RETRIES=1
DEEPSEEK_TEMPERATURE=0.3
DEEPSEEK_MAX_TOKENS=1800
```

---

## Step 2：DeepSeek API 客户端

创建 `backend/app/services/deepseek_service.py`：

```python
import os
import time
import httpx

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CHAT_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"


def _auth_header() -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def ask_deepseek(
    query: str,
    uid: str = "",
    history: list[dict] | None = None,
    parameters: dict | None = None,
    stream: bool = False,
) -> dict:
    """调用 DeepSeek API，返回标准化响应"""
    system_prompt = "你是成电校园餐饮推荐助手，请结合用户需求、用户画像和候选信息给出清晰推荐。"
    if parameters:
        profile = parameters.get("AGENT_USER_PROFILE_SUMMARY", "")
        keywords = parameters.get("AGENT_CATEGORY_KEYWORDS", "")
        system_prompt += f"\n用户画像：{profile}\n意图关键词：{keywords}"

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": query})

    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4"),
        "messages": messages,
        "temperature": float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "1800")),
        "stream": stream,
    }

    timeout = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "25"))
    max_retries = int(os.getenv("DEEPSEEK_MAX_RETRIES", "1"))

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(CHAT_URL, headers=_auth_header(), json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                finish_reason = data.get("choices", [{}])[0].get("finish_reason", "")
                return {
                    "ok": True,
                    "answer": content,
                    "raw": data,
                    "code": 0,
                    "finish_reason": finish_reason,
                }
        except httpx.HTTPError as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_error = str(e)
            break

    return {"ok": False, "answer": "", "raw": None, "error": last_error, "code": -1}
```

**关键设计点：**

1. **统一标准响应** — 对外始终返回 `ok / answer / error / code / finish_reason`，避免路由层绑定具体供应商格式
2. **用户画像注入** — 将 `AGENT_USER_PROFILE_SUMMARY` 与 `AGENT_CATEGORY_KEYWORDS` 合并到系统提示词中
3. **指数退避重试** — `time.sleep(2 ** attempt)`，第 1 次重试等 1s，第 2 次等 2s，第 3 次等 4s

---

## Step 3：DeepSeek Rerank 混合推荐（亮点模块）

创建 `backend/app/services/deepseek_rerank_service.py`。

这是面试最值得讲的模块。核心思路：

```
全部店铺 ──规则引擎初排──→ Top 30 ──构造Prompt──→ DeepSeek V4 ──返回JSON──→ 白名单过滤 ──→ 最终Top N
```

```python
import json
import os
import httpx

from app.services.parser import parse_query
from app.services.recommender import recommend as rule_recommend


def ask_deepseek_rerank(query: str, uid: str = "", **kwargs) -> dict:
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

    # Step 3：调 DeepSeek V4 API
    raw_output = _call_deepseek_api(system_prompt, user_prompt)

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


def _call_deepseek_api(system_prompt: str, user_prompt: str) -> str:
    """调 DeepSeek V4 API（非流式）"""
    endpoint = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4")
    temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3"))
    max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "1800"))

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
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
        "engine": "deepseek_rerank",
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
注入到 DeepSeek API 的系统提示词中，与用户输入、分类意图关键词一起发送给 DeepSeek V4。模型在生成推荐或重排序时会参考这段用户偏好摘要。

---

## Step 5：写 proxy_routes.py

创建 `backend/app/api/proxy_routes.py`，这是 `/api` 下的新路由：

```python
import os
from fastapi import APIRouter

from app.models.schemas import (
    DeepSeekRecommendRequest,
    DeepSeekRecommendResponse,
)
from app.services.parser import parse_query
from app.services.recommender import recommend as rule_recommend
from app.services.query_intent_service import build_query_with_intent_hint, extract_query_intents
from app.services.user_profile import build_iterative_profile
from app.services.deepseek_service import ask_deepseek
from app.services.deepseek_rerank_service import ask_deepseek_rerank

proxy_router = APIRouter()


@proxy_router.post("/recommend")
def post_recommend(req: DeepSeekRecommendRequest):
    provider = os.getenv("RECOMMEND_PROVIDER", "deepseek_api").strip().lower()

    # 构建用户画像（两种 AI 模式共用）
    profile = build_iterative_profile(uid=req.uid, user_id=req.userId)

    if provider == "deepseek_api":
        # ===== DeepSeek API 模式 =====
        enhanced_query = build_query_with_intent_hint(req.query)

        # 注入 AGENT_* 参数，保持后续 Prompt 与 Agent 编排扩展的一致性
        params = {
            "AGENT_USER_PROFILE_SUMMARY": profile.get("summary", ""),
            "AGENT_CATEGORY_KEYWORDS": ",".join(extract_query_intents(req.query)),
        }
        # 合并前端传来的参数
        if req.parameters:
            params.update(req.parameters)

        result = ask_deepseek(
            query=enhanced_query,
            uid=req.uid or req.anonymousId or "",
            history=req.history,
            parameters=params,
            stream=req.stream,
        )
        return DeepSeekRecommendResponse(
            ok=result["ok"],
            answer=result.get("answer", ""),
            finishReason=result.get("finish_reason", ""),
            error=result.get("error"),
            code=result.get("code", 0),
        )

    elif provider in ("deepseek_rerank", "rerank"):
        # ===== DeepSeek Rerank 模式 =====
        result = ask_deepseek_rerank(
            query=req.query,
            uid=req.uid or req.anonymousId or "",
            profile=profile,
            user_id=req.userId,
        )
        return DeepSeekRecommendResponse(
            ok=result["ok"],
            answer=result.get("answer", ""),
            recommendations=result.get("recommendations", []),
        )

    else:
        # ===== 规则引擎兜底 =====
        slots = parse_query(req.query)
        results = rule_recommend(slots, top_k=req.top_k or 3)
        return DeepSeekRecommendResponse(
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
class DeepSeekRecommendRequest(BaseModel):
    query: str = Field(..., min_length=1)
    uid: Optional[str] = None
    anonymousId: Optional[str] = None
    userId: Optional[str] = None
    chatId: Optional[str] = None
    top_k: Optional[int] = Field(default=3, ge=1, le=10)
    stream: bool = False
    history: Optional[list[dict]] = None
    parameters: Optional[dict] = None


class DeepSeekRecommendResponse(BaseModel):
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
app.include_router(proxy_router, prefix="/api", tags=["deepseek-proxy"])
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
RECOMMEND_PROVIDER=deepseek_api uvicorn app.main:app --port 8000
# 应该返回 DeepSeek V4 生成的推荐
```

DeepSeek V4 重排序模式：
```bash
RECOMMEND_PROVIDER=deepseek_rerank uvicorn app.main:app --port 8000
# 应该返回规则引擎初排 + DeepSeek V4 精排后的推荐
```

---

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| DeepSeek API 返回空结果 | Prompt 约束不清、模型输出为空或 API 响应格式变化 | 打印 raw 响应，确认 `choices[0].message.content` 是否存在 |
| DeepSeek API 鉴权失败 | API Key 不正确或环境变量未加载 | 检查 `DEEPSEEK_API_KEY`，确认 `Authorization: Bearer <key>` 格式 |
| DeepSeek V4 返回的 JSON 解析不了 | LLM 输出掺杂了 Markdown、中文标点 | `_sanitize` 里做更鲁棒的清理 |
| DeepSeek V4 编造不存在的店名 | LLM 幻觉 | 白名单过滤是整个流程的最后防线，**不能删** |

## 章末检查

- [ ] 三种模式（deepseek_api / deepseek_rerank / 规则兜底）都能正常返回
- [ ] 切换 `RECOMMEND_PROVIDER` 确实切换了引擎
- [ ] DeepSeek Rerank 模式的输出清洗能过滤幻觉店名
- [ ] 用户画像从历史数据中生成合理的摘要
