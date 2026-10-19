import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path


EARTH_RADIUS_KM = 6371.0088


def build_profile_snapshots(
    split_dir: Path,
    businesses_path: Path,
    output_dir: Path,
    *,
    profile_version: str = "profile_v1",
) -> dict:
    split_dir = Path(split_dir)
    split_manifest = json.loads(
        (split_dir / "split_manifest.json").read_text(encoding="utf-8")
    )
    businesses = _load_businesses(businesses_path)
    train_by_user = _group_by_user(_load_jsonl(split_dir / "train_interactions.jsonl"))
    validation_by_user = _single_target_by_user(
        _load_jsonl(split_dir / "validation_interactions.jsonl"),
        "validation",
    )
    test_by_user = _single_target_by_user(
        _load_jsonl(split_dir / "test_interactions.jsonl"),
        "test",
    )

    if validation_by_user.keys() != test_by_user.keys():
        raise ValueError("Validation and test user sets must match")

    profiles: list[dict] = []
    for user_id in sorted(validation_by_user):
        train_history = sorted(train_by_user[user_id], key=_interaction_sort_key)
        validation_target = validation_by_user[user_id]
        test_target = test_by_user[user_id]
        profiles.append(
            _build_profile(
                user_id,
                "validation",
                validation_target,
                train_history,
                businesses,
                split_manifest,
                profile_version,
            )
        )
        profiles.append(
            _build_profile(
                user_id,
                "test",
                test_target,
                sorted([*train_history, validation_target], key=_interaction_sort_key),
                businesses,
                split_manifest,
                profile_version,
            )
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "user_profile_snapshots.jsonl", profiles)
    manifest = {
        "profile_version": profile_version,
        "source_split_version": split_manifest["split_version"],
        "source_data_version": split_manifest["source_data_version"],
        "created_date": date.today().isoformat(),
        "profile_count": len(profiles),
        "warm_user_count": len(validation_by_user),
        "validation_profile_count": sum(
            profile["target_split"] == "validation" for profile in profiles
        ),
        "test_profile_count": sum(profile["target_split"] == "test" for profile in profiles),
        "category_limit": 10,
        "recent_item_limit": 5,
        "positive_rating_threshold": 4,
        "missing_price_policy": "exclude from price average and count as unknown",
        "geo_policy": "mean historical coordinates and p75 Haversine radius",
        "outputs": {"profiles": "user_profile_snapshots.jsonl"},
    }
    _write_json(output_dir / "profile_manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build leakage-safe Yelp user profiles.")
    parser.add_argument("--split-dir", type=Path, required=True)
    parser.add_argument("--businesses", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile-version", default="profile_v1")
    args = parser.parse_args(argv)
    build_profile_snapshots(
        args.split_dir,
        args.businesses,
        args.output_dir,
        profile_version=args.profile_version,
    )
    return 0


def _build_profile(
    user_id: str,
    target_split: str,
    target: dict,
    history: list[dict],
    businesses: dict[str, dict],
    split_manifest: dict,
    profile_version: str,
) -> dict:
    target_key = _interaction_sort_key(target)
    if any(_interaction_sort_key(interaction) >= target_key for interaction in history):
        raise ValueError(f"Profile history is not before {target_split} target for user {user_id}")

    business_history: list[tuple[dict, dict]] = []
    for interaction in history:
        business_id = interaction["business_id"]
        if business_id not in businesses:
            raise ValueError(f"Unknown business_id in profile history: {business_id}")
        business_history.append((interaction, businesses[business_id]))

    ratings = [float(interaction["rating"]) for interaction, _ in business_history]
    known_prices = [
        int(business["price_level"])
        for _, business in business_history
        if business.get("price_level") is not None
    ]
    category_preferences = _category_preferences(business_history)
    coordinates = [
        (float(business["latitude"]), float(business["longitude"]))
        for _, business in business_history
        if business.get("latitude") is not None and business.get("longitude") is not None
    ]
    geo_center, geo_radius = _geo_features(coordinates)
    recent_history = history[-5:]

    profile_key = "|".join(
        [
            user_id,
            target_split,
            target["event_time"],
            target["interaction_id"],
            profile_version,
        ]
    )
    return {
        "profile_id": hashlib.sha256(profile_key.encode("utf-8")).hexdigest()[:24],
        "user_id": user_id,
        "target_split": target_split,
        "as_of_time": target["event_time"],
        "cutoff_interaction_id": target["interaction_id"],
        "history_count": len(history),
        "history_start_time": history[0]["event_time"] if history else None,
        "history_end_time": history[-1]["event_time"] if history else None,
        "category_preferences": category_preferences[:10],
        "price_distribution": {
            str(level): count for level, count in sorted(Counter(known_prices).items())
        },
        "mean_price_level": _mean(known_prices),
        "known_price_count": len(known_prices),
        "unknown_price_count": len(history) - len(known_prices),
        "mean_rating": _mean(ratings),
        "positive_rating_ratio": (
            round(sum(rating >= 4 for rating in ratings) / len(ratings), 4) if ratings else None
        ),
        "geo_center": geo_center,
        "geo_radius_p75_km": geo_radius,
        "recent_interaction_ids": [row["interaction_id"] for row in recent_history],
        "recent_business_ids": [row["business_id"] for row in recent_history],
        "recent_categories": _recent_categories(recent_history, businesses),
        "source_data_version": split_manifest["source_data_version"],
        "split_version": split_manifest["split_version"],
        "profile_version": profile_version,
    }


def _category_preferences(business_history: list[tuple[dict, dict]]) -> list[dict]:
    ratings_by_category: dict[str, list[float]] = defaultdict(list)
    for interaction, business in business_history:
        for category in business.get("categories_normalized", []):
            ratings_by_category[category].append(float(interaction["rating"]))
    preferences = [
        {
            "category": category,
            "interaction_count": len(ratings),
            "mean_rating": _mean(ratings),
        }
        for category, ratings in ratings_by_category.items()
    ]
    preferences.sort(
        key=lambda item: (
            -item["interaction_count"],
            -item["mean_rating"],
            item["category"],
        )
    )
    return preferences


def _recent_categories(history: list[dict], businesses: dict[str, dict]) -> list[str]:
    recent: list[str] = []
    for interaction in reversed(history):
        for category in businesses[interaction["business_id"]].get("categories_normalized", []):
            if category not in recent:
                recent.append(category)
            if len(recent) == 5:
                return recent
    return recent


def _geo_features(
    coordinates: list[tuple[float, float]],
) -> tuple[dict | None, float | None]:
    if not coordinates:
        return None, None
    latitude = sum(point[0] for point in coordinates) / len(coordinates)
    longitude = sum(point[1] for point in coordinates) / len(coordinates)
    distances = sorted(
        _haversine_km(latitude, longitude, point[0], point[1]) for point in coordinates
    )
    p75 = distances[round((len(distances) - 1) * 0.75)]
    return (
        {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "valid_coordinate_count": len(coordinates),
        },
        round(p75, 4),
    )


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


def _mean(values: list[float] | list[int]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _interaction_sort_key(row: dict) -> tuple[datetime, str]:
    return datetime.fromisoformat(row["event_time"]), row["interaction_id"]


def _load_businesses(path: Path) -> dict[str, dict]:
    return {row["business_id"]: row for row in _load_jsonl(path)}


def _group_by_user(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["user_id"]].append(row)
    return grouped


def _single_target_by_user(rows: list[dict], target_split: str) -> dict[str, dict]:
    targets: dict[str, dict] = {}
    for row in rows:
        user_id = row["user_id"]
        if user_id in targets:
            raise ValueError(f"Multiple {target_split} targets for user {user_id}")
        targets[user_id] = row
    return targets


def _load_jsonl(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
