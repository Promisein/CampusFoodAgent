from fastapi.testclient import TestClient

import app.main as main_module
from app.data_repository import ProcessedDatasetRepository
from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/api/v2/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "v2",
        "project": "CampusFoodAgent Yelp",
    }


def test_dataset_status_uses_processed_manifest():
    response = client.get("/api/v2/dataset/status")

    assert response.status_code == 200
    assert response.json() == {
        "dataset": "yelp_processed",
        "data_version": "yelp_open_dataset_local",
        "city": "Tampa",
        "state": "FL",
        "business_count": 3805,
        "interaction_count": 100000,
        "representative_review_count": 29092,
        "raw_yelp_required": False,
    }


def test_dataset_status_reports_processed_data_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main_module,
        "dataset_repository",
        ProcessedDatasetRepository(tmp_path),
    )
    error_client = TestClient(app, raise_server_exceptions=False)

    response = error_client.get("/api/v2/dataset/status")

    assert response.status_code == 503
    assert response.json()["detail"].startswith("Processed dataset unavailable:")
    assert "data_manifest.json" in response.json()["detail"]


def test_recommend_endpoint_returns_evidence_backed_yelp_results():
    response = client.post(
        "/api/v2/recommend",
        json={
            "query": "quiet pizza dinner",
            "latitude": 39.9526,
            "longitude": -75.1652,
            "radius_km": 3,
            "max_price_level": 2,
            "city": "Philadelphia",
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "v2"
    assert payload["engine"] == "fixture_geo_keyword_rag"
    assert payload["recommendations"]
    first = payload["recommendations"][0]
    assert first["business_id"] == "v2_yelp_biz_001"
    assert first["distance_km"] <= 3
    assert first["evidence"]
