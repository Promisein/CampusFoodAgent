from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    query: str = Field(..., min_length=1)
    latitude: float
    longitude: float
    radius_km: float = Field(default=3, gt=0, le=50)
    max_price_level: int = Field(default=4, ge=1, le=4)
    city: str = Field(default="Philadelphia", min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class EvidenceItem(BaseModel):
    document_id: str
    source: str
    text: str


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


class RecommendationResponse(BaseModel):
    version: str
    engine: str
    recommendations: list[RestaurantRecommendation]


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
