def test_fixed_multi_turn_study_is_offline_and_reproducible(tmp_path):
    from app.evaluation.agent_study import DEFAULT_CASES,run_study
    from app.artifact_io import verify_artifacts
    output=tmp_path/'study'
    first=run_study(DEFAULT_CASES,output)
    assert first['scenarios']==12 and first['scenario_passed']==12
    assert first['provider_calls']==0 and first['steps_passed']==first['steps']
    before={p.name:p.read_bytes() for p in output.iterdir()}
    assert run_study(DEFAULT_CASES,output)==first
    assert before=={p.name:p.read_bytes() for p in output.iterdir()}
    verify_artifacts(output,'experiment_manifest.json')
