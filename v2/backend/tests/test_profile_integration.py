import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.data_pipeline.split_interactions import split_interactions
from app.main import app
from app.profiles.build_profiles import build_profile_snapshots
from app.profiles.profile_repository import UserProfileRepository


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BACKEND_ROOT / "data" / "processed"


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _sort_key(row: dict) -> tuple[datetime, str]:
    return datetime.fromisoformat(row["event_time"]), row["interaction_id"]


def test_real_profiles_are_traceable_and_leakage_safe(tmp_path):
    interactions_path = PROCESSED_DIR / "interactions.jsonl"
    businesses_path = PROCESSED_DIR / "businesses.jsonl"
    source_manifest = json.loads(
        (PROCESSED_DIR / "data_manifest.json").read_text(encoding="utf-8")
    )
    source_before = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (interactions_path, businesses_path)
    }
    split_dir = tmp_path / "split"
    profile_dir = tmp_path / "profiles"

    split_manifest = split_interactions(
        interactions_path,
        split_dir,
        source_data_version=source_manifest["data_version"],
    )
    profile_manifest = build_profile_snapshots(
        split_dir,
        businesses_path,
        profile_dir,
    )
    repository = UserProfileRepository(profile_dir)
    profiles = repository.load_profiles()

    assert split_manifest["counts"] == {
        "train": 30978,
        "validation": 3023,
        "test": 3023,
        "cold_start": 62976,
        "total": 100000,
    }
    assert profile_manifest["profile_count"] == 6046
    assert repository.load_manifest()["warm_user_count"] == 3023
    assert len(profiles) == 6046
    assert len({profile["profile_id"] for profile in profiles}) == 6046

    businesses = {
        row["business_id"]: row for row in _read_jsonl(businesses_path)
    }
    train_counts = Counter(
        row["user_id"] for row in _read_jsonl(split_dir / "train_interactions.jsonl")
    )
    validation_targets = {
        row["user_id"]: row
        for row in _read_jsonl(split_dir / "validation_interactions.jsonl")
    }
    test_targets = {
        row["user_id"]: row
        for row in _read_jsonl(split_dir / "test_interactions.jsonl")
    }

    for profile in profiles:
        target = (
            validation_targets[profile["user_id"]]
            if profile["target_split"] == "validation"
            else test_targets[profile["user_id"]]
        )
        expected_history_count = train_counts[profile["user_id"]] + (
            profile["target_split"] == "test"
        )
        assert profile["history_count"] == expected_history_count
        assert profile["cutoff_interaction_id"] == target["interaction_id"]
        assert profile["as_of_time"] == target["event_time"]
        assert profile["cutoff_interaction_id"] not in profile["recent_interaction_ids"]
        assert set(profile["recent_business_ids"]) <= businesses.keys()
        assert (
            datetime.fromisoformat(profile["history_end_time"]),
            profile["recent_interaction_ids"][-1],
        ) < _sort_key(target)

    source_after = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (interactions_path, businesses_path)
    }
    assert source_after == source_before


def test_online_recommendation_remains_on_processed_rule_engine():
    response = TestClient(app).post(
        "/api/v2/recommend",
        json={
            "query": "coffee breakfast",
            "latitude": 27.9506,
            "longitude": -82.4572,
            "radius_km": 5,
            "max_price_level": 2,
            "top_k": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["engine"] == "processed_geo_keyword_evidence"
