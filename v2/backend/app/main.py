from pathlib import Path
import sqlite3
from threading import Lock

from fastapi import FastAPI, HTTPException

from app.data_repository import ProcessedDatasetRepository
from app.models import DatasetStatusResponse, HealthResponse, RecommendationRequest, RecommendationResponse
from app.personalized import recommend_personalized, recommend_anonymous
from app.serving.model import ServingRepository
from app.ranking.learned import RankingRepository
from app.events import EventRepository, register_event_routes
from app.demo import register_demo_routes

app = FastAPI(title="CampusFoodAgent Yelp v2 API", version="0.4.0")
dataset_repository = ProcessedDatasetRepository(
    Path(__file__).resolve().parents[1] / "data" / "processed"
)
serving_repository = ServingRepository(Path(__file__).resolve().parents[1] / "data" / "derived" / "serving_v1")
ranking_repository = RankingRepository(Path(__file__).resolve().parents[1] / 'data/derived/ranking_v1')
try:
    from app.retrieval.semantic import SearchRepository
    search_repository = SearchRepository(Path(__file__).resolve().parents[1] / 'data/derived/search_v1')
except ImportError:
    search_repository = None
_event_repository = None
_event_lock = Lock()


def get_event_repository():
    global _event_repository
    with _event_lock:
        if _event_repository is None:
            _event_repository=EventRepository(Path(__file__).resolve().parents[1]/'data/derived/demo_events/events.sqlite3')
        return _event_repository


register_event_routes(app,lambda:get_event_repository())
register_demo_routes(app)


@app.get('/api/v2/system/status')
def system_status():
    result={'version':'0.4.0','scope':'local_offline_demo'}
    for key,repository in [('history',serving_repository),('search',search_repository),('ranker',ranking_repository)]:
        try:
            if repository is None:raise ValueError('Unavailable dependency')
            bundle=repository.load()
            manifest=bundle['manifest']
            result[key]={'available':True,'version':manifest.get('model_version',manifest.get('experiment_id')),
                         'selection':bundle.get('selection'),'profile_count':manifest.get('profile_count')}
        except (ImportError,OSError,ValueError,KeyError,TypeError):
            result[key]={'available':False}
    try:result['events']={'available':True,'metrics':get_event_repository().metrics()}
    except (OSError,sqlite3.Error):result['events']={'available':False}
    return result


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
            response=recommend_personalized(request, dataset_repository, serving_repository,
                search_repository=search_repository,ranking_repository=ranking_repository)
        else:
            response=recommend_anonymous(request,dataset_repository,search_repository=search_repository)
        try:
            response.metadata['request_id']=get_event_repository().record_exposure(request,response)
        except (OSError,sqlite3.Error,ValueError):
            response.metadata.setdefault('warnings',[]).append('event_store_unavailable')
        return response
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Recommendation data unavailable") from exc
