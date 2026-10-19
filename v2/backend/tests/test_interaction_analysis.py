import json
from pathlib import Path

from app.data_pipeline.analyze_interactions import (
    analyze_interactions,
    main,
    write_interaction_statistics,
)


def _interaction(
    interaction_id: str,
    user_id: str,
    *,
    business_id: str = "business-1",
    event_time: str = "2021-01-01 12:00:00",
    rating: float | None = 4.0,
) -> dict:
    return {
        "interaction_id": interaction_id,
        "user_id": user_id,
        "business_id": business_id,
        "event_type": "review",
        "event_time": event_time,
        "rating": rating,
        "review_text": "Good food.",
        "source": "yelp_review",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_analysis_counts_user_cohorts_and_time_range(tmp_path):
    interactions_path = tmp_path / "interactions.jsonl"
    rows = [
        _interaction("cold-1", "cold", event_time="2020-01-01 00:00:00"),
        _interaction("sparse-1", "sparse", event_time="2020-02-01 00:00:00"),
        _interaction("sparse-2", "sparse", event_time="2020-02-02 00:00:00"),
        *[
            _interaction(f"warm-{index}", "warm", event_time=f"2021-01-0{index} 00:00:00")
            for index in range(1, 6)
        ],
    ]
    _write_jsonl(interactions_path, rows)

    statistics = analyze_interactions(interactions_path, {"business-1"})

    assert statistics["rows"] == 8
    assert statistics["users"] == 3
    assert statistics["businesses"] == 1
    assert statistics["date_min"] == "2020-01-01 00:00:00"
    assert statistics["date_max"] == "2021-01-05 00:00:00"
    assert statistics["interactions_per_user"]["min"] == 1
    assert statistics["interactions_per_user"]["max"] == 5
    assert statistics["user_cohorts"] == {
        "cold": {"users": 1, "interactions": 1},
        "sparse": {"users": 1, "interactions": 2},
        "warm": {"users": 1, "interactions": 5},
    }


def test_analysis_reports_duplicate_invalid_missing_and_unknown_rows(tmp_path):
    interactions_path = tmp_path / "interactions.jsonl"
    rows = [
        _interaction("duplicate", "user-1"),
        _interaction("duplicate", "user-2"),
        _interaction(
            "invalid",
            "user-3",
            business_id="unknown-business",
            event_time="not-a-time",
            rating=None,
        ),
    ]
    _write_jsonl(interactions_path, rows)

    statistics = analyze_interactions(interactions_path, {"business-1"})

    assert statistics["duplicate_interaction_ids"] == 1
    assert statistics["invalid_event_times"] == 1
    assert statistics["unknown_business_ids"] == 1
    assert statistics["missing_fields"] == {"rating": 1}


def test_statistics_are_written_as_utf8_json(tmp_path):
    output_path = tmp_path / "derived" / "interaction_statistics.json"
    statistics = {"rows": 2, "note": "用户审计"}

    write_interaction_statistics(statistics, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == statistics


def test_cli_writes_statistics_from_interactions_and_businesses(tmp_path):
    interactions_path = tmp_path / "interactions.jsonl"
    businesses_path = tmp_path / "businesses.jsonl"
    output_path = tmp_path / "derived" / "interaction_statistics.json"
    _write_jsonl(interactions_path, [_interaction("interaction-1", "user-1")])
    _write_jsonl(businesses_path, [{"business_id": "business-1"}])

    exit_code = main(
        [
            "--interactions",
            str(interactions_path),
            "--businesses",
            str(businesses_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["rows"] == 1
