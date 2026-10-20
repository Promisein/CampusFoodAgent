import json
import math

import pytest


def sample():
    businesses = {
        item: {"business_id": item, "categories_normalized": ["Food"],
               "latitude": 0, "longitude": 0, "price_level": 1}
        for item in "ABCD"
    }
    entries = [
        ("u1", "A", 5, "2020-01-01"), ("u2", "A", 5, "2020-01-01"),
        ("u2", "B", 5, "2020-01-02"), ("u3", "C", 5, "2020-01-02"),
        ("u1", "A", 5, "2020-02-01"),  # repeat skipped
        ("u1", "B", 5, "2020-02-02"),
        ("cold", "D", 5, "2020-02-02"),  # historical catalog cannot contain D
        ("low", "C", 1, "2020-02-03"),
        ("u1", "C", 5, "2020-03-01"), ("new", "D", 5, "2020-03-02"),
    ]
    rows = [{"interaction_id": str(i), "user_id": user, "business_id": item,
             "rating": rating, "event_time": time}
            for i, (user, item, rating, time) in enumerate(entries)]
    return rows, businesses


def evaluate(rows=None, **kwargs):
    from app.evaluation.baseline_replay import evaluate_dataset

    original, businesses = sample()
    return evaluate_dataset(original if rows is None else rows, businesses,
                            cutoffs=("2020-02-01", "2020-03-01"), **kwargs)


def test_metrics_use_single_target_rank_and_distinguish_empty_denominators():
    from app.evaluation.baseline_replay import summarize_metrics

    result = summarize_metrics([
        {"rank": 3, "eligible": True, "candidates": ["A", "B", "C"]},
        {"rank": None, "eligible": False, "candidates": []},
    ], catalog_size=4)
    assert result["recall@20"] == 0.5
    assert result["ndcg@10"] == 0.25  # (1/log2(3+1)) / 2
    assert result["eligible_recall@20"] == 1
    assert result["catalog_coverage@100"] == 0.75
    assert result["empty_recall_rate"] == 0.5
    assert summarize_metrics([], catalog_size=0)["recall@20"] is None


def test_target_selection_keeps_unavailable_targets_and_rejects_repeat_positives():
    report, artifacts = evaluate()
    validation = report["splits"]["validation"]
    assert validation["window"]["target_users"] == 2
    assert validation["window"]["users_without_new_positive"] == 1
    assert validation["window"]["repeated_positive_events"] == 1
    city = validation["scenarios"]["city_preference"]
    assert city["eligible_targets"] == 1
    assert city["engines"]["popularity"]["all"]["recall@20"] == 0.5
    assert city["engines"]["itemcf"]["all"]["recall@20"] == 0.5
    assert city["engines"]["combined"]["cold"]["recall@20"] == 0
    target_ids = {row["target_business_id"] for row in artifacts["traces"]
                  if row["split"] == "validation" and row["scenario"] == "city_preference"}
    assert target_ids == {"B", "D"}
    missing = next(row for row in artifacts["traces"] if row["split"] == "validation"
                   and row["scenario"] == "city_preference" and row["target_business_id"] == "D")
    assert missing["eligibility_reason"] == "not_in_historical_catalog"
    assert "D" not in missing["candidates"]["combined"]


def test_boundary_and_future_changes_cannot_change_validation_features_or_results():
    rows, _ = sample()
    report1, artifacts1 = evaluate(rows)
    rows[-1]["rating"] = 1
    report2, artifacts2 = evaluate(rows)
    assert report1["splits"]["validation"] == report2["splits"]["validation"]
    assert [p for p in artifacts1["profiles"] if p["split"] == "validation"] == [
        p for p in artifacts2["profiles"] if p["split"] == "validation"]
    assert report1["splits"]["validation"]["history_events"] == 4
    assert report1["splits"]["test"]["history_events"] == 8


def test_simulated_geo_reports_cold_position_absence_and_constraints():
    report, artifacts = evaluate()
    geo = report["splits"]["validation"]["scenarios"]["simulated_geo"]
    assert geo["requests_without_position"] == 1
    assert geo["eligible_targets"] == 1
    assert geo["constraint_violations"] == 0
    assert sum(geo["complementarity@100"].values()) == 2
    assert all(row["as_of_time"] <= row["target_time"] for row in artifacts["traces"])


def test_failure_analysis_preserves_denominators_and_anonymizes_examples():
    report, _ = evaluate()
    city = report["splits"]["validation"]["scenarios"]["city_preference"]
    assert sum(city["combined_outcomes"].values()) == 2
    assert city["combined_outcomes"]["not_in_historical_catalog"] == 1
    assert city["combined_outcomes"]["hit@20"] == 1
    assert city["failure_examples"][0]["target_business_id"] == "D"
    assert "user_id" not in city["failure_examples"][0]
    assert len(city["failure_examples"][0]["user_hash"]) == 16


def test_replay_is_deterministic_under_input_shuffle():
    rows, _ = sample()
    assert evaluate(rows) == evaluate(list(reversed(rows)))


def test_cli_writes_reproducible_artifacts_without_modifying_sources(tmp_path):
    from app.evaluation.baseline_replay import main

    rows, businesses = sample()
    source, out = tmp_path / "processed", tmp_path / "result"
    source.mkdir()
    for name, values in [("interactions.jsonl", rows), ("businesses.jsonl", businesses.values())]:
        (source / name).write_text("".join(json.dumps(row) + "\n" for row in values), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    args = ["--data-dir", str(source), "--output-dir", str(out),
            "--validation-cutoff", "2020-02-01", "--test-cutoff", "2020-03-01"]
    assert main(args) == 0
    assert json.loads((out / "metrics.json").read_text())["splits"]["validation"]["history_events"] == 4
    assert (out / "report.md").exists()
    assert (out / "neighbors.jsonl").exists()
    assert (out / "profiles.jsonl").exists()
    assert "review_text" not in (out / "request_trace.jsonl").read_text()
    first = {path.name: path.read_bytes() for path in out.iterdir()}
    assert main(args) == 0
    assert first == {path.name: path.read_bytes() for path in out.iterdir()}
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}


def test_output_cannot_overwrite_inputs_or_unrelated_existing_artifacts(tmp_path):
    from app.evaluation.baseline_replay import run_experiment

    source = tmp_path / "processed"
    source.mkdir()
    original = source / "keep.txt"
    original.write_text("keep")
    for output in (source, source.parent, source / "nested"):
        with pytest.raises(ValueError):
            run_experiment(source, output)
    out = tmp_path / "old_profiles"
    out.mkdir()
    (out / "profile_manifest.json").write_text("{}")
    with pytest.raises(ValueError):
        run_experiment(source, out)
    assert original.read_text() == "keep"


@pytest.mark.parametrize("cutoffs", [("2020-03-01", "2020-02-01"),
                                    ("2019-01-01", "2019-02-01")])
def test_invalid_or_empty_time_windows_fail(cutoffs):
    from app.evaluation.baseline_replay import evaluate_dataset

    rows, businesses = sample()
    with pytest.raises(ValueError):
        evaluate_dataset(rows, businesses, cutoffs=cutoffs)
