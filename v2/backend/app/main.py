from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.data_repository import ProcessedDatasetRepository
from app.models import DatasetStatusResponse, HealthResponse, RecommendationRequest, RecommendationResponse
from app.recommender import recommend_restaurants

app = FastAPI(title="CampusFoodAgent Yelp v2 API", version="0.2.0")
dataset_repository = ProcessedDatasetRepository(
    Path(__file__).resolve().parents[1] / "data" / "processed"
)


@app.get("/api/v2/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        version="v2",
        project="CampusFoodAgent Yelp",
    )


@app.get("/api/v2/dataset/status", response_model=DatasetStatusResponse)
def dataset_status():
    try:
        manifest = dataset_repository.load_manifest()
        selected_city = manifest["selected_city"]
        kept = manifest["kept"]
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Processed dataset unavailable: {exc}") from exc
    return DatasetStatusResponse(
        dataset="yelp_processed",
        data_version=manifest["data_version"],
        city=selected_city["city"],
        state=selected_city["state"],
        business_count=kept["businesses"],
        interaction_count=kept["reviews_as_interactions"],
        representative_review_count=kept["representative_reviews"],
        raw_yelp_required=False,
    )


@app.post("/api/v2/recommend", response_model=RecommendationResponse)
def recommend(request: RecommendationRequest):
    return RecommendationResponse(
        version="v2",
        engine="processed_geo_keyword_evidence",
        recommendations=recommend_restaurants(request, dataset_repository),
    )
