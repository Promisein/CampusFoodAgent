import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RESTAURANT_TERMS = ("Restaurants", "Food", "Coffee", "Bars")
BUSINESS_FILE = "yelp_academic_dataset_business.json"
REVIEW_FILE = "yelp_academic_dataset_review.json"
RETAINED_RAW_SOURCES = [BUSINESS_FILE, REVIEW_FILE]
EXCLUDED_RAW_SOURCES = {
    "yelp_academic_dataset_user.json": (
        "not needed for the first runnable agent; user histories are derived from review interactions"
    ),
    "yelp_academic_dataset_checkin.json": "deferred to a later heat and active-time feature pass",
    "yelp_academic_dataset_tip.json": (
        "optional RAG short-text evidence, excluded from the first reproducible curation"
    ),
}


@dataclass(frozen=True)
class YelpCurationConfig:
    archive_dir: Path
    output_dir: Path
    city: str | None = None
    state: str | None = None
    max_reviews_total: int = 200_000
    max_reviews_per_business: int = 50
    representative_reviews_per_business: int = 10
    restaurant_terms: tuple[str, ...] = RESTAURANT_TERMS


def curate_yelp_dataset(config: YelpCurationConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    business_path = config.archive_dir / BUSINESS_FILE
    review_path = config.archive_dir / REVIEW_FILE
    _require_file(business_path)
    _require_file(review_path)

    city_stats, business_rows, discarded = _scan_businesses(config, business_path)
    selected_city = _resolve_selected_city(config, city_stats)
    selected_businesses = [
        _normalize_business(row)
        for row in business_rows
        if _city_key(row) == selected_city
    ]
    selected_business_ids = {row["business_id"] for row in selected_businesses}

    discarded["businesses_outside_selected_city"] = (
        sum(stats["restaurant_or_food_businesses"] for key, stats in city_stats.items() if key != selected_city)
    )

    _write_json(config.output_dir / "city_statistics.json", _serialize_city_stats(city_stats))
    _write_jsonl(config.output_dir / "businesses.jsonl", selected_businesses)

    review_result = _write_reviews(config, review_path, selected_business_ids)

    manifest = {
        "data_version": "yelp_open_dataset_local",
        "selected_city": {"city": selected_city[0], "state": selected_city[1]},
        "selection_policy": {
            "city": (
                "auto-selected by open restaurant/food business count, then open review count"
                if config.city is None
                else "explicitly requested by config"
            ),
            "businesses": "retain restaurant/food businesses in the selected city; keep is_open for downstream hard filtering",
            "reviews": "retain only reviews for selected businesses, capped by total and per-business limits",
            "representative_reviews": "keep the most useful retained reviews per business for first-pass RAG evidence",
        },
        "limits": {
            "max_reviews_total": config.max_reviews_total,
            "max_reviews_per_business": config.max_reviews_per_business,
            "representative_reviews_per_business": config.representative_reviews_per_business,
        },
        "kept": {
            "businesses": len(selected_businesses),
            "open_businesses": sum(1 for row in selected_businesses if row["is_open"]),
            "closed_businesses": sum(1 for row in selected_businesses if not row["is_open"]),
            "reviews_as_interactions": review_result["kept_interactions"],
            "representative_reviews": review_result["kept_representative_reviews"],
        },
        "discarded": {
            **discarded,
            **review_result["discarded"],
        },
        "retained_raw_sources": RETAINED_RAW_SOURCES,
        "excluded_raw_sources": EXCLUDED_RAW_SOURCES,
        "outputs": {
            "businesses": "businesses.jsonl",
            "interactions": "interactions.jsonl",
            "representative_reviews": "representative_reviews.jsonl",
            "city_statistics": "city_statistics.json",
            "manifest": "data_manifest.json",
        },
    }
    _write_json(config.output_dir / "data_manifest.json", manifest)
    return manifest


def _scan_businesses(
    config: YelpCurationConfig, business_path: Path
) -> tuple[dict[tuple[str, str], dict[str, int]], list[dict[str, Any]], dict[str, int]]:
    city_stats: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {
            "restaurant_or_food_businesses": 0,
            "open_restaurant_or_food_businesses": 0,
            "review_count": 0,
            "open_review_count": 0,
        }
    )
    business_rows: list[dict[str, Any]] = []
    discarded = {
        "non_restaurant_or_non_food_businesses": 0,
        "businesses_with_missing_required_fields": 0,
    }

    for row in _iter_jsonl(business_path):
        if not _has_required_business_fields(row):
            discarded["businesses_with_missing_required_fields"] += 1
            continue
        if not _is_restaurant_or_food(row.get("categories"), config.restaurant_terms):
            discarded["non_restaurant_or_non_food_businesses"] += 1
            continue

        key = _city_key(row)
        review_count = int(row.get("review_count") or 0)
        is_open = int(row.get("is_open") or 0) == 1
        city_stats[key]["restaurant_or_food_businesses"] += 1
        city_stats[key]["review_count"] += review_count
        if is_open:
            city_stats[key]["open_restaurant_or_food_businesses"] += 1
            city_stats[key]["open_review_count"] += review_count
        business_rows.append(row)

    return dict(city_stats), business_rows, discarded


