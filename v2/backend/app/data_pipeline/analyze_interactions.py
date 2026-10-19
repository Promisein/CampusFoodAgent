import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


REQUIRED_INTERACTION_FIELDS = (
    "interaction_id",
    "user_id",
    "business_id",
    "event_type",
    "event_time",
    "rating",
    "review_text",
    "source",
)


def analyze_interactions(
    interactions_path: Path,
    valid_business_ids: set[str],
) -> dict:
    user_counts: Counter[str] = Counter()
    business_ids: set[str] = set()
    seen_interaction_ids: set[str] = set()
    missing_fields: Counter[str] = Counter()
    duplicate_interaction_ids = 0
    invalid_event_times = 0
    unknown_business_ids = 0
    rows = 0
    date_min: datetime | None = None
    date_max: datetime | None = None

    with Path(interactions_path).open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1

            for field in REQUIRED_INTERACTION_FIELDS:
                if row.get(field) is None:
                    missing_fields[field] += 1

            interaction_id = row.get("interaction_id")
            if interaction_id is not None:
                if interaction_id in seen_interaction_ids:
                    duplicate_interaction_ids += 1
                seen_interaction_ids.add(interaction_id)

            user_id = row.get("user_id")
            if user_id is not None:
                user_counts[user_id] += 1

            business_id = row.get("business_id")
            if business_id is not None:
                business_ids.add(business_id)
                if business_id not in valid_business_ids:
                    unknown_business_ids += 1

            try:
                event_time = datetime.fromisoformat(row.get("event_time", ""))
            except (TypeError, ValueError):
                invalid_event_times += 1
            else:
                date_min = event_time if date_min is None or event_time < date_min else date_min
                date_max = event_time if date_max is None or event_time > date_max else date_max

    interaction_counts = sorted(user_counts.values())
    cohorts = {
        "cold": [count for count in interaction_counts if count == 1],
        "sparse": [count for count in interaction_counts if 2 <= count <= 4],
        "warm": [count for count in interaction_counts if count >= 5],
    }

    return {
        "rows": rows,
        "users": len(user_counts),
        "businesses": len(business_ids),
        "date_min": _format_datetime(date_min),
        "date_max": _format_datetime(date_max),
        "interactions_per_user": {
            "min": interaction_counts[0] if interaction_counts else None,
            "p50": _percentile(interaction_counts, 0.50),
            "p75": _percentile(interaction_counts, 0.75),
            "p90": _percentile(interaction_counts, 0.90),
            "p95": _percentile(interaction_counts, 0.95),
            "max": interaction_counts[-1] if interaction_counts else None,
        },
        "user_cohorts": {
            name: {"users": len(values), "interactions": sum(values)}
            for name, values in cohorts.items()
        },
        "missing_fields": dict(sorted(missing_fields.items())),
        "duplicate_interaction_ids": duplicate_interaction_ids,
        "invalid_event_times": invalid_event_times,
        "unknown_business_ids": unknown_business_ids,
    }


def write_interaction_statistics(statistics: dict, output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(statistics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit processed Yelp interactions.")
    parser.add_argument("--interactions", type=Path, required=True)
    parser.add_argument("--businesses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    valid_business_ids = _load_business_ids(args.businesses)
    statistics = analyze_interactions(args.interactions, valid_business_ids)
    write_interaction_statistics(statistics, args.output)
    return 0


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    return values[round((len(values) - 1) * fraction)]


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ") if value is not None else None


def _load_business_ids(path: Path) -> set[str]:
    with Path(path).open(encoding="utf-8") as f:
        return {
            row["business_id"]
            for line in f
            if line.strip()
            for row in [json.loads(line)]
        }


if __name__ == "__main__":
    raise SystemExit(main())
