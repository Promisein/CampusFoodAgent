from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    HealthResponse,
    HotRankingItem,
    HotRankingResponse,
    ParsedSlotsResponse,
    RecommendMeta,
    RecommendRequest,
    RecommendResponse,
    ShopResult,
    StoreDetailResponse,
    StoreSuggestResponse,
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
@router.get("/stores/detail", response_model=StoreDetailResponse)
def get_store_detail(name: str = Query(..., min_length=1)):
    """根据店名查详情"""
    shop = fetch_store_detail_by_name(name)
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return shop


# ---- 店名自动补全 ----
@router.get("/stores/suggest", response_model=StoreSuggestResponse)
def get_store_suggestions(keyword: str = Query(..., min_length=1)):
    names = suggest_store_names(keyword)
    return {"suggestions": names}


# ---- 热门排行（简化版） ----
@router.get("/rankings/today", response_model=HotRankingResponse)
def get_today_rankings():
    """简易实现：按评分排序取 Top 5（当前评分数据不完整，结果接近原始顺序）"""
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