def _resolve_selected_city(
    config: YelpCurationConfig, city_stats: dict[tuple[str, str], dict[str, int]]
) -> tuple[str, str]:
    if config.city is not None:
        key = (config.city, config.state or "")
        if key in city_stats:
            return key
        matches = [city_key for city_key in city_stats if city_key[0].lower() == config.city.lower()]
        if config.state:
            matches = [city_key for city_key in matches if city_key[1].lower() == config.state.lower()]
        if matches:
            return sorted(
                matches,
                key=lambda item: (
                    city_stats[item]["open_restaurant_or_food_businesses"],
                    city_stats[item]["open_review_count"],
                ),
                reverse=True,
            )[0]
        raise ValueError(f"Selected city was not found in restaurant/food businesses: {config.city}, {config.state}")

    if not city_stats:
        raise ValueError("No restaurant/food businesses found in Yelp business file")
    return sorted(
        city_stats,
        key=lambda item: (
            city_stats[item]["open_restaurant_or_food_businesses"],
            city_stats[item]["open_review_count"],
        ),
        reverse=True,
    )[0]


def _write_reviews(config: YelpCurationConfig, review_path: Path, selected_business_ids: set[str]) -> dict[str, Any]:
    per_business_counts: Counter[str] = Counter()
    kept_interactions = 0
    reviews_outside_selected_businesses = 0
    reviews_over_limits = 0
    representative_reviews: dict[str, list[dict[str, Any]]] = defaultdict(list)

    interactions_path = config.output_dir / "interactions.jsonl"
    with interactions_path.open("w", encoding="utf-8") as out:
        for row in _iter_jsonl(review_path):
            business_id = row.get("business_id")
            if business_id not in selected_business_ids:
                reviews_outside_selected_businesses += 1
                continue
            if kept_interactions >= config.max_reviews_total:
                reviews_over_limits += 1
                continue
            if per_business_counts[business_id] >= config.max_reviews_per_business:
                reviews_over_limits += 1
                continue

            interaction = _review_to_interaction(row)
            out.write(json.dumps(interaction, ensure_ascii=False) + "\n")
            kept_interactions += 1
            per_business_counts[business_id] += 1
            _add_representative_review(
                representative_reviews[business_id],
                row,
                config.representative_reviews_per_business,
            )

    flattened_reviews = [
        review
        for reviews in representative_reviews.values()
        for review in sorted(reviews, key=_review_rank, reverse=True)
    ]
    _write_jsonl(config.output_dir / "representative_reviews.jsonl", flattened_reviews)
    return {
        "kept_interactions": kept_interactions,
        "kept_representative_reviews": len(flattened_reviews),
        "discarded": {
            "reviews_outside_selected_businesses": reviews_outside_selected_businesses,
            "reviews_over_limits": reviews_over_limits,
        },
    }


