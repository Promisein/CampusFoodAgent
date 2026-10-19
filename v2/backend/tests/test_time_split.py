import json
from pathlib import Path

import pytest

from app.data_pipeline.split_interactions import main, split_interactions


def _interaction(
    interaction_id: str,
    user_id: str,
    event_time: str,
) -> dict:
    return {
        "interaction_id": interaction_id,
        "user_id": user_id,
        "business_id": "business-1",
        "event_type": "review",
        "event_time": event_time,
        "rating": 4.0,
        "review_text": "Good food.",
        "source": "yelp_review",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_split_uses_leave_two_out_and_preserves_cold_users(tmp_path):
    interactions_path = tmp_path / "interactions.jsonl"
    output_dir = tmp_path / "split"
    rows = [
        *[
            _interaction(f"warm-{index}", "warm", f"2021-01-0{index} 00:00:00")
            for index in range(1, 7)
        ],
        _interaction("sparse-1", "sparse", "2021-02-01 00:00:00"),
        _interaction("sparse-2", "sparse", "2021-02-02 00:00:00"),
        _interaction("cold-1", "cold", "2021-03-01 00:00:00"),
    ]
    _write_jsonl(interactions_path, rows)

    manifest = split_interactions(
        interactions_path,
        output_dir,
        min_warm_interactions=5,
        source_data_version="test-data",
    )

    assert [row["interaction_id"] for row in _read_jsonl(output_dir / "train_interactions.jsonl")] == [
        "warm-1",
        "warm-2",
        "warm-3",
        "warm-4",
    ]
    assert _read_jsonl(output_dir / "validation_interactions.jsonl")[0]["interaction_id"] == "warm-5"
    assert _read_jsonl(output_dir / "test_interactions.jsonl")[0]["interaction_id"] == "warm-6"
    cold_rows = _read_jsonl(output_dir / "cold_start_interactions.jsonl")
    assert {row["interaction_id"] for row in cold_rows} == {"sparse-1", "sparse-2", "cold-1"}
    assert {row["user_cohort"] for row in cold_rows} == {"cold", "sparse"}
    assert manifest["counts"] == {"train": 4, "validation": 1, "test": 1, "cold_start": 3, "total": 9}
    assert manifest["user_counts"] == {"warm": 1, "sparse": 1, "cold": 1, "total": 3}


def test_split_is_stable_for_same_timestamp_and_input_order(tmp_path):
    rows = [
        _interaction(interaction_id, "warm", "2021-01-01 00:00:00")
        for interaction_id in ["e", "c", "a", "d", "b"]
    ]
    first_input = tmp_path / "first.jsonl"
    second_input = tmp_path / "second.jsonl"
    first_output = tmp_path / "first-output"
    second_output = tmp_path / "second-output"
    _write_jsonl(first_input, rows)
    _write_jsonl(second_input, list(reversed(rows)))

    split_interactions(first_input, first_output, source_data_version="test")
    split_interactions(second_input, second_output, source_data_version="test")

    for filename in (
        "train_interactions.jsonl",
        "validation_interactions.jsonl",
        "test_interactions.jsonl",
        "cold_start_interactions.jsonl",
    ):
        assert (first_output / filename).read_text(encoding="utf-8") == (
            second_output / filename
        ).read_text(encoding="utf-8")
    assert [
        row["interaction_id"] for row in _read_jsonl(first_output / "train_interactions.jsonl")
    ] == ["a", "b", "c"]
    assert _read_jsonl(first_output / "validation_interactions.jsonl")[0]["interaction_id"] == "d"
    assert _read_jsonl(first_output / "test_interactions.jsonl")[0]["interaction_id"] == "e"


def test_split_outputs_have_no_overlap_and_preserve_total_count(tmp_path):
    interactions_path = tmp_path / "interactions.jsonl"
    output_dir = tmp_path / "split"
    rows = [
        *[
            _interaction(f"user-a-{index}", "user-a", f"2020-01-0{index} 00:00:00")
            for index in range(1, 6)
        ],
        *[
            _interaction(f"user-b-{index}", "user-b", f"2020-02-0{index} 00:00:00")
            for index in range(1, 6)
        ],
    ]
    _write_jsonl(interactions_path, rows)

    manifest = split_interactions(interactions_path, output_dir, source_data_version="test")

    id_sets = []
    for filename in manifest["outputs"].values():
        if filename.endswith(".jsonl"):
            id_sets.append(
                {row["interaction_id"] for row in _read_jsonl(output_dir / filename)}
            )
    assert sum(len(ids) for ids in id_sets) == len(set().union(*id_sets)) == len(rows)
    assert json.loads((output_dir / "split_manifest.json").read_text(encoding="utf-8")) == manifest


def test_split_rejects_duplicate_interaction_ids(tmp_path):
    interactions_path = tmp_path / "interactions.jsonl"
    _write_jsonl(
        interactions_path,
        [
            _interaction("duplicate", "user-a", "2021-01-01 00:00:00"),
            _interaction("duplicate", "user-b", "2021-01-02 00:00:00"),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate interaction_id: duplicate"):
        split_interactions(
            interactions_path,
            tmp_path / "split",
            source_data_version="test",
        )


def test_cli_reads_source_version_and_writes_split(tmp_path):
    interactions_path = tmp_path / "interactions.jsonl"
    source_manifest_path = tmp_path / "data_manifest.json"
    output_dir = tmp_path / "split"
    _write_jsonl(
        interactions_path,
        [
            _interaction(f"warm-{index}", "warm", f"2021-01-0{index} 00:00:00")
            for index in range(1, 6)
        ],
    )
    source_manifest_path.write_text(
        json.dumps({"data_version": "source-v1"}),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--interactions",
            str(interactions_path),
            "--source-manifest",
            str(source_manifest_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    manifest = json.loads((output_dir / "split_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_data_version"] == "source-v1"
