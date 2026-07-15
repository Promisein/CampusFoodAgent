import json
from collections import defaultdict
from pathlib import Path

BUSINESS_REQUIRED_FIELDS = (
    "business_id",
    "name",
    "categories_raw",
    "categories_normalized",
    "latitude",
    "longitude",
    "city",
    "state",
    "stars",
    "review_count",
    "price_level",
    "hours",
    "attributes",
    "is_open",
    "data_version",
)
REPRESENTATIVE_REVIEW_REQUIRED_FIELDS = (
    "review_id",
    "business_id",
    "user_id",
    "rating",
    "review_date",
    "useful",
    "text",
    "source",
)
MANIFEST_REQUIRED_FIELDS = ("data_version", "selected_city", "kept")


class ProcessedDatasetRepository:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._manifest: dict | None = None
        self._businesses: list[dict] | None = None
        self._reviews_by_business: dict[str, list[dict]] | None = None

    def load_manifest(self) -> dict:
        if self._manifest is not None:
            return self._manifest
        path = self._require_file("data_manifest.json")
        with path.open(encoding="utf-8") as f:
            manifest = json.load(f)
        missing_fields = [field for field in MANIFEST_REQUIRED_FIELDS if field not in manifest]
        if missing_fields:
            raise ValueError(
                f"{path.name} is missing required fields: " + ", ".join(missing_fields)
            )
        self._manifest = manifest
        return self._manifest

    def load_businesses(self) -> list[dict]:
        if self._businesses is None:
            self._businesses = self._load_jsonl(
                self._require_file("businesses.jsonl"),
                required_fields=BUSINESS_REQUIRED_FIELDS,
            )
        return self._businesses

    def load_representative_reviews_by_business(self) -> dict[str, list[dict]]:
        if self._reviews_by_business is not None:
            return self._reviews_by_business
        grouped: dict[str, list[dict]] = defaultdict(list)
        path = self._require_file("representative_reviews.jsonl")
        for review in self._load_jsonl(
            path,
            required_fields=REPRESENTATIVE_REVIEW_REQUIRED_FIELDS,
        ):
            grouped[review["business_id"]].append(review)
        self._reviews_by_business = dict(grouped)
        return self._reviews_by_business

    def _require_file(self, filename: str) -> Path:
        path = self.data_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required processed dataset file is missing: {path}")
        return path

    @staticmethod
    def _load_jsonl(path: Path, required_fields: tuple[str, ...] = ()) -> list[dict]:
        with path.open(encoding="utf-8") as f:
            rows = []
            for line_number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                missing_fields = [field for field in required_fields if field not in row]
                if missing_fields:
                    raise ValueError(
                        f"{path.name} line {line_number} is missing required fields: "
                        + ", ".join(missing_fields)
                    )
                rows.append(row)
            return rows