def _add_representative_review(target: list[dict[str, Any]], row: dict[str, Any], limit: int) -> None:
    if limit <= 0:
        return
    candidate = {
        "review_id": row["review_id"],
        "business_id": row["business_id"],
        "user_id": row.get("user_id"),
        "rating": float(row.get("stars") or 0),
        "review_date": row.get("date"),
        "useful": int(row.get("useful") or 0),
        "text": row.get("text") or "",
        "source": "yelp_review",
    }
    target.append(candidate)
    target.sort(key=_review_rank, reverse=True)
    del target[limit:]


def _review_rank(row: dict[str, Any]) -> tuple[int, float, str]:
    return (int(row.get("useful") or 0), float(row.get("rating") or row.get("stars") or 0), row.get("review_date") or "")


def _review_to_interaction(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "interaction_id": row["review_id"],
        "user_id": row["user_id"],
        "business_id": row["business_id"],
        "event_type": "review",
        "event_time": row.get("date"),
        "rating": float(row.get("stars") or 0),
        "review_text": row.get("text") or "",
        "source": "yelp_review",
    }


def _normalize_business(row: dict[str, Any]) -> dict[str, Any]:
    attributes = row.get("attributes") or {}
    return {
        "business_id": row["business_id"],
        "name": row["name"],
        "categories_raw": row.get("categories") or "",
        "categories_normalized": _normalize_categories(row.get("categories") or ""),
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "city": row["city"],
        "state": row["state"],
        "stars": float(row.get("stars") or 0),
        "review_count": int(row.get("review_count") or 0),
        "price_level": _parse_price_level(attributes),
        "hours": row.get("hours") or {},
        "attributes": attributes,
        "is_open": int(row.get("is_open") or 0) == 1,
        "data_version": "yelp_open_dataset_local",
    }


def _normalize_categories(categories: str) -> list[str]:
    return [category.strip() for category in categories.split(",") if category.strip()]


def _parse_price_level(attributes: dict[str, Any]) -> int | None:
    raw_value = attributes.get("RestaurantsPriceRange2") if isinstance(attributes, dict) else None
    try:
        price = int(raw_value)
    except (TypeError, ValueError):
        return None
    return price if 1 <= price <= 4 else None


def _is_restaurant_or_food(categories: str | None, restaurant_terms: tuple[str, ...]) -> bool:
    if not categories:
        return False
    return any(term in categories for term in restaurant_terms)


def _has_required_business_fields(row: dict[str, Any]) -> bool:
    required = ("business_id", "name", "city", "state", "latitude", "longitude", "categories")
    return all(row.get(field) not in (None, "") for field in required)


def _city_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("city") or "").strip(), str(row.get("state") or "").strip())


def _serialize_city_stats(city_stats: dict[tuple[str, str], dict[str, int]]) -> list[dict[str, Any]]:
    rows = [
        {
            "city": city,
            "state": state,
            **stats,
        }
        for (city, state), stats in city_stats.items()
    ]
    return sorted(
        rows,
        key=lambda row: (row["open_restaurant_or_food_businesses"], row["open_review_count"]),
        reverse=True,
    )


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_number}: {exc}") from exc


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Required Yelp source file not found: {path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Curate a local Yelp subset for CampusFoodAgent v2.")
    parser.add_argument("--archive-dir", type=Path, default=Path("data/archive"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--city", default=None)
    parser.add_argument("--state", default=None)
    parser.add_argument("--max-reviews-total", type=int, default=200_000)
    parser.add_argument("--max-reviews-per-business", type=int, default=50)
    parser.add_argument("--representative-reviews-per-business", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest = curate_yelp_dataset(
        YelpCurationConfig(
            archive_dir=args.archive_dir,
            output_dir=args.output_dir,
            city=args.city,
            state=args.state,
            max_reviews_total=args.max_reviews_total,
            max_reviews_per_business=args.max_reviews_per_business,
            representative_reviews_per_business=args.representative_reviews_per_business,
        )
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
