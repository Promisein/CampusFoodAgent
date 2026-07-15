import json
import math
from functools import lru_cache
from pathlib import Path

from app.data_repository import ProcessedDatasetRepository
from app.models import EvidenceItem, RecommendationRequest, RestaurantRecommendation

EARTH_RADIUS_KM = 6371.0088


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "fixtures" / "yelp_restaurants.json"


@lru_cache(maxsize=1)
def load_restaurants() -> list[dict]:
    with _fixture_path().open(encoding="utf-8") as f:
        data = json.load(f)
    return data["businesses"]


def dataset_business_count() -> int:
    return len(load_restaurants())


def recommend_restaurants(
    request: RecommendationRequest,
    repository: ProcessedDatasetRepository | None = None,
) -> list[RestaurantRecommendation]:
    query_terms = _tokenize(request.query)
    scored: list[RestaurantRecommendation] = []
    businesses = repository.load_businesses() if repository else load_restaurants()
    reviews_by_business = (
        repository.load_representative_reviews_by_business() if repository else {}
    )

    for source_business in businesses:
        business = _recommendation_business(
            source_business,
            reviews_by_business.get(source_business["business_id"]),
        )
        if not business.get("is_open", True):
            continue
        if business["city"].lower() != request.city.lower():
            continue
        if business.get("price_level") is None:
            continue
        if int(business["price_level"]) > request.max_price_level:
            continue

        distance = _haversine_km(
            request.latitude,
            request.longitude,
            float(business["latitude"]),
            float(business["longitude"]),
        )
        if distance > request.radius_km:
            continue

        keyword_score, matched_terms = _keyword_score(business, query_terms)
        rating_score = float(business["rating"]) / 5.0
        review_confidence = min(math.log1p(int(business["review_count"])) / math.log1p(500), 1.0)
        distance_score = max(0.0, 1.0 - distance / request.radius_km)
        price_score = 1.0 - (int(business["price_level"]) - 1) / 4.0

        score = (
            keyword_score * 0.35
            + rating_score * 0.25
            + review_confidence * 0.15
            + distance_score * 0.15
            + price_score * 0.10
        )

        scored.append(
            RestaurantRecommendation(
                business_id=business["business_id"],
                name=business["name"],
                city=business["city"],
                categories=business["categories"],
                price_level=int(business["price_level"]),
                rating=float(business["rating"]),
                review_count=int(business["review_count"]),
                distance_km=round(distance, 3),
                score=round(score, 4),
                reasons=_build_reasons(business, matched_terms, distance),
                evidence=[
                    EvidenceItem(
                        document_id=review["review_id"],
                        source=review.get("source", "fixture_review"),
                        text=review["text"],
                    )
                    for review in business.get("representative_reviews", [])[:2]
                ],
            )
        )

    scored.sort(key=lambda item: (-item.score, item.distance_km, item.business_id))
    return scored[: request.top_k]


def _recommendation_business(business: dict, reviews: list[dict] | None) -> dict:
    if "categories_normalized" not in business:
        return business

    return {
        **business,
        "categories": business["categories_normalized"],
        "rating": business["stars"],
        "representative_reviews": reviews or [],
    }


def _tokenize(query: str) -> set[str]:
    return {part.strip().lower() for part in query.replace(",", " ").split() if part.strip()}


def _keyword_score(business: dict, query_terms: set[str]) -> tuple[float, list[str]]:
    if not query_terms:
        return 0.0, []

    searchable_parts = [
        business["name"],
        " ".join(business["categories"]),
        " ".join(_attribute_texts(business.get("attributes"))),
        " ".join(review["text"] for review in business.get("representative_reviews", [])),
    ]
    searchable_text = " ".join(searchable_parts).lower()
    matched = sorted(term for term in query_terms if term in searchable_text)
    return len(matched) / len(query_terms), matched


def _build_reasons(business: dict, matched_terms: list[str], distance_km: float) -> list[str]:
    reasons = [
        f"{business['rating']} stars from {business['review_count']} Yelp-style reviews",
        f"{distance_km:.1f} km from requested location",
    ]
    if matched_terms:
        reasons.insert(0, "matched query terms: " + ", ".join(matched_terms))
    attribute_texts = _attribute_texts(business.get("attributes"))
    if attribute_texts:
        reasons.append("attributes: " + ", ".join(attribute_texts[:3]))
    return reasons


def _attribute_texts(attributes: dict | list | None) -> list[str]:
    if isinstance(attributes, dict):
        return [f"{key}: {value}" for key, value in attributes.items()]
    if isinstance(attributes, list):
        return [str(value) for value in attributes]
    return []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
