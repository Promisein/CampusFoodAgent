from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.data_repository import ProcessedDatasetRepository
from test_serving_model import make_snapshot


def setup_service(tmp_path, monkeypatch):
    from app.serving.model import ServingRepository

    source, out, businesses, _ = make_snapshot(tmp_path)
    monkeypatch.setattr(main_module, "dataset_repository", ProcessedDatasetRepository(source))
    monkeypatch.setattr(main_module, "serving_repository", ServingRepository(out))
    return TestClient(main_module.app), source, out, businesses


def payload(user="u"):
    return {"query": "coffee", "user_id": user, "latitude": 0, "longitude": 0,
            "radius_km": 10, "max_price_level": 2, "top_k": 5}


def test_user_profile_changes_results_and_preserves_hard_filters(tmp_path, monkeypatch):
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    first = client.post("/api/v2/recommend", json=payload()).json()
    second = client.post("/api/v2/recommend", json=payload("v")).json()
    assert first["engine"] == "personalized_weighted_rrf"
    assert first["metadata"]["profile_found"] is True
    assert first["metadata"]["snapshot_cutoff"].startswith("2020-01-02")
    ids = [row["business_id"] for row in first["recommendations"]]
    assert set(ids) == {"B", "C"}
    assert ids != [row["business_id"] for row in second["recommendations"]]
    assert first["recommendations"][0]["channel_scores"]
    assert all(set(row["reason_business_ids"]) <= {"A"} for row in first["recommendations"])


def test_unknown_user_uses_geo_popularity_without_inventing_history(tmp_path, monkeypatch):
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    response = client.post("/api/v2/recommend", json=payload("unknown"))
    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "personalized_geo_popularity"
    assert body["metadata"]["profile_found"] is False
    assert all(not row["reason_business_ids"] for row in body["recommendations"])


def test_missing_model_and_evidence_fall_back_with_explicit_warnings(tmp_path, monkeypatch):
    from app.serving.model import ServingRepository

    client, source, _, _ = setup_service(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "serving_repository", ServingRepository(tmp_path / "missing"))
    (source / "representative_reviews.jsonl").unlink()
    body = client.post("/api/v2/recommend", json=payload()).json()
    assert body["engine"] == "processed_rule_fallback"
    assert "model_unavailable" in body["metadata"]["warnings"]
    assert "evidence_unavailable" in body["metadata"]["warnings"]
    assert body["recommendations"]
    assert all(not row["evidence"] for row in body["recommendations"])


def test_single_channel_failure_keeps_legal_personalized_candidates(tmp_path, monkeypatch):
    from app.serving.model import RequestRecallIndex

    client, _, out, _ = setup_service(tmp_path, monkeypatch)
    (out / "content.json").unlink()
    original = RequestRecallIndex.recommend

    def fail_cf(self, user, source, **kwargs):
        if source == "itemcf":
            raise TimeoutError("injected channel timeout")
        return original(self, user, source, **kwargs)

    monkeypatch.setattr(RequestRecallIndex, "recommend", fail_cf)
    body = client.post("/api/v2/recommend", json=payload()).json()
    assert {row["business_id"] for row in body["recommendations"]} == {"B", "C"}
    assert "content_unavailable" in body["metadata"]["warnings"]
    assert "itemcf_unavailable" in body["metadata"]["warnings"]


def test_missing_base_dataset_returns_503(tmp_path, monkeypatch):
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "dataset_repository", ProcessedDatasetRepository(tmp_path / "missing"))
    assert client.post("/api/v2/recommend", json=payload()).status_code == 503


@pytest.mark.parametrize("change", [{"latitude": 91}, {"longitude": 181}, {"user_id": " "}])
def test_invalid_location_or_user_is_rejected(change):
    assert TestClient(main_module.app).post("/api/v2/recommend", json={**payload(), **change}).status_code == 422

@pytest.mark.parametrize('broken', ['selection', 'popularity'])
def test_corrupted_artifacts_degrade_without_server_error_or_seen_leak(tmp_path, monkeypatch, broken):
    import json
    client, _, out, _ = setup_service(tmp_path, monkeypatch)
    if broken == 'selection':
        path = out / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['selection']['simulated_geo'] = []
        path.write_text(json.dumps(manifest), encoding='utf-8')
    else:
        (out / 'popularity.json').unlink()
    response = client.post('/api/v2/recommend', json=payload())
    assert response.status_code == 200
    body = response.json()
    if broken == 'selection':
        assert 'model_unavailable' in body['metadata']['warnings']
    else:
        assert body['metadata']['profile_found'] is True
        assert 'popularity_unavailable' in body['metadata']['warnings']
        assert all(row['business_id'] != 'A' for row in body['recommendations'])
        assert body['engine'] == 'personalized_weighted_rrf'
