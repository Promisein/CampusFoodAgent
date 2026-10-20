from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.data_repository import ProcessedDatasetRepository
from app.models import DatasetStatusResponse, HealthResponse, RecommendationRequest, RecommendationResponse
from app.personalized import recommend_personalized, recommend_anonymous
from app.serving.model import ServingRepository

app = FastAPI(title="CampusFoodAgent Yelp v2 API", version="0.3.0")
dataset_repository = ProcessedDatasetRepository(
    Path(__file__).resolve().parents[1] / "data" / "processed"
)
serving_repository = ServingRepository(Path(__file__).resolve().parents[1] / "data" / "derived" / "serving_v1")


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
    try:
        if request.user_id is not None:
            return recommend_personalized(request, dataset_repository, serving_repository)
        return recommend_anonymous(request, dataset_repository)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Recommendation data unavailable") from exc
