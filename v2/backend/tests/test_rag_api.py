import json

import httpx

from test_personalized_api import payload,setup_service


def test_answer_is_opt_in_and_no_key_fallback_keeps_recommendations(tmp_path,monkeypatch):
    import app.main as main
    from app.rag.generation import AnswerService
    from app.rag.settings import RagSettings
    client,_,_,_=setup_service(tmp_path,monkeypatch)
    monkeypatch.setattr(main,'get_rag_service',lambda:AnswerService(RagSettings()))
    original=client.post('/api/v2/recommend',json={**payload(),'query':'披萨'}).json()
    augmented=client.post('/api/v2/recommend',json={**payload(),'query':'披萨','generate_answer':True}).json()
    assert original['recommendations']==augmented['recommendations']
    assert original['answer'] is None
    assert augmented['answer']['reason']=='missing_key'
    assert augmented['metadata']['request_id']


def test_configured_api_accepts_only_valid_grounded_plan(tmp_path,monkeypatch):
    import app.main as main
    from app.rag.generation import AnswerService,DeepSeekProvider
    from app.rag.settings import RagSettings
    client,_,_,_=setup_service(tmp_path,monkeypatch)
    settings=RagSettings(api_key='secret-for-mock')
    def handler(req):
        context=json.loads(json.loads(req.content)['messages'][1]['content'])['untrusted_context']
        from app.rag.context import default_plan
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(default_plan(context))}}]})
    monkeypatch.setattr(main,'get_rag_service',lambda:AnswerService(settings,DeepSeekProvider(settings,transport=httpx.MockTransport(handler))))
    response=client.post('/api/v2/recommend',json={**payload(),'query':'披萨','generate_answer':True})
    assert response.status_code==200 and response.json()['answer']['mode']=='deepseek_plan'
    assert 'secret-for-mock' not in response.text


def test_bad_config_isolated_and_status_has_no_credentials(tmp_path,monkeypatch):
    import app.main as main
    client,_,_,_=setup_service(tmp_path,monkeypatch)
    def fail():raise ValueError('private-credential-do-not-echo')
    monkeypatch.setattr(main,'get_rag_service',fail)
    response=client.post('/api/v2/recommend',json={**payload(),'generate_answer':True})
    assert response.status_code==200 and response.json()['recommendations']
    assert response.json()['answer']['reason']=='invalid_configuration'
    assert 'private-credential-do-not-echo' not in response.text
    status=client.get('/api/v2/rag/status')
    assert status.status_code==200 and 'private-credential-do-not-echo' not in status.text
