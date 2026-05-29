import json
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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


# ===== 店铺详情 =====
class StoreDetailResponse(BaseModel):
    """对外暴露的店铺详情——隐藏 created_at/updated_at/poi_id，JSON 字段转为数组"""
    id: int
    name: str
    campus: str
    area: Optional[str] = None
    category: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    avg_price: Optional[float] = None
    open_hours: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    review_count: int = 0
    tastes: list[str] = []
    scenes: list[str] = []
    tags: list[str] = []
    image_urls: list[str] = []

    @field_validator("tastes", "scenes", "tags", "image_urls", mode="before")
    @classmethod
    def _parse_json_list(cls, v):
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return []


# ===== 店名补全 =====
class StoreSuggestResponse(BaseModel):
    suggestions: list[str]


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


# ===== DeepSeek AI 推荐 =====
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


# ===== 用户认证 =====
class WechatLoginRequest(BaseModel):
    code: str = Field(..., min_length=1)
    anonymousId: str = ""


class WechatLoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    userId: str
    anonymousId: str = ""


class AuthMeResponse(BaseModel):
    userId: str
    authenticated: bool = True


class ProfileSyncRequest(BaseModel):
    anonymousId: str = ""
    favorites: list[str] = []
