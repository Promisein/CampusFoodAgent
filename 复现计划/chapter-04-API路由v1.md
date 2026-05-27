# 第 4 章：API 路由 v1

## 本章目标

把第 3 章的规则引擎暴露为 REST API，创建完整的 MVP 端点集合。

## 前置知识

- REST API 基础（GET/POST/DELETE 的语义）
- FastAPI 的 APIRouter 怎么用
- Pydantic BaseModel 的定义方法

## 文件清单

```
backend/
└── app/
    ├── models/
    │   └── schemas.py        # ★ 所有请求/响应的 Pydantic 模型
    └── api/
        └── routes.py          # ★ MVP 路由（挂载在 /api/v1）
```

---

## Step 1：定义数据模型

创建 `backend/app/models/schemas.py`。

不用一次写完所有模型，先写本章需要的：

```python
from typing import Optional
from pydantic import BaseModel, Field


# ===== 推荐相关 =====
class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户自然语言输入")
    top_k: int = Field(default=3, ge=1, le=10, description="返回数量")


class ParsedSlotsResponse(BaseModel):
    budget_max: Optional[float] = None
    location: Optional[str] = None
    scene: Optional[str] = None
    taste: Optional[str] = None
    time: Optional[str] = None


class ShopResult(BaseModel):
    shop_id: int
    name: str
    campus: str
    area: str = ""
    avg_price: Optional[float] = None
    tags: str = ""
    score: float
    reason: str


class RecommendMeta(BaseModel):
    total_candidates: int
    returned: int
    engine: str = "rule-based"


class RecommendResponse(BaseModel):
    parsed: ParsedSlotsResponse
    recommendations: list[ShopResult]
    meta: RecommendMeta


# ===== 健康检查 =====
class HealthResponse(BaseModel):
    status: str


# ===== 热门排行 =====
class HotRankingItem(BaseModel):
    rank: int
    name: str
    tag: str
    avg_price: Optional[float] = None
    query: str


class HotRankingResponse(BaseModel):
    items: list[HotRankingItem]
    generated_at: str
```

**为什么用 Pydantic 而不是 dataclass？**
- FastAPI 原生支持 Pydantic，自动生成 Swagger 文档和请求校验
- Pydantic v2 的 `Field(min_length=1)` 会在请求到达你的代码之前拦截非法输入

---

## Step 2：写路由

创建 `backend/app/api/routes.py`：

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.models.schemas import (
    HealthResponse,
    HotRankingItem,
    HotRankingResponse,
    RecommendRequest,
    RecommendResponse,
    ShopResult,
    ParsedSlotsResponse,
    RecommendMeta,
)
from app.services.parser import parse_query
from app.services.recommender import recommend
from app.services.shop_repository import fetch_active_shops, fetch_store_detail_by_name, suggest_store_names

router = APIRouter()


# ---- 健康检查 ----
@router.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


# ---- 核心推荐端点 ----
@router.post("/recommend", response_model=RecommendResponse)
def post_recommend(req: RecommendRequest):
    # 1. 解析
    slots = parse_query(req.query)

    # 2. 推荐
    results = recommend(slots, top_k=req.top_k)
    total = len(fetch_active_shops())

    return RecommendResponse(
        parsed=ParsedSlotsResponse(
            budget_max=slots.budget_max,
            location=slots.location,
            scene=slots.scene,
            taste=slots.taste,
            time=slots.time,
        ),
        recommendations=[
            ShopResult(
                shop_id=r["shop_id"],
                name=r["name"],
                campus=r["campus"],
                area=r.get("area", ""),
                avg_price=r["avg_price"],
                tags=r.get("tags", ""),
                score=r["score"],
                reason=r["reason"],
            )
            for r in results
        ],
        meta=RecommendMeta(
            total_candidates=total,
            returned=len(results),
            engine="rule-based",
        ),
    )


# ---- 店铺详情 ----
@router.get("/stores/detail")
def get_store_detail(name: str = Query(..., min_length=1)):
    """根据店名查详情"""
    shop = fetch_store_detail_by_name(name)
    if not shop:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="店铺不存在")
    return {"data": shop}


# ---- 店名自动补全 ----
@router.get("/stores/suggest")
def get_store_suggestions(keyword: str = Query(..., min_length=1)):
    names = suggest_store_names(keyword)
    return {"suggestions": names}


# ---- 热门排行（简化版） ----
@router.get("/rankings/today")
def get_today_rankings():
    # 简易实现：按评分排序取 Top 5
    shops = fetch_active_shops()
    shops.sort(key=lambda s: s.get("rating") or 0, reverse=True)
    items = []
    for i, s in enumerate(shops[:5]):
        items.append(HotRankingItem(
            rank=i + 1,
            name=s["name"],
            tag=s.get("category") or "美食",
            avg_price=s.get("avg_price"),
            query=s["name"],
        ))
    return HotRankingResponse(
        items=items,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
```

---

## Step 3：把路由挂载到 main.py

在 `backend/app/main.py` 中添加：

```python
from app.api.routes import router

# ... 中间件配置 ...

app.include_router(router, prefix="/api/v1", tags=["mvp"])
```

---

## Step 4：验证

启动后端后，打开 `http://localhost:8000/docs`：

1. `POST /api/v1/recommend` — 输入 `{"query": "清水河，一个人吃清淡的，别太贵"}`
2. `GET /api/v1/stores/detail?name=学子餐厅`
3. `GET /api/v1/stores/suggest?keyword=米线`
4. `GET /api/v1/rankings/today`
5. `GET /api/v1/health`

全部跑通确认返回格式符合预期。

---

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| 422 Unprocessable Entity | Pydantic 校验不过（query 为空、格式不对） | 对照 schemas.py 检查字段类型 |
| 响应中文 `\uXXXX` | FastAPI 默认 `ensure_ascii=True` | 别用 `json.dumps` 手动序列化；FastAPI 自动处理 |
| `response_model` 返回字段缺失 | Pydantic 模型字段名和数据库字段名不一致 | 检查 schemas.py 中的字段名 == SQLite 列名 |

---

## 章末检查

- [ ] 所有端点能在 Swagger 文档中看到
- [ ] `POST /api/v1/recommend` 返回 parsed + recommendations + meta 三部分
- [ ] `GET /api/v1/stores/detail` 返回完整店铺信息
- [ ] `GET /api/v1/stores/suggest` 返回店名列表
- [ ] `GET /api/v1/rankings/today` 返回热门排行
