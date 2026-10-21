import json
from uuid import uuid4

import httpx
import pytest


def setup_agent(tmp_path,monkeypatch):
    import app.main as main
    from app.agent.store import SessionRepository
    from test_personalized_api import setup_service
    client,*_=setup_service(tmp_path,monkeypatch)
    repo=SessionRepository(tmp_path/'agent.sqlite3')
    monkeypatch.setattr(main,'get_agent_repository',lambda:repo)
    created=client.post('/api/v2/agent/sessions',json={'latitude':0,'longitude':0,'radius_km':10,'max_price_level':3,'user_id':'agent-test-user'})
    assert created.status_code==201
    return client,created.json(),repo


def turn(client,session,message,**options):
    payload={'turn_id':str(uuid4()),'expected_version':session['version'],'message':message,**options}
    response=client.post(f"/api/v2/agent/sessions/{session['session_id']}/turns",json=payload)
    assert response.status_code==200,response.text
    result=response.json();session['version']=result['version']
    return result,payload


def test_multi_turn_search_refine_explain_favorite_and_retry(tmp_path,monkeypatch):
    client,session,repo=setup_agent(tmp_path,monkeypatch)
    first,_=turn(client,session,'咖啡')
    assert first['action']=='search' and first['recommendations']
    second,_=turn(client,session,'再便宜一点')
    assert second['state']['slots']['include']==['coffee']
    assert second['state']['slots']['max_price_level']==2
    explained,_=turn(client,session,'解释第一家')
    assert explained['action']=='explain' and explained['answer']['mode']=='template'
    assert explained['focused_business_id']==second['recommendations'][0]['business_id']
    saved,payload=turn(client,session,'收藏它')
    assert saved['status']=='completed' and saved['action']=='favorite'
    duplicate=client.post(f"/api/v2/agent/sessions/{session['session_id']}/turns",json=payload)
    assert duplicate.json()==saved
    history,_=turn(client,session,'查看历史')
    assert len([e for e in history['events'] if e['event_type']=='favorite'])==1
    assert repo.get(session['session_id'])['version']==5


def test_clarification_blocks_stale_writes_and_new_search_clears_focus(tmp_path,monkeypatch):
    client,session,_=setup_agent(tmp_path,monkeypatch)
    turn(client,session,'咖啡')
    turn(client,session,'解释第一家')
    invalid,_=turn(client,session,'50元以内')
    assert invalid['status']=='needs_clarification' and not invalid['recommendations']
    blocked,_=turn(client,session,'收藏第一家')
    assert blocked['status']=='needs_clarification'
    valid,_=turn(client,session,'价格等级2')
    assert valid['recommendations']
    ambiguous,_=turn(client,session,'收藏它')
    if len(valid['recommendations'])>1:assert ambiguous['status']=='needs_clarification'


def test_model_cannot_authorize_write_or_choose_foreign_merchant(tmp_path,monkeypatch):
    import app.main as main
    from app.rag.settings import RagSettings
    from app.rag.generation import DeepSeekProvider
    client,session,_=setup_agent(tmp_path,monkeypatch)
    settings=RagSettings(api_key='mock-secret')
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'action':'favorite','business_id':'foreign'})}}]})
    monkeypatch.setattr(main,'get_agent_settings',lambda:settings)
    monkeypatch.setattr(main,'get_agent_planner_provider',lambda settings:DeepSeekProvider(settings,transport=httpx.MockTransport(handler)))
    result,_=turn(client,session,'咖啡',use_model=True)
    assert result['action']=='search' and result['planner']['mode']=='rules'
    assert result['budget']['provider_calls']==1 and len(calls)==1
    assert 'mock-secret' not in json.dumps(result)


