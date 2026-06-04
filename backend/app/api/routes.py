from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import require_authenticated_user

from app.models.schemas import (
    AdClickEventRequest,
    AdSlotItem,
    AdSlotsResponse,
    FeedbackRequest,
    FavoriteRemoveRequest,
    FavoriteRequest,
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
    TrackEventRequest,
)
from app.services.ad_repository import list_public_ad_slots, log_ad_click_event
from app.services.favorites_repository import add_favorite, list_favorites, remove_favorite
from app.services.feedback_repository import save_feedback
from app.services.hot_ranking import get_today_hot_rankings
from app.services.parser import parse_query
from app.services.recommender import recommend
from app.services.shop_repository import fetch_active_shops, fetch_store_detail_by_name, suggest_store_names
from app.services.usage_events import log_usage_event

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


# ---- 热门排行 ----
@router.get("/rankings/today", response_model=HotRankingResponse)
def get_today_rankings():
    """基于真实查询事件统计的热门排行。若无事件数据则回退评分排序。"""
    items_data = get_today_hot_rankings(limit=5)
    if items_data:
        items = []
        for item in items_data:
            items.append(HotRankingItem(
                rank=item["rank"],
                name=item["name"],
                tag=item["tag"],
                avg_price=item["avg_price"],
                query=item.get("query", item["name"]),
            ))
        return HotRankingResponse(
            items=items,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # 回退：按评分排序
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


# ---- 用户反馈 ----
@router.post("/feedback")
def submit_feedback(req: FeedbackRequest):
    fid = save_feedback(
        feedback_type=req.feedbackType,
        store_name=req.storeName,
        rating=req.rating,
        scene_tags=req.sceneTags,
        taste_tags=req.tasteTags,
        recommend_dish=req.recommendDish,
        comment=req.comment,
        uid=req.uid,
        user_id=req.userId,
        anonymous_id=req.anonymousId,
    )
    return {"ok": True, "id": fid}


# ---- 收藏 ----
@router.post("/favorites")
def add_user_favorite(req: FavoriteRequest, user_id: str = Depends(require_authenticated_user)):
    add_favorite(user_id=user_id, shop_id=req.shop_id, shop_name=req.shop_name)
    return {"ok": True}


@router.get("/favorites")
def get_user_favorites(user_id: str = Depends(require_authenticated_user)):
    return {"favorites": list_favorites(user_id)}


@router.delete("/favorites")
def remove_user_favorite(req: FavoriteRemoveRequest, user_id: str = Depends(require_authenticated_user)):
    remove_favorite(user_id=user_id, shop_id=req.shop_id)
    return {"ok": True}


# ---- 广告 ----
@router.get("/ads/slots", response_model=AdSlotsResponse)
def get_ad_slots(limit: int = Query(default=5, ge=1, le=20)):
    raw = list_public_ad_slots(limit=limit)
    return {"slots": [AdSlotItem(**s) for s in raw]}


@router.post("/events/ad-click")
def log_ad_click(req: AdClickEventRequest):
    log_ad_click_event(
        slot_id=req.slotId,
        uid=req.uid,
        user_id=req.userId,
        anonymous_id=req.anonymousId,
    )
    return {"ok": True}


# ---- 事件追踪 ----
@router.post("/events/track")
def track_event(req: TrackEventRequest):
    log_usage_event(
        event_type=req.event_type,
        uid=req.uid,
        user_id=req.user_id,
        anonymous_id=req.anonymous_id,
        query_text=req.query_text,
        shop_id=req.shop_id,
        shop_name=req.shop_name,
        extra=req.extra,
    )
    return {"ok": True}
