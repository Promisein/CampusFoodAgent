import json

import httpx
import pytest


def snapshot(tmp_path):
    from app.artifact_io import publish_directory
    from app.evidence import retrieve_evidence
    from app.models import EvidenceItem
    from app.query_intent import parse_intent
    from test_rag_context import response
    stage=tmp_path/'stage';stage.mkdir()
    rec=response()
    reviews={'b':[{'business_id':'b','review_id':'r','text':'A quiet cafe.'}]}
    rec.recommendations[0].evidence=[EvidenceItem(**e) for e in retrieve_evidence('b','quiet',parse_intent('quiet'),reviews['b'])['items']]
    traces=[{'query_id':f'q{i}','query':'quiet','engine':rec.engine,
             'recommendations':[r.model_dump() for r in rec.recommendations]} for i in range(1,7)]
    (stage/'query_results.json').write_text(json.dumps(traces),encoding='utf-8')
    output=tmp_path/'snapshot'
    publish_directory(stage,output,{'experiment_id':'query_quality_v1','snapshot_id':'fixture'},'experiment_manifest.json')
    return output,reviews


def test_live_comparison_is_bounded_and_preserves_grounding(tmp_path):
    from app.evaluation.pre_agent import run_comparison
    from app.rag.generation import DeepSeekProvider
    from app.rag.context import default_plan
    from app.rag.settings import RagSettings
    directory,reviews=snapshot(tmp_path)
    settings=RagSettings(api_key='mock-secret')
    calls=[]
    def handler(req):
        calls.append(1)
        context=json.loads(json.loads(req.content)['messages'][1]['content'])['untrusted_context']
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(default_plan(context))}}],
                                      'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
    provider=DeepSeekProvider(settings,transport=httpx.MockTransport(handler))
    report,traces=run_comparison(directory,reviews,settings=settings,provider=provider,live=True,query_ids=['q1','q2'])
    assert len(calls)==2 and report['provider_attempts']==2 and report['generated']==2
    assert report['citation_violations']==0 and report['ranking_changes']==0
    assert report['token_usage']['total_tokens']==60
    assert 'mock-secret' not in json.dumps((report,traces))
    with pytest.raises(ValueError):run_comparison(directory,reviews,settings=settings,provider=provider,live=True,query_ids=[f'q{i}' for i in range(1,7)])
    assert len(calls)==2
    report,_=run_comparison(directory,reviews,settings=settings,provider=provider,live=False,query_ids=['q1'])
    assert report['provider_attempts']==0 and len(calls)==2


def test_live_comparison_auth_failure_stops_without_retries(tmp_path):
    from app.evaluation.pre_agent import run_comparison
    from app.rag.generation import DeepSeekProvider
    from app.rag.settings import RagSettings
    directory,reviews=snapshot(tmp_path)
    settings=RagSettings(api_key='mock')
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(401,text='private response')
    report,traces=run_comparison(directory,reviews,settings=settings,
        provider=DeepSeekProvider(settings,transport=httpx.MockTransport(handler)),live=True,query_ids=['q1','q2'])
    assert len(calls)==1 and report['provider_attempts']==1
    assert report['stop_reason']=='authentication_failed'
    assert traces[0]['candidate']['mode']=='template'
    assert 'private response' not in json.dumps(traces)
    with pytest.raises(ValueError):run_comparison(directory,reviews,settings=RagSettings(),live=True,query_ids=['q1'])


def test_comparison_records_current_code_and_effective_settings_without_key():
    from app.evaluation.pre_agent import comparison_provenance
    from app.rag.settings import RagSettings
    value=comparison_provenance(RagSettings(api_key='never-export-this',max_tokens=512,max_restaurants=2))
    assert value['effective_settings']['max_tokens']==512
    assert value['effective_settings']['max_restaurants']==2
    assert 'app/evidence.py' in value['code_sha256']
    assert 'app/rag/generation.py' in value['code_sha256']
    assert 'never-export-this' not in json.dumps(value) and 'api_key' not in value['effective_settings']


def test_live_timeout_is_reported_as_unsuccessful_generation(tmp_path):
    from app.evaluation.pre_agent import run_comparison
    from app.rag.generation import DeepSeekProvider
    from app.rag.settings import RagSettings
    directory,reviews=snapshot(tmp_path)
    settings=RagSettings(api_key='mock')
    def handler(req):raise httpx.ReadTimeout('private diagnostic')
    report,_=run_comparison(directory,reviews,settings=settings,provider=DeepSeekProvider(settings,transport=httpx.MockTransport(handler)),live=True,query_ids=['q1'])
    assert report['all_live_generations_succeeded'] is False
    assert report['generated']==0 and report['provider_attempts']==1
