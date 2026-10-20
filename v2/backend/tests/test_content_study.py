import copy
import json

import pytest


CUTOFFS = ("2020-02-01", "2020-03-01")


def fixture():
    businesses = {item: {"business_id": item, "categories_normalized": [category],
                         "latitude": 0, "longitude": 0, "price_level": 1}
                  for item, category in [("A", "Coffee"), ("B", "Coffee"), ("C", "Pizza"), ("D", "Coffee")]}
    data = [("u", "A", "2020-01-01"), ("v", "B", "2020-01-02"),
            ("w", "C", "2020-01-03"), ("u", "B", "2020-02-02"),
            ("new", "D", "2020-02-03"), ("u", "C", "2020-03-01"),
            ("later", "B", "2020-03-02")]
    rows = [{"interaction_id": str(i), "user_id": user, "business_id": item,
             "rating": 5, "event_time": time} for i, (user, item, time) in enumerate(data)]
    # Missing B's early review changes catalog/history, not the common evaluation labels.
    legacy = [row for row in rows if row["interaction_id"] != "1"]
    return legacy, rows, businesses


def test_streaming_metrics_match_hand_computed_rank_and_coverage():
    from app.evaluation.content_study import MetricAccumulator

    acc = MetricAccumulator()
    acc.add(["A", "B", "C"], "C", eligible=True)
    acc.add([], "D", eligible=False)
    result = acc.result(catalog_size=4)
    assert result["requests"] == 2
    assert result["recall@20"] == .5
    assert result["ndcg@10"] == .25
    assert result["catalog_coverage@100"] == .75
    assert result["eligible_recall@20"] == 1
    assert result["empty_recall_rate"] == .5
    assert MetricAccumulator().result(catalog_size=0)["recall@20"] is None


def test_common_targets_keep_identical_denominators_and_expose_catalog_loss():
    from app.evaluation.content_study import evaluate_study

    legacy, full, businesses = fixture()
    report, _ = evaluate_study(legacy, full, businesses, cutoffs=CUTOFFS)
    old = report["variants"]["legacy_history"]["validation"]["scenarios"]["city_preference"]
    new = report["variants"]["full_history"]["validation"]["scenarios"]["city_preference"]
    assert old["requests"] == new["requests"] == 2
    assert old["target_fingerprint"] == new["target_fingerprint"]
    assert old["eligible_targets"] == 0
    assert new["eligible_targets"] == 1
    assert old["engines"]["content"]["all"]["recall@20"] == 0
    assert new["engines"]["content"]["all"]["recall@20"] == .5
    assert new["constraint_violations"] == 0


def test_snapshot_experiment_is_labeled_conditional_and_keeps_main_targets():
    from app.evaluation.content_study import evaluate_study

    legacy, full, businesses = fixture()
    report, _ = evaluate_study(legacy, full, businesses, cutoffs=CUTOFFS)
    snapshot = report["variants"]["full_snapshot_catalog"]["validation"]
    assert snapshot["catalog_policy"] == "snapshot_catalog"
    assert snapshot["strict_historical_catalog"] is False
    city = snapshot["scenarios"]["city_preference"]
    assert city["requests"] == 2
    assert city["eligible_targets"] == 2
    assert "simulated_geo" not in snapshot["scenarios"]


def test_future_changes_do_not_affect_validation_or_earlier_content_models():
    from app.evaluation.content_study import evaluate_study

    legacy, full, businesses = fixture()
    report1, artifacts1 = evaluate_study(legacy, full, businesses, cutoffs=CUTOFFS)
    changed = copy.deepcopy(full)
    changed[-1]["rating"] = 1
    changed_legacy = [row for row in changed if row["interaction_id"] != "1"]
    report2, artifacts2 = evaluate_study(changed_legacy, changed, businesses, cutoffs=CUTOFFS)
    for variant in report1["variants"]:
        assert report1["variants"][variant]["validation"] == report2["variants"][variant]["validation"]
    assert artifacts1["models"]["full_history_validation"] == artifacts2["models"]["full_history_validation"]


