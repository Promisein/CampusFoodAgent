from pathlib import Path

from fastapi.testclient import TestClient

from test_personalized_api import setup_service, payload


def test_exposure_feedback_and_favorites_close_the_api_loop(tmp_path, monkeypatch):
    import app.main as main
    from app.events import EventRepository
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    events=EventRepository(tmp_path/'events.sqlite3')
    monkeypatch.setattr(main,'get_event_repository',lambda:events)
    body=client.post('/api/v2/recommend',json={**payload(),'query':'披萨'}).json()
    request_id=body['metadata']['request_id'];item=body['recommendations'][0]['business_id']
    feedback={'event_id':'one','request_id':request_id,'user_id':'u','business_id':item,'event_type':'favorite'}
    assert client.post('/api/v2/events',json=feedback).status_code==200
    assert client.post('/api/v2/events',json=feedback).status_code==200
    assert client.get('/api/v2/users/u/favorites').json()['favorites']
    assert client.post('/api/v2/events',json={**feedback,'event_id':'foreign','business_id':'A'}).status_code==404


def test_optional_search_and_ranker_failures_preserve_legal_recommendations(tmp_path,monkeypatch):
    import app.main as main
    from app.ranking.learned import RankingRepository
    client,_,_,_=setup_service(tmp_path,monkeypatch)
    class BrokenSearch:
        def recommend(self,*args,**kwargs):raise TimeoutError('offline')
    monkeypatch.setattr(main,'search_repository',BrokenSearch())
    monkeypatch.setattr(main,'ranking_repository',RankingRepository(tmp_path/'missing'))
    query=client.post('/api/v2/recommend',json={**payload(),'query':'披萨'}).json()
    assert [r['business_id'] for r in query['recommendations']]==['C']
    assert 'semantic_unavailable' in query['metadata']['warnings']
    neutral=client.post('/api/v2/recommend',json=payload()).json()
    assert neutral['recommendations'] and 'ranker_unavailable' in neutral['metadata']['warnings']


def test_unavailable_event_store_does_not_break_recommendations(tmp_path,monkeypatch):
    import app.main as main
    client,_,_,_=setup_service(tmp_path,monkeypatch)
    def broken():raise OSError('unwritable')
    monkeypatch.setattr(main,'get_event_repository',broken)
    body=client.post('/api/v2/recommend',json={**payload(),'query':'披萨'}).json()
    assert body['recommendations']
    assert 'event_store_unavailable' in body['metadata']['warnings']


def test_demo_and_status_are_available():
    import app.main as main
    client=TestClient(main.app)
    assert client.get('/demo').status_code==200
    result=client.get('/api/v2/system/status')
    assert result.status_code==200
    assert result.json()['scope']=='local_offline_demo'


def test_malformed_rank_manifest_preserves_rrf_and_status(tmp_path,monkeypatch):
    import app.main as main
    from app.ranking.learned import RankingRepository
    client,_,_,_=setup_service(tmp_path,monkeypatch)
    directory=tmp_path/'broken';directory.mkdir()
    (directory/'experiment_manifest.json').write_text('[]')
    monkeypatch.setattr(main,'ranking_repository',RankingRepository(directory))
    body=client.post('/api/v2/recommend',json=payload()).json()
    assert body['recommendations'] and 'ranker_unavailable' in body['metadata']['warnings']
    assert client.get('/api/v2/system/status').json()['ranker']['available'] is False
