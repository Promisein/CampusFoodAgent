import json
from pathlib import Path

import pytest

from app.profiles.profile_repository import UserProfileRepository


def _profile(
    profile_id: str = "profile-1",
    *,
    user_id: str = "user-1",
    target_split: str = "validation",
) -> dict:
    return {
        "profile_id": profile_id,
        "user_id": user_id,
        "target_split": target_split,
        "as_of_time": "2021-01-04 00:00:00",
        "cutoff_interaction_id": "target-1",
        "history_count": 3,
        "history_start_time": "2021-01-01 00:00:00",
        "history_end_time": "2021-01-03 00:00:00",
        "category_preferences": [],
        "price_distribution": {},
        "mean_price_level": None,
        "known_price_count": 0,
        "unknown_price_count": 3,
        "mean_rating": 4.0,
        "positive_rating_ratio": 0.6667,
        "geo_center": None,
        "geo_radius_p75_km": None,
        "recent_interaction_ids": ["i1", "i2", "i3"],
        "recent_business_ids": ["b1", "b2", "b3"],
        "recent_categories": [],
        "source_data_version": "test-data",
        "split_version": "time_split_v1",
        "profile_version": "profile_v1",
    }


def _write_repository(profile_dir: Path, profiles: list[dict]) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "profile_manifest.json").write_text(
        json.dumps(
            {
                "profile_version": "profile_v1",
                "source_split_version": "time_split_v1",
                "source_data_version": "test-data",
                "profile_count": len(profiles),
                "warm_user_count": len({profile["user_id"] for profile in profiles}),
                "validation_profile_count": sum(
                    profile["target_split"] == "validation" for profile in profiles
                ),
                "test_profile_count": sum(
                    profile["target_split"] == "test" for profile in profiles
                ),
                "outputs": {"profiles": "user_profile_snapshots.jsonl"},
            }
        ),
        encoding="utf-8",
    )
    (profile_dir / "user_profile_snapshots.jsonl").write_text(
        "".join(json.dumps(profile) + "\n" for profile in profiles),
        encoding="utf-8",
    )


def test_repository_loads_caches_and_queries_profiles(tmp_path):
    profiles = [
        _profile(),
        _profile("profile-2", target_split="test"),
    ]
    _write_repository(tmp_path, profiles)
    repository = UserProfileRepository(tmp_path)

    manifest = repository.load_manifest()
    loaded = repository.load_profiles()

    assert manifest["profile_count"] == 2
    assert loaded is repository.load_profiles()
    assert manifest is repository.load_manifest()
    assert repository.get_profile("user-1", "validation")["profile_id"] == "profile-1"
    assert repository.get_profile("unknown", "validation") is None


def test_repository_reports_missing_profile_file(tmp_path):
    _write_repository(tmp_path, [])
    (tmp_path / "user_profile_snapshots.jsonl").unlink()
    repository = UserProfileRepository(tmp_path)

    with pytest.raises(FileNotFoundError, match="user_profile_snapshots.jsonl"):
        repository.load_profiles()


def test_repository_rejects_profile_missing_required_field(tmp_path):
    invalid_profile = _profile()
    invalid_profile.pop("as_of_time")
    _write_repository(tmp_path, [invalid_profile])

    with pytest.raises(ValueError, match="as_of_time"):
        UserProfileRepository(tmp_path).load_profiles()


def test_repository_rejects_duplicate_user_and_split(tmp_path):
    _write_repository(
        tmp_path,
        [
            _profile("profile-1"),
            _profile("profile-2"),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate profile key: user-1/validation"):
        UserProfileRepository(tmp_path).load_profiles()