def test_study_rejects_inconsistent_legacy_or_nonmatching_business_events():
    from app.evaluation.content_study import evaluate_study

    legacy, full, businesses = fixture()
    legacy[0] = {**legacy[0], "rating": 1}
    with pytest.raises(ValueError):
        evaluate_study(legacy, full, businesses, cutoffs=CUTOFFS)


def test_study_cli_reproduces_metrics_digests_and_does_not_change_sources(tmp_path):
    from app.evaluation.content_study import main

    legacy, full, businesses = fixture()
    old_dir, full_dir = tmp_path / "old", tmp_path / "full"
    for directory, rows in ((old_dir, legacy), (full_dir, full)):
        directory.mkdir()
        (directory / "interactions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        (directory / "businesses.jsonl").write_text("".join(json.dumps(row) + "\n" for row in businesses.values()), encoding="utf-8")
    before = {str(path): path.read_bytes() for directory in (old_dir, full_dir) for path in directory.iterdir()}
    out = tmp_path / "study"
    args = ["--legacy-dir", str(old_dir), "--full-dir", str(full_dir), "--output-dir", str(out),
            "--validation-cutoff", CUTOFFS[0], "--test-cutoff", CUTOFFS[1]]
    assert main(args) == 0
    first = {path.name: path.read_bytes() for path in out.iterdir()}
    assert main(args) == 0
    assert first == {path.name: path.read_bytes() for path in out.iterdir()}
    assert all(path.read_bytes() == before[str(path)] for directory in (old_dir, full_dir) for path in directory.iterdir())
    assert "review_text" not in (out / "trace_samples.jsonl").read_text()


def test_study_output_protects_source_and_unrelated_directories(tmp_path):
    from app.evaluation.content_study import run_study

    source = tmp_path / "source"
    source.mkdir()
    for output in (source, tmp_path):
        with pytest.raises(ValueError):
            run_study(source, source, output)
    output = tmp_path / "old_profiles"
    output.mkdir()
    (output / "keep").write_text("keep")
    with pytest.raises(ValueError):
        run_study(source, source, output)


def test_failed_study_publication_preserves_previous_complete_result(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    from app.evaluation.content_study import run_study

    legacy, full, businesses = fixture()
    old_dir, full_dir, out = tmp_path / "old", tmp_path / "full", tmp_path / "study"
    for directory, rows in ((old_dir, legacy), (full_dir, full)):
        directory.mkdir()
        (directory / "interactions.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
        (directory / "businesses.jsonl").write_text("".join(json.dumps(row)+"\n" for row in businesses.values()))
    run_study(old_dir, full_dir, out, cutoffs=CUTOFFS)
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    real_replace = os.replace

    def fail_new_directory(source, target):
        if Path(source).name.startswith(".content-study-") and Path(target) == out:
            raise OSError("simulated publication failure")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_new_directory)
    with pytest.raises(OSError):
        run_study(old_dir, full_dir, out, cutoffs=CUTOFFS)
    assert before == {path.name: path.read_bytes() for path in out.iterdir()}


def test_study_manifest_fingerprints_eligibility_dependency(tmp_path):
    import hashlib
    from pathlib import Path
    from app.evaluation import baseline_replay
    from app.evaluation.content_study import run_study

    legacy, full, businesses = fixture()
    for name, rows in (("old", legacy), ("full", full)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "interactions.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
        (directory / "businesses.jsonl").write_text("".join(json.dumps(row)+"\n" for row in businesses.values()))
    out = tmp_path / "study"
    run_study(tmp_path / "old", tmp_path / "full", out, cutoffs=CUTOFFS)
    manifest = json.loads((out / "study_manifest.json").read_text())
    assert manifest["code_sha256"]["baseline_replay.py"] == hashlib.sha256(Path(baseline_replay.__file__).read_bytes()).hexdigest()
