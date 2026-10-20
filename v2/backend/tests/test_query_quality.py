import csv
import json

import pytest


def test_fixed_suite_has_40_curated_queries_and_no_human_gold():
    from app.evaluation.query_quality import DEFAULT_CASES
    fixture = json.loads(DEFAULT_CASES.read_text(encoding='utf-8'))
    assert len(fixture['cases']) == 40
    assert len({c['id'] for c in fixture['cases']}) == 40
    assert {c['expected']['outcome'] for c in fixture['cases']} == {'results', 'clarify', 'empty'}
    assert fixture['label_source'] == 'agent_curated_functional_not_human_gold'


def test_offline_audit_detects_contracts_and_exports_unjudged_reproducibly(tmp_path):
    from app.evaluation.query_quality import run_study, score_review
    from app.evaluation.query_study import fixture_service
    from app.artifact_io import verify_artifacts
    from app.evaluation.query_study import DEFAULT_CASES as SYNTHETIC
    fixture = json.loads(SYNTHETIC.read_text(encoding='utf-8'))
    dataset, serving = fixture_service(fixture, tmp_path/'fixture')
    cases = tmp_path/'inputs/cases.json'
    cases.parent.mkdir()
    cases.write_text(json.dumps({'label_source':'agent_curated_functional_not_human_gold','cases':[
        {'id':'q1','group':'coffee','request':{'query':'coffee'},'expected':{'outcome':'results','include_any':['Coffee & Tea']}},
        {'id':'q2','group':'clarify','request':{'query':'咖啡，50元'},'expected':{'outcome':'clarify'}},
        {'id':'q3','group':'empty','request':{'query':'coffee','city':'Nowhere'},'expected':{'outcome':'empty'}},
    ]}),encoding='utf-8')
    output=tmp_path/'study'
    first=run_study(cases, output, dataset=dataset, serving=serving, search=None, ranker=None,
                    defaults={'latitude':0,'longitude':0,'radius_km':50})
    assert first['requests']==3 and first['contract_passed']==3
    assert first['live_provider_calls']==0
    assert first['citation_violations']==0 and first['card_answer_mismatches']==0
    before={p.name:p.read_bytes() for p in output.iterdir()}
    assert run_study(cases,output,dataset=dataset,serving=serving,search=None,ranker=None,
                    defaults={'latitude':0,'longitude':0,'radius_km':50})==first
    assert before=={p.name:p.read_bytes() for p in output.iterdir()}
    verify_artifacts(output,'experiment_manifest.json')
    metrics=score_review(output,output/'review_sheet.csv')
    assert metrics['restaurant_judged']==0 and metrics['evidence_judged']==0
    assert metrics['precision_at_5_complete_queries'] is None
    with pytest.raises(ValueError):
        run_study(cases,cases.parent,dataset=dataset,serving=serving,search=None,ranker=None)


def test_review_import_rejects_forged_stale_duplicate_or_unattributed_labels(tmp_path):
    from app.evaluation.query_quality import score_rows
    restaurant={'record_id':'r','snapshot_id':'snap','kind':'restaurant','query_id':'q','business_id':'b','rank':'1',
                'relevance':'','stance':'','reviewer':'','note':''}
    quote={**restaurant,'record_id':'e','kind':'evidence','review_id':'review','excerpt':'Not quiet.'}
    expected=[restaurant,quote]
    labels=[{**restaurant,'relevance':'2','reviewer':'tester'},{**quote,'stance':'contradict','reviewer':'tester'}]
    score=score_rows(expected,labels)
    assert score['restaurant_judged']==1 and score['evidence_judged']==1
    assert score['evidence_stance_counts']['contradict']==1
    assert score['precision_at_5_complete_queries']==1
    assert score['pooled_ndcg_at_5_complete_queries']==1
    for bad in ([{**labels[0],'snapshot_id':'old'}], labels+[labels[0]],
                [{**labels[0],'reviewer':''}], [{**labels[0],'record_id':'foreign'}],
                [{**labels[0],'business_id':'other'}], [{**labels[0],'relevance':'9'}],
                [{**labels[1],'stance':'support','excerpt':'quiet'}]):
        with pytest.raises(ValueError):score_rows(expected,bad)
    partial=score_rows([restaurant,{**restaurant,'record_id':'r2','rank':'2'}],[labels[0]])
    assert partial['complete_relevance_queries']==0
    assert partial['precision_at_5_complete_queries'] is None


def test_contract_audit_catches_bad_radius_category_price_and_abstention():
    from app.evaluation.query_quality import contract_errors
    from app.models import RecommendationRequest
    from test_rag_context import response
    req=RecommendationRequest(query='coffee',latitude=0,longitude=0)
    rec=response()
    business={'b':{'categories_normalized':['Pizza'],'latitude':1,'longitude':0,'price_level':4,
                   'city':'Elsewhere','is_open':False}}
    case={'expected':{'outcome':'empty','include_any':['Coffee & Tea'],'exclude_any':['Pizza'],
                      'max_price_level':1,'radius_km':1}}
    assert set(contract_errors(case,req,rec,business)) == {
        'unexpected_outcome','category_include','category_exclude','radius','price','city_or_snapshot_open'}
