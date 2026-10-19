import json
from pathlib import Path

from app.profiles.build_profiles import build_profile_snapshots, main


def _business(
    business_id: str,
    *,
    categories: list[str],
    price_level: int | None,
    latitude: float,
    longitude: float,
) -> dict:
    return {
        "business_id": business_id,
        "name": business_id,
        "categories_raw": ", ".join(categories),
        "categories_normalized": categories,
        "latitude": latitude,
        "longitude": longitude,
        "city": "Tampa",
        "state": "FL",
        "stars": 4.0,
        "review_count": 10,
        "price_level": price_level,
        "hours": {},
        "attributes": {},
        "is_open": True,
        "data_version": "test-data",
    }


def _interaction(
    interaction_id: str,
    business_id: str,
    event_time: str,
    rating: float,
    *,
    user_id: str = "user-1",
) -> dict:
    return {
        "interaction_id": interaction_id,
        "user_id": user_id,
        "business_id": business_id,
        "event_type": "review",
        "event_time": event_time,
        "rating": rating,
        "review_text": "Review text.",
        "source": "yelp_review",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _prepare_split(tmp_path: Path) -> tuple[Path, Path]:
    split_dir = tmp_path / "split"
    businesses_path = tmp_path / "businesses.jsonl"
    businesses = [
        _business("b1", categories=["Coffee & Tea"], price_level=1, latitude=27.94, longitude=-82.46),
        _business(
            "b2",
            categories=["Coffee & Tea", "Bakeries"],
            price_level=2,
            latitude=27.95,
            longitude=-82.45,
        ),
        _business("b3", categories=["Bakeries"], price_level=None, latitude=27.96, longitude=-82.44),
        _business("b4", categories=["Breakfast & Brunch"], price_level=2, latitude=27.97, longitude=-82.43),
        _business("b5", categories=["Restaurants"], price_level=3, latitude=27.98, longitude=-82.42),
    ]
    train = [
        _interaction("i1", "b1", "2020-01-01 00:00:00", 5.0),
        _interaction("i2", "b2", "2020-02-01 00:00:00", 4.0),
        _interaction("i3", "b3", "2020-03-01 00:00:00", 3.0),
    ]
    validation = [_interaction("i4", "b4", "2020-04-01 00:00:00", 5.0)]
    test = [_interaction("i5", "b5", "2020-05-01 00:00:00", 2.0)]
    _write_jsonl(businesses_path, businesses)
    _write_jsonl(split_dir / "train_interactions.jsonl", train)
    _write_jsonl(split_dir / "validation_interactions.jsonl", validation)
    _write_jsonl(split_dir / "test_interactions.jsonl", test)
    (split_dir / "split_manifest.json").write_text(
        json.dumps(
            {
                "split_version": "time_split_v1",
                "source_data_version": "test-data",
                "user_counts": {"warm": 1},
            }
        ),
        encoding="utf-8",
    )
    return split_dir, businesses_path


def _load_profiles(output_dir: Path) -> list[dict]:
    with (output_dir / "user_profile_snapshots.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_profiles_use_only_history_before_each_target(tmp_path):
    split_dir, businesses_path = _prepare_split(tmp_path)
    output_dir = tmp_path / "profiles"

    manifest = build_profile_snapshots(split_dir, businesses_path, output_dir)

    profiles = {profile["target_split"]: profile for profile in _load_profiles(output_dir)}
    assert profiles["validation"]["history_count"] == 3
    assert profiles["validation"]["recent_interaction_ids"] == ["i1", "i2", "i3"]
    assert profiles["validation"]["as_of_time"] == "2020-04-01 00:00:00"
    assert profiles["test"]["history_count"] == 4
    assert profiles["test"]["recent_interaction_ids"] == ["i1", "i2", "i3", "i4"]
    assert "i5" not in profiles["test"]["recent_interaction_ids"]
    assert manifest["profile_count"] == 2


def test_profile_features_are_explainable_and_handle_missing_price(tmp_path):
    split_dir, businesses_path = _prepare_split(tmp_path)
    output_dir = tmp_path / "profiles"

    build_profile_snapshots(split_dir, businesses_path, output_dir)

    validation = next(
        profile for profile in _load_profiles(output_dir) if profile["target_split"] == "validation"
    )
    assert validation["category_preferences"][:2] == [
        {"category": "Coffee & Tea", "interaction_count": 2, "mean_rating": 4.5},
        {"category": "Bakeries", "interaction_count": 2, "mean_rating": 3.5},
    ]
    assert validation["price_distribution"] == {"1": 1, "2": 1}
    assert validation["known_price_count"] == 2
    assert validation["unknown_price_count"] == 1
    assert validation["mean_price_level"] == 1.5
    assert validation["mean_rating"] == 4.0
    assert validation["positive_rating_ratio"] == 0.6667
    assert validation["geo_center"] == {
        "latitude": 27.95,
        "longitude": -82.45,
        "valid_coordinate_count": 3,
    }
    assert validation["geo_radius_p75_km"] > 0


def test_profile_ids_and_output_are_deterministic(tmp_path):
    split_dir, businesses_path = _prepare_split(tmp_path)
    first_output = tmp_path / "first-profiles"
    second_output = tmp_path / "second-profiles"

    first_manifest = build_profile_snapshots(split_dir, businesses_path, first_output)
    second_manifest = build_profile_snapshots(split_dir, businesses_path, second_output)

    assert (first_output / "user_profile_snapshots.jsonl").read_text(encoding="utf-8") == (
        second_output / "user_profile_snapshots.jsonl"
    ).read_text(encoding="utf-8")
    assert first_manifest == second_manifest
    assert first_manifest["validation_profile_count"] == 1
    assert first_manifest["test_profile_count"] == 1


def test_cli_builds_profile_artifacts(tmp_path):
    split_dir, businesses_path = _prepare_split(tmp_path)
    output_dir = tmp_path / "profiles"

    exit_code = main(
        [
            "--split-dir",
            str(split_dir),
            "--businesses",
            str(businesses_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "profile_manifest.json").is_file()
    assert (output_dir / "user_profile_snapshots.jsonl").is_file()
