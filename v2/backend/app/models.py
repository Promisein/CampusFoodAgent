from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    query: str = Field(..., min_length=1)
    user_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(default=3, gt=0, le=50)
    max_price_level: int = Field(default=4, ge=1, le=4)
    city: str = Field(default="Tampa", min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class EvidenceItem(BaseModel):
    document_id: str
    source: str
    text: str
    business_id: str | None = None
    excerpt: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    relevance_score: float = 0


class RestaurantRecommendation(BaseModel):
    business_id: str
    name: str
    city: str
    categories: list[str]
    price_level: int
    rating: float
    review_count: int
    distance_km: float
    score: float
    reasons: list[str]
    evidence: list[EvidenceItem]
    channel_scores: dict[str, dict] = Field(default_factory=dict)
    reason_business_ids: list[str] = Field(default_factory=list)
    evidence_status: str = "not_requested"


class RecommendationResponse(BaseModel):
    version: str
    engine: str
    recommendations: list[RestaurantRecommendation]
    metadata: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    version: str
    project: str


class DatasetStatusResponse(BaseModel):
    dataset: str
    data_version: str
    city: str
    state: str
    business_count: int
    interaction_count: int
    representative_review_count: int
    raw_yelp_required: bool
