def test_offline_rag_study_is_deterministic_and_audits_references(tmp_path):
    from app.evaluation.rag_study import run_study,DEFAULT_CASES
    from app.artifact_io import verify_artifacts
    out=tmp_path/'rag'
    report=run_study(DEFAULT_CASES,out)
    assert report['cases']==17 and report['contract_passed']==17
    assert report['citation_ownership_violations']==0
    assert report['live_deepseek_calls']==0
    before={p.name:p.read_bytes() for p in out.iterdir()}
    assert run_study(DEFAULT_CASES,out)==report
    assert before=={p.name:p.read_bytes() for p in out.iterdir()}
    verify_artifacts(out,'experiment_manifest.json')
