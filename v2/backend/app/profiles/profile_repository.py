import json
from pathlib import Path


MANIFEST_REQUIRED_FIELDS = (
    "profile_version",
    "source_split_version",
    "source_data_version",
    "profile_count",
    "warm_user_count",
    "validation_profile_count",
    "test_profile_count",
    "outputs",
)

PROFILE_REQUIRED_FIELDS = (
    "profile_id",
    "user_id",
    "target_split",
    "as_of_time",
    "cutoff_interaction_id",
    "history_count",
    "history_start_time",
    "history_end_time",
    "category_preferences",
    "price_distribution",
    "mean_price_level",
    "known_price_count",
    "unknown_price_count",
    "mean_rating",
    "positive_rating_ratio",
    "geo_center",
    "geo_radius_p75_km",
    "recent_interaction_ids",
    "recent_business_ids",
    "recent_categories",
    "source_data_version",
    "split_version",
    "profile_version",
)


class UserProfileRepository:
    def __init__(self, profile_dir: Path):
        self.profile_dir = Path(profile_dir)
        self._manifest: dict | None = None
        self._profiles: list[dict] | None = None
        self._profile_index: dict[tuple[str, str], dict] | None = None

    def load_manifest(self) -> dict:
        if self._manifest is not None:
            return self._manifest
        path = self._require_file("profile_manifest.json")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        _require_fields(manifest, MANIFEST_REQUIRED_FIELDS, path.name)
        self._manifest = manifest
        return manifest

    def load_profiles(self) -> list[dict]:
        if self._profiles is not None:
            return self._profiles
        manifest = self.load_manifest()
        filename = manifest["outputs"]["profiles"]
        path = self._require_file(filename)
        profiles: list[dict] = []
        profile_index: dict[tuple[str, str], dict] = {}
        with path.open(encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                profile = json.loads(line)
                _require_fields(
                    profile,
                    PROFILE_REQUIRED_FIELDS,
                    f"{path.name} line {line_number}",
                )
                key = (profile["user_id"], profile["target_split"])
                if key in profile_index:
                    raise ValueError(f"Duplicate profile key: {key[0]}/{key[1]}")
                profile_index[key] = profile
                profiles.append(profile)
        self._profiles = profiles
        self._profile_index = profile_index
        return profiles

    def get_profile(self, user_id: str, target_split: str) -> dict | None:
        self.load_profiles()
        assert self._profile_index is not None
        return self._profile_index.get((user_id, target_split))

    def _require_file(self, filename: str) -> Path:
        path = self.profile_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required profile file not found: {path}")
        return path


def _require_fields(value: dict, fields: tuple[str, ...], source: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ValueError(f"{source} missing required fields: {', '.join(missing)}")