def test_model_valid_action_and_generation_budget_are_separate(tmp_path,monkeypatch):
    import app.main as main
    from app.rag.settings import RagSettings
    from app.rag.generation import DeepSeekProvider
    client,session,_=setup_agent(tmp_path,monkeypatch)
    settings=RagSettings(api_key='mock')
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'action':'search','index':None})}}]})
    monkeypatch.setattr(main,'get_agent_settings',lambda:settings)
    monkeypatch.setattr(main,'get_agent_planner_provider',lambda settings:DeepSeekProvider(settings,transport=httpx.MockTransport(handler)))
    result,_=turn(client,session,'咖啡',use_model=True)
    assert result['planner']['mode']=='deepseek_action'
    assert len(result['trace'])<=4


def test_session_validation_and_optimistic_version(tmp_path,monkeypatch):
    client,session,_=setup_agent(tmp_path,monkeypatch)
    result,_=turn(client,session,'咖啡')
    stale=client.post(f"/api/v2/agent/sessions/{session['session_id']}/turns",json={'turn_id':'stale','expected_version':0,'message':'披萨'})
    assert stale.status_code==409
    assert client.get('/api/v2/agent/sessions/unknown').status_code==404
    bad=client.post(f"/api/v2/agent/sessions/{session['session_id']}/turns",json={'turn_id':'x','expected_version':1,'message':'a'*1001})
    assert bad.status_code==422


def test_model_clarification_invalidates_old_results(tmp_path,monkeypatch):
    import app.main as main
    from app.rag.settings import RagSettings
    from app.rag.generation import DeepSeekProvider
    client,session,_=setup_agent(tmp_path,monkeypatch)
    turn(client,session,'咖啡')
    settings=RagSettings(api_key='mock')
    def handler(req):return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"action":"clarify","index":null}'}}]})
    monkeypatch.setattr(main,'get_agent_settings',lambda:settings)
    monkeypatch.setattr(main,'get_agent_planner_provider',lambda s:DeepSeekProvider(s,transport=httpx.MockTransport(handler)))
    result,_=turn(client,session,'50元以内',use_model=True)
    assert result['status']=='needs_clarification'
    assert result['state']['pending_clarification'] and not result['recommendations']
    saved,_=turn(client,session,'收藏第一家')
    assert saved['status']=='needs_clarification'


def test_search_budget_exhaustion_invalidates_references(tmp_path,monkeypatch):
    import app.main as main
    from app.agent.service import Budget
    client,session,_=setup_agent(tmp_path,monkeypatch)
    turn(client,session,'咖啡')
    original=main.get_agent_service
    def exhausted():
        service=original();service.budget_factory=lambda:Budget(max_steps=0)
        return service
    monkeypatch.setattr(main,'get_agent_service',exhausted)
    result,_=turn(client,session,'近一点')
    assert result['status']=='limit_exceeded'
    assert result['state']['pending_clarification'] and not result['recommendations']


def test_explanation_reserves_single_model_call_and_uses_current_merchant(tmp_path,monkeypatch):
    import app.main as main
    import app.agent.service as service_module
    from app.rag.generation import AnswerService,DeepSeekProvider
    from app.rag.context import default_plan
    from app.rag.settings import RagSettings
    client,session,_=setup_agent(tmp_path,monkeypatch)
    first,_=turn(client,session,'咖啡')
    settings=RagSettings(api_key='mock')
    calls=[]
    def handler(req):
        calls.append(1)
        context=json.loads(json.loads(req.content)['messages'][1]['content'])['untrusted_context']
        assert [i['business_id'] for i in context['items']]==[first['recommendations'][0]['business_id']]
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(default_plan(context))}}]})
    monkeypatch.setattr(main,'get_agent_settings',lambda:settings)
    monkeypatch.setattr(main,'get_agent_planner_provider',lambda s:pytest.fail('planner must not consume reserved call'))
    monkeypatch.setattr(service_module,'AnswerService',lambda s:AnswerService(s,DeepSeekProvider(s,transport=httpx.MockTransport(handler))))
    explained,payload=turn(client,session,'解释第一家',use_model=True,generate_answer=True)
    assert explained['answer']['mode']=='deepseek_plan' and len(calls)==1
    assert explained['budget']['provider_calls']==1
    duplicate=client.post(f"/api/v2/agent/sessions/{session['session_id']}/turns",json=payload)
    assert duplicate.json()==explained and len(calls)==1
