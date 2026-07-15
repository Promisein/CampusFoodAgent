import importlib
import importlib.util
import json
from pathlib import Path

import pytest


def _repository_class():
    spec = importlib.util.find_spec("app.data_repository")
    assert spec is not None, "app.data_repository must be implemented"
    module = importlib.import_module("app.data_repository")
    return module.ProcessedDatasetRepository


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _business(business_id: str) -> dict:
    return {
        "business_id": business_id,
        "name": f"Business {business_id}",
        "categories_raw": "Restaurants, Coffee & Tea",
        "categories_normalized": ["Restaurants", "Coffee & Tea"],
        "latitude": 27.95,
        "longitude": -82.45,
        "city": "Tampa",
        "state": "FL",
        "stars": 4.5,
        "review_count": 100,
        "price_level": 2,
        "hours": {},
        "attributes": {},
        "is_open": True,
        "data_version": "test",
    }


def _review(review_id: str, business_id: str) -> dict:
    return {
        "review_id": review_id,
        "business_id": business_id,
        "user_id": "user-1",
        "rating": 5.0,
        "review_date": "2021-01-01 12:00:00",
        "useful": 1,
        "text": "quiet coffee shop",
        "source": "yelp_review",
    }


def test_repository_loads_manifest_businesses_and_grouped_reviews(tmp_path):
    repository_class = _repository_class()
    _write_json(
        tmp_path / "data_manifest.json",
        {
            "data_version": "test",
            "selected_city": {"city": "Tampa", "state": "FL"},
            "kept": {
                "businesses": 2,
                "reviews_as_interactions": 2,
                "representative_reviews": 2,
            },
        },
    )
    _write_jsonl(tmp_path / "businesses.jsonl", [_business("b1"), _business("b2")])
    _write_jsonl(
        tmp_path / "representative_reviews.jsonl",
        [_review("r1", "b1"), _review("r2", "b1")],
    )

    repository = repository_class(tmp_path)

    assert repository.load_manifest()["selected_city"]["city"] == "Tampa"
    assert [row["business_id"] for row in repository.load_businesses()] == ["b1", "b2"]
    assert list(repository.load_representative_reviews_by_business()) == ["b1"]
    assert [row["review_id"] for row in repository.load_representative_reviews_by_business()["b1"]] == [
        "r1",
        "r2",
    ]


def test_repository_reports_the_missing_processed_file(tmp_path):
    repository = _repository_class()(tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match=r"Required processed dataset file is missing: .*businesses\.jsonl",
    ):
        repository.load_businesses()


def test_repository_rejects_businesses_missing_required_fields(tmp_path):
    invalid_business = _business("b1")
    invalid_business.pop("business_id")
    _write_jsonl(tmp_path / "businesses.jsonl", [invalid_business])
    repository = _repository_class()(tmp_path)

    with pytest.raises(
        ValueError,
        match=r"businesses\.jsonl line 1 is missing required fields: business_id",
    ):
        repository.load_businesses()


def test_repository_rejects_reviews_missing_required_fields(tmp_path):
    invalid_review = _review("r1", "b1")
    invalid_review.pop("review_id")
    _write_jsonl(tmp_path / "representative_reviews.jsonl", [invalid_review])
    repository = _repository_class()(tmp_path)

    with pytest.raises(
        ValueError,
        match=r"representative_reviews\.jsonl line 1 is missing required fields: review_id",
    ):
        repository.load_representative_reviews_by_business()


def test_repository_rejects_manifest_missing_required_fields(tmp_path):
    _write_json(
        tmp_path / "data_manifest.json",
        {
            "data_version": "test",
            "kept": {},
        },
    )
    repository = _repository_class()(tmp_path)

    with pytest.raises(
        ValueError,
        match=r"data_manifest\.json is missing required fields: selected_city",
    ):
        repository.load_manifest()


def test_repository_caches_loaded_processed_data(tmp_path):
    _write_json(
        tmp_path / "data_manifest.json",
        {
            "data_version": "test",
            "selected_city": {"city": "Tampa", "state": "FL"},
            "kept": {},
        },
    )
    _write_jsonl(tmp_path / "businesses.jsonl", [_business("b1")])
    _write_jsonl(tmp_path / "representative_reviews.jsonl", [_review("r1", "b1")])
    repository = _repository_class()(tmp_path)

    first_manifest = repository.load_manifest()
    first_businesses = repository.load_businesses()
    first_reviews = repository.load_representative_reviews_by_business()
    _write_jsonl(tmp_path / "businesses.jsonl", [_business("b1"), _business("b2")])
    _write_jsonl(
        tmp_path / "representative_reviews.jsonl",
        [_review("r1", "b1"), _review("r2", "b2")],
    )

    assert repository.load_manifest() is first_manifest
    assert repository.load_businesses() is first_businesses
    assert repository.load_representative_reviews_by_business() is first_reviews
    assert len(repository.load_businesses()) == 1
    assert list(repository.load_representative_reviews_by_business()) == ["b1"]
