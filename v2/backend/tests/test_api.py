import json

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


def test_recommend_endpoint_uses_processed_tampa_data_by_default(tmp_path, monkeypatch):
    business = {
        "business_id": "tampa-api-1",
        "name": "Tampa Study Cafe",
        "categories_raw": "Restaurants, Coffee & Tea",
        "categories_normalized": ["Restaurants", "Coffee & Tea"],
        "latitude": 27.9506,
        "longitude": -82.4572,
        "city": "Tampa",
        "state": "FL",
        "stars": 4.7,
        "review_count": 120,
        "price_level": 2,
        "hours": {},
        "attributes": {"Ambience": "{'quiet': True}"},
        "is_open": True,
        "data_version": "test",
    }
    review = {
        "review_id": "tampa-review-1",
        "business_id": "tampa-api-1",
        "user_id": "user-1",
        "rating": 5.0,
        "review_date": "2021-01-01 12:00:00",
        "useful": 3,
        "text": "Quiet coffee and breakfast place.",
        "source": "yelp_review",
    }
    (tmp_path / "businesses.jsonl").write_text(json.dumps(business) + "\n", encoding="utf-8")
    (tmp_path / "representative_reviews.jsonl").write_text(
        json.dumps(review) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "dataset_repository", ProcessedDatasetRepository(tmp_path))

    response = client.post(
        "/api/v2/recommend",
        json={
            "query": "quiet coffee breakfast",
            "latitude": 27.9506,
            "longitude": -82.4572,
            "radius_km": 3,
            "max_price_level": 2,
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "v2"
    assert payload["engine"] == "processed_geo_keyword_evidence"
    assert payload["recommendations"]
    first = payload["recommendations"][0]
    assert first["business_id"] == "tampa-api-1"
    assert first["city"] == "Tampa"
    assert first["distance_km"] <= 3
    assert first["evidence"][0]["document_id"] == "tampa-review-1"
