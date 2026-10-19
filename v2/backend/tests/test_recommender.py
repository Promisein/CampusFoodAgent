import json
from pathlib import Path

from app.data_repository import ProcessedDatasetRepository
from app.models import RecommendationRequest
from app.recommender import recommend_restaurants


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _processed_business(
    business_id: str,
    *,
    name: str = "Tampa Coffee",
    city: str = "Tampa",
    latitude: float = 27.9506,
    longitude: float = -82.4572,
    price_level: int | None = 2,
    is_open: bool = True,
    stars: float = 4.5,
    review_count: int = 100,
    attributes: dict | None = None,
) -> dict:
    return {
        "business_id": business_id,
        "name": name,
        "categories_raw": "Restaurants, Coffee & Tea",
        "categories_normalized": ["Restaurants", "Coffee & Tea"],
        "latitude": latitude,
        "longitude": longitude,
        "city": city,
        "state": "FL",
        "stars": stars,
        "review_count": review_count,
        "price_level": price_level,
        "hours": {},
        "attributes": attributes or {},
        "is_open": is_open,
        "data_version": "test",
    }


def _processed_review(review_id: str, business_id: str, text: str = "quiet coffee") -> dict:
    return {
        "review_id": review_id,
        "business_id": business_id,
        "user_id": "user-1",
        "rating": 5.0,
        "review_date": "2021-01-01 12:00:00",
        "useful": 2,
        "text": text,
        "source": "yelp_review",
    }


def _processed_repository(tmp_path: Path, businesses: list[dict], reviews: list[dict]):
    _write_jsonl(tmp_path / "businesses.jsonl", businesses)
    _write_jsonl(tmp_path / "representative_reviews.jsonl", reviews)
    return ProcessedDatasetRepository(tmp_path)


def test_recommend_maps_processed_business_and_review_evidence(tmp_path):
    repository = _processed_repository(
        tmp_path,
        [_processed_business("tampa-1")],
        [_processed_review("review-1", "tampa-1")],
    )
    request = RecommendationRequest(
        query="quiet coffee",
        latitude=27.9506,
        longitude=-82.4572,
        radius_km=3,
        max_price_level=2,
        city="Tampa",
        top_k=1,
    )

    results = recommend_restaurants(request, repository)

    assert len(results) == 1
    assert results[0].business_id == "tampa-1"
    assert results[0].categories == ["Restaurants", "Coffee & Tea"]
    assert results[0].rating == 4.5
    assert results[0].evidence[0].document_id == "review-1"
    assert results[0].evidence[0].source == "yelp_review"


def test_processed_recommend_applies_all_hard_filters_and_excludes_missing_price(tmp_path):
    repository = _processed_repository(
        tmp_path,
        [
            _processed_business("missing-price", price_level=None),
            _processed_business("good"),
            _processed_business("closed", is_open=False),
            _processed_business("other-city", city="Philadelphia"),
            _processed_business("far-away", latitude=28.0506),
            _processed_business("too-expensive", price_level=3),
        ],
        [],
    )
    request = RecommendationRequest(
        query="coffee",
        latitude=27.9506,
        longitude=-82.4572,
        radius_km=3,
        max_price_level=2,
        city="Tampa",
        top_k=10,
    )

    results = recommend_restaurants(request, repository)

    assert [item.business_id for item in results] == ["good"]


def test_processed_recommend_searches_attribute_values(tmp_path):
    repository = _processed_repository(
        tmp_path,
        [
            _processed_business("plain", name="Plain Cafe"),
            _processed_business(
                "quiet",
                name="Study Cafe",
                attributes={"Ambience": "{'quiet': True}"},
            ),
        ],
        [],
    )
    request = RecommendationRequest(
        query="quiet",
        latitude=27.9506,
        longitude=-82.4572,
        radius_km=3,
        max_price_level=2,
        city="Tampa",
        top_k=2,
    )

    results = recommend_restaurants(request, repository)

    assert results[0].business_id == "quiet"
    assert "matched query terms: quiet" in results[0].reasons


def test_processed_recommend_keeps_stable_order_and_business_specific_evidence(tmp_path):
    repository = _processed_repository(
        tmp_path,
        [
            _processed_business("business-b", name="Same Cafe"),
            _processed_business("business-a", name="Same Cafe"),
        ],
        [
            _processed_review("review-b", "business-b"),
            _processed_review("review-a", "business-a"),
        ],
    )
    request = RecommendationRequest(
        query="coffee",
        latitude=27.9506,
        longitude=-82.4572,
        radius_km=3,
        max_price_level=2,
        city="Tampa",
        top_k=2,
    )

    results = recommend_restaurants(request, repository)

    assert [item.business_id for item in results] == ["business-a", "business-b"]
    assert [item.evidence[0].document_id for item in results] == ["review-a", "review-b"]


def test_recommend_filters_by_city_radius_price_and_category():
    request = RecommendationRequest(
        query="quiet pizza dinner",
        latitude=39.9526,
        longitude=-75.1652,
        radius_km=3,
        max_price_level=2,
        city="Philadelphia",
        top_k=3,
    )

    results = recommend_restaurants(request)

    assert results
    assert all(item.city == "Philadelphia" for item in results)
    assert all(item.distance_km <= 3 for item in results)
    assert all(item.price_level <= 2 for item in results)
    assert results[0].business_id == "v2_yelp_biz_001"
    assert results[0].evidence


def test_recommend_never_returns_closed_or_out_of_scope_businesses():
    request = RecommendationRequest(
        query="sushi",
        latitude=39.9526,
        longitude=-75.1652,
        radius_km=10,
        max_price_level=4,
        city="Philadelphia",
        top_k=10,
    )

    results = recommend_restaurants(request)

    ids = {item.business_id for item in results}
    assert "v2_yelp_biz_closed" not in ids
    assert "v2_yelp_biz_other_city" not in ids


def test_recommend_returns_empty_list_when_hard_filters_remove_everything():
    request = RecommendationRequest(
        query="pizza",
        latitude=39.9526,
        longitude=-75.1652,
        radius_km=0.1,
        max_price_level=1,
        city="Philadelphia",
        top_k=5,
    )

    assert recommend_restaurants(request) == []
