import json


def test_query_study_reproducible_labels_and_provenance(tmp_path):
    from app.evaluation.query_study import run_study, DEFAULT_CASES
    from app.artifact_io import verify_artifacts
    output = tmp_path/'study'
    first = run_study(DEFAULT_CASES, output)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert run_study(DEFAULT_CASES, output) == first
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    verify_artifacts(output, 'experiment_manifest.json')
    assert first['splits']['acceptance']['query_v1']['constraint_violations'] == 0
    assert first['splits']['dev']['query_v1']['parser_exact_rate'] == 1
    assert first['splits']['acceptance']['query_v1']['parser_exact_rate'] == 1
    assert first['splits']['acceptance']['query_v1']['ndcg@5'] > first['splits']['acceptance']['historical_only']['ndcg@5']
    assert first['splits']['acceptance']['query_v1']['evidence_precision'] == 1


def test_query_study_does_not_overwrite_input(tmp_path):
    import pytest
    from app.evaluation.query_study import run_study, DEFAULT_CASES
    with pytest.raises(ValueError):
        run_study(DEFAULT_CASES, DEFAULT_CASES.parent)
