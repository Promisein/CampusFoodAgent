"""Build compact, uncapped city interactions without changing online processed data."""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from app import artifact_io
from app.retrieval.baselines import validate_interactions


DATA_VERSION = "tampa_full_reviews_v1"


def build_full_city_corpus(review_path, businesses_path, output_dir, *, progress=False):
    review_path, businesses_path, output_dir = map(
        lambda path: Path(path).resolve(), (review_path, businesses_path, output_dir))
    if any(output_dir == path or output_dir in path.parents for path in (review_path, businesses_path)):
        raise ValueError("Output cannot contain or replace source files")
    existing_manifest = output_dir / "data_manifest.json"
    if output_dir.exists() and any(output_dir.iterdir()):
        if not existing_manifest.exists() or json.loads(existing_manifest.read_text(encoding="utf-8")).get("data_version") != DATA_VERSION:
            raise ValueError("Refusing to overwrite unrelated data")
    business_bytes = businesses_path.read_bytes()
    business_rows = [json.loads(line) for line in business_bytes.splitlines() if line.strip()]
    businesses = {row["business_id"]: row for row in business_rows}
    if not businesses or len(businesses) != len(business_rows):
        raise ValueError("Empty or duplicate business universe")
    if any(row.get("city") != "Tampa" or row.get("state") != "FL" for row in business_rows):
        raise ValueError("This corpus is restricted to the existing Tampa, FL business universe")
    source_state = {path: (path.stat().st_size, path.stat().st_mtime_ns)
                    for path in (review_path, businesses_path)}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    kept, scanned, outside = 0, 0, 0
    seen, users, items = set(), set(), set()
    minimum, maximum = None, None
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix=".full-city-", dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        with review_path.open("rb") as source, (stage / "interactions.jsonl").open("w", encoding="utf-8") as out:
            for number, raw in enumerate(source, start=1):
                digest.update(raw)
                if not raw.strip():
                    continue
                try:
                    review = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError(f"Invalid source JSON at line {number}") from exc
                scanned += 1
                if progress and scanned % 1_000_000 == 0:
                    print(f"Scanned {scanned:,} reviews; retained {kept:,}", file=sys.stderr, flush=True)
                if review.get("business_id") not in businesses:
                    outside += 1
                    continue
                row = validate_interactions([{
                    "interaction_id": review.get("review_id"), "user_id": review.get("user_id"),
                    "business_id": review["business_id"], "rating": review.get("stars"),
                    "event_time": review.get("date"),
                }], businesses)[0]
                if row["interaction_id"] in seen:
                    raise ValueError(f"Duplicate selected review: {row['interaction_id']}")
                seen.add(row["interaction_id"])
                row.update(event_type="review", source="yelp_review")
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                kept += 1
                users.add(row["user_id"])
                items.add(row["business_id"])
                minimum = min(minimum, row["event_time"]) if minimum else row["event_time"]
                maximum = max(maximum, row["event_time"]) if maximum else row["event_time"]
        if not kept:
            raise ValueError("No matching city reviews")
        if source_state != {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in source_state}:
            raise RuntimeError("Source changed during corpus construction")
        from app.retrieval import baselines

        manifest = {
            "data_version": DATA_VERSION, "selected_city": {"city": "Tampa", "state": "FL"},
            "selection_policy": "all reviews for the existing business universe; no total or per-business truncation",
            "text_policy": "omit review text; existing evidence data is unchanged",
            "kept": {"businesses": len(businesses), "interactions": kept, "users": len(users),
                     "businesses_with_interactions": len(items)},
            "scanned_reviews": scanned, "discarded": {"outside_business_universe": outside},
            "date_min": minimum, "date_max": maximum,
            "inputs": {"reviews": {"sha256": digest.hexdigest(), "bytes": source_state[review_path][0]},
                       "businesses": {"sha256": hashlib.sha256(business_bytes).hexdigest(), "bytes": len(business_bytes)}},
            "code_sha256": {Path(module).name: artifact_io.file_sha256(module)
                            for module in (__file__, baselines.__file__, artifact_io.__file__)},
        }
        (stage / "businesses.jsonl").write_bytes(business_bytes)
        artifact_io.publish_directory(stage, output_dir, manifest, "data_manifest.json")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", type=Path, default=Path("data/archive/yelp_academic_dataset_review.json"))
    parser.add_argument("--businesses", type=Path, default=Path("data/processed/businesses.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/derived/tampa_full_reviews_v1"))
    args = parser.parse_args(argv)
    result = build_full_city_corpus(args.reviews, args.businesses, args.output_dir, progress=True)
    print(json.dumps(result["kept"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
