import argparse
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


OUTPUT_FILES = {
    "train": "train_interactions.jsonl",
    "validation": "validation_interactions.jsonl",
    "test": "test_interactions.jsonl",
    "cold_start": "cold_start_interactions.jsonl",
}


def split_interactions(
    interactions_path: Path,
    output_dir: Path,
    *,
    min_warm_interactions: int = 5,
    source_data_version: str,
) -> dict:
    interactions_by_user: dict[str, list[dict]] = defaultdict(list)
    seen_interaction_ids: set[str] = set()
    with Path(interactions_path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                interaction_id = row["interaction_id"]
                if interaction_id in seen_interaction_ids:
                    raise ValueError(f"Duplicate interaction_id: {interaction_id}")
                seen_interaction_ids.add(interaction_id)
                interactions_by_user[row["user_id"]].append(row)

    split_rows: dict[str, list[dict]] = {name: [] for name in OUTPUT_FILES}
    user_counts = {"warm": 0, "sparse": 0, "cold": 0}

    for user_id in sorted(interactions_by_user):
        ordered = sorted(interactions_by_user[user_id], key=_interaction_sort_key)
        if len(ordered) >= min_warm_interactions:
            user_counts["warm"] += 1
            split_rows["train"].extend(ordered[:-2])
            split_rows["validation"].append(ordered[-2])
            split_rows["test"].append(ordered[-1])
            continue

        cohort = "cold" if len(ordered) == 1 else "sparse"
        user_counts[cohort] += 1
        split_rows["cold_start"].extend(
            {**row, "user_cohort": cohort} for row in ordered
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for split_name, filename in OUTPUT_FILES.items():
        _write_jsonl(output_dir / filename, split_rows[split_name])

    counts = {name: len(rows) for name, rows in split_rows.items()}
    counts["total"] = sum(counts.values())
    manifest = {
        "split_version": "time_split_v1",
        "source_data_version": source_data_version,
        "created_date": date.today().isoformat(),
        "sorting_key": ["event_time", "interaction_id"],
        "min_warm_interactions": min_warm_interactions,
        "policy": "per-user leave-two-out: last=test, penultimate=validation, earlier=train",
        "counts": counts,
        "user_counts": {**user_counts, "total": sum(user_counts.values())},
        "outputs": OUTPUT_FILES,
    }
    _write_json(output_dir / "split_manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a per-user chronological Yelp split.")
    parser.add_argument("--interactions", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-warm-interactions", type=int, default=5)
    args = parser.parse_args(argv)

    source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    split_interactions(
        args.interactions,
        args.output_dir,
        min_warm_interactions=args.min_warm_interactions,
        source_data_version=source_manifest["data_version"],
    )
    return 0


def _interaction_sort_key(row: dict) -> tuple[datetime, str]:
    return datetime.fromisoformat(row["event_time"]), row["interaction_id"]


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
