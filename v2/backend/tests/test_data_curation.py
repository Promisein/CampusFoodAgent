import json
from pathlib import Path

from app.data_pipeline.curate_yelp import YelpCurationConfig, curate_yelp_dataset


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_curator_selects_densest_restaurant_city_and_filters_businesses(tmp_path):
    archive = tmp_path / "archive"
    output = tmp_path / "processed"
    archive.mkdir()
    _write_jsonl(
        archive / "yelp_academic_dataset_business.json",
        [
            {
                "business_id": "phl_open_1",
                "name": "Pizza One",
                "city": "Philadelphia",
                "state": "PA",
                "latitude": 39.95,
                "longitude": -75.16,
                "stars": 4.5,
                "review_count": 100,
                "is_open": 1,
                "categories": "Restaurants, Pizza",
                "attributes": {"RestaurantsPriceRange2": "2"},
                "hours": {"Monday": "10:0-22:0"},
            },
            {
                "business_id": "phl_open_2",
                "name": "Coffee Two",
                "city": "Philadelphia",
                "state": "PA",
                "latitude": 39.96,
                "longitude": -75.15,
                "stars": 4.0,
                "review_count": 90,
                "is_open": 1,
                "categories": "Food, Coffee & Tea",
                "attributes": {},
                "hours": None,
            },
            {
                "business_id": "tpa_open_1",
                "name": "Tampa Sushi",
                "city": "Tampa",
                "state": "FL",
                "latitude": 27.95,
                "longitude": -82.45,
                "stars": 5.0,
                "review_count": 300,
                "is_open": 1,
                "categories": "Restaurants, Sushi Bars",
                "attributes": {},
                "hours": None,
            },
            {
                "business_id": "phl_non_food",
                "name": "Philly Printer",
                "city": "Philadelphia",
                "state": "PA",
                "latitude": 39.97,
                "longitude": -75.14,
                "stars": 3.0,
                "review_count": 10,
                "is_open": 1,
                "categories": "Printing Services",
                "attributes": {},
                "hours": None,
            },
        ],
    )
    _write_jsonl(archive / "yelp_academic_dataset_review.json", [])

    manifest = curate_yelp_dataset(YelpCurationConfig(archive_dir=archive, output_dir=output))

    assert manifest["selected_city"] == {"city": "Philadelphia", "state": "PA"}
    businesses = _read_jsonl(output / "businesses.jsonl")
    assert {row["business_id"] for row in businesses} == {"phl_open_1", "phl_open_2"}
    assert businesses[0]["price_level"] == 2
    assert manifest["kept"]["businesses"] == 2
    assert manifest["discarded"]["non_restaurant_or_non_food_businesses"] == 1
    assert manifest["discarded"]["businesses_outside_selected_city"] == 1


def test_curator_maps_only_selected_city_reviews_to_interactions_and_evidence(tmp_path):
    archive = tmp_path / "archive"
    output = tmp_path / "processed"
    archive.mkdir()
    _write_jsonl(
        archive / "yelp_academic_dataset_business.json",
        [
            {
                "business_id": "phl_open_1",
                "name": "Pizza One",
                "city": "Philadelphia",
                "state": "PA",
                "latitude": 39.95,
                "longitude": -75.16,
                "stars": 4.5,
                "review_count": 100,
                "is_open": 1,
                "categories": "Restaurants, Pizza",
                "attributes": {},
                "hours": None,
            },
            {
                "business_id": "tpa_open_1",
                "name": "Tampa Sushi",
                "city": "Tampa",
                "state": "FL",
                "latitude": 27.95,
                "longitude": -82.45,
                "stars": 5.0,
                "review_count": 300,
                "is_open": 1,
                "categories": "Restaurants, Sushi Bars",
                "attributes": {},
                "hours": None,
            },
        ],
    )
    _write_jsonl(
        archive / "yelp_academic_dataset_review.json",
        [
            {
                "review_id": "r1",
                "user_id": "u1",
                "business_id": "phl_open_1",
                "stars": 5,
                "text": "quiet dinner and good pizza",
                "date": "2021-01-01 12:00:00",
                "useful": 5,
            },
            {
                "review_id": "r2",
                "user_id": "u2",
                "business_id": "phl_open_1",
                "stars": 4,
                "text": "fast service",
                "date": "2021-01-02 12:00:00",
                "useful": 2,
            },
            {
                "review_id": "r3",
                "user_id": "u3",
                "business_id": "phl_open_1",
                "stars": 2,
                "text": "too loud",
                "date": "2021-01-03 12:00:00",
                "useful": 1,
            },
            {
                "review_id": "r4",
                "user_id": "u4",
                "business_id": "tpa_open_1",
                "stars": 5,
                "text": "outside city",
                "date": "2021-01-04 12:00:00",
                "useful": 9,
            },
        ],
    )

    manifest = curate_yelp_dataset(
        YelpCurationConfig(
            archive_dir=archive,
            output_dir=output,
            city="Philadelphia",
            state="PA",
            max_reviews_total=2,
            max_reviews_per_business=2,
            representative_reviews_per_business=1,
        )
    )

    interactions = _read_jsonl(output / "interactions.jsonl")
    evidence = _read_jsonl(output / "representative_reviews.jsonl")
    assert [row["interaction_id"] for row in interactions] == ["r1", "r2"]
    assert all(row["event_type"] == "review" for row in interactions)
    assert all(row["source"] == "yelp_review" for row in interactions)
    assert [row["review_id"] for row in evidence] == ["r1"]
    assert manifest["kept"]["reviews_as_interactions"] == 2
    assert manifest["discarded"]["reviews_outside_selected_businesses"] == 1
    assert manifest["discarded"]["reviews_over_limits"] == 1


def test_curator_manifest_documents_retained_and_excluded_raw_files(tmp_path):
    archive = tmp_path / "archive"
    output = tmp_path / "processed"
    archive.mkdir()
    _write_jsonl(
        archive / "yelp_academic_dataset_business.json",
        [
            {
                "business_id": "phl_open_1",
                "name": "Pizza One",
                "city": "Philadelphia",
                "state": "PA",
                "latitude": 39.95,
                "longitude": -75.16,
                "stars": 4.5,
                "review_count": 100,
                "is_open": 1,
                "categories": "Restaurants, Pizza",
                "attributes": {},
                "hours": None,
            }
        ],
    )
    _write_jsonl(archive / "yelp_academic_dataset_review.json", [])

    manifest = curate_yelp_dataset(
        YelpCurationConfig(archive_dir=archive, output_dir=output, city="Philadelphia", state="PA")
    )

    assert manifest["retained_raw_sources"] == [
        "yelp_academic_dataset_business.json",
        "yelp_academic_dataset_review.json",
    ]
    assert manifest["excluded_raw_sources"] == {
        "yelp_academic_dataset_user.json": "not needed for the first runnable agent; user histories are derived from review interactions",
        "yelp_academic_dataset_checkin.json": "deferred to a later heat and active-time feature pass",
        "yelp_academic_dataset_tip.json": "optional RAG short-text evidence, excluded from the first reproducible curation",
    }
    assert (output / "data_manifest.json").exists()
    assert (output / "city_statistics.json").exists()
