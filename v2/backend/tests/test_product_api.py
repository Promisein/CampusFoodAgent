from uuid import uuid4

from fastapi.testclient import TestClient


def setup_product(tmp_path,monkeypatch):
    import app.main as main
    from app.product.accounts import AccountStore
    from test_personalized_api import setup_service
    client,*_=setup_service(tmp_path,monkeypatch)
    store=AccountStore(tmp_path/'accounts.sqlite3')
    monkeypatch.setattr(main,'get_product_account_store',lambda:store)
    return client,store,main


def register(client,handle):
    result=client.post('/api/v2/product/register',json={'handle':handle,'password':'long-password-2026'})
    assert result.status_code==201,result.text
    return result.json()


def test_account_cookie_csrf_and_owned_agent_flow(tmp_path,monkeypatch):
    client,store,main=setup_product(tmp_path,monkeypatch)
    assert client.get('/api/v2/product/me').status_code==401
    registered=register(client,'alice_1')
    csrf=registered['csrf_token']
    assert registered['account']['handle']=='alice_1'
    assert 'HttpOnly' in client.post('/api/v2/product/login',json={'handle':'alice_1','password':'long-password-2026'}).headers['set-cookie']
    me=client.get('/api/v2/product/me')
    assert me.status_code==200 and me.json()['account']['id']==registered['account']['id']
    csrf=me.json()['csrf_token']
    params={'latitude':0,'longitude':0,'city':'Tampa','radius_km':10,'max_price_level':3,'top_k':5}
    assert client.post('/api/v2/product/sessions',json=params).status_code==403
    assert client.post('/api/v2/product/sessions',json={**params,'user_id':'yelp-forged'},headers={'X-CSRF-Token':csrf}).status_code==422
    assert client.post('/api/v2/product/sessions',json={**params,'city':'New Orleans'},headers={'X-CSRF-Token':csrf}).status_code==422
    created=client.post('/api/v2/product/sessions',json=params,headers={'X-CSRF-Token':csrf})
    assert created.status_code==201,created.text
    session=created.json()
    assert session['scope']=='account_owned_product'
    assert store.owns_conversation(registered['account']['id'],session['session_id'])
    internal=main.get_agent_repository().get(session['session_id'])
    assert internal['state']['context']['user_id']==registered['account']['id']
    payload={'turn_id':str(uuid4()),'expected_version':0,'message':'咖啡','use_model':False}
    sent=client.post(f"/api/v2/product/sessions/{session['session_id']}/turns",json=payload,headers={'X-CSRF-Token':csrf})
    assert sent.status_code==200 and sent.json()['recommendations']
    assert sent.json()['scope']=='account_owned_product'
    favorite_payload={**payload,'turn_id':str(uuid4()),'expected_version':1,'message':'收藏第一家'}
    saved=client.post(f"/api/v2/product/sessions/{session['session_id']}/turns",json=favorite_payload,headers={'X-CSRF-Token':csrf})
    assert saved.status_code==200 and saved.json()['status']=='completed'
    assert len(client.get('/api/v2/product/favorites').json()['favorites'])==1
    business_id=client.get('/api/v2/product/favorites').json()['favorites'][0]['business_id']
    assert client.delete('/api/v2/product/favorites/'+business_id).status_code==403
    removed=client.delete('/api/v2/product/favorites/'+business_id,headers={'X-CSRF-Token':csrf})
    assert removed.status_code==200 and removed.json()=={'removed':True}
    again=client.delete('/api/v2/product/favorites/'+business_id,headers={'X-CSRF-Token':csrf})
    assert again.status_code==200 and again.json()=={'removed':False}
    assert client.get('/api/v2/product/favorites').json()['favorites']==[]
    assert client.get('/api/v2/product/history').json()['events'][0]['event_type']=='unfavorite'
    assert client.get('/api/v2/product/conversations').json()['conversations'][0]['session_id']==session['session_id']
    retry=client.post(f"/api/v2/product/sessions/{session['session_id']}/turns",json=favorite_payload,headers={'X-CSRF-Token':csrf})
    assert retry.status_code==200 and retry.json()==saved.json()
    assert client.get('/api/v2/product/favorites').json()['favorites']==[]
    resave={**favorite_payload,'turn_id':str(uuid4()),'expected_version':2}
    assert client.post(f"/api/v2/product/sessions/{session['session_id']}/turns",
        json=resave,headers={'X-CSRF-Token':csrf}).status_code==200
    assert len(client.get('/api/v2/product/favorites').json()['favorites'])==1


def test_other_account_cannot_read_or_write_agent_session(tmp_path,monkeypatch):
    alice,_,main=setup_product(tmp_path,monkeypatch)
    alice_auth=register(alice,'alice_1')
    context={'latitude':0,'longitude':0,'radius_km':10}
    made=alice.post('/api/v2/product/sessions',json=context,headers={'X-CSRF-Token':alice_auth['csrf_token']}).json()
    bob=TestClient(main.app)
    bob_auth=register(bob,'bob_001')
    owner=alice_auth['account']['id']
    exposure=main.get_event_repository().record_exposure({'user_id':owner,'query':'coffee'},
        {'recommendations':[{'business_id':'private-cafe','name':'Private Cafe','city':'Tampa',
                             'rating':4,'price_level':2}]})
    main.get_event_repository().record_event({'event_id':str(uuid4()),'request_id':exposure,
        'user_id':owner,'business_id':'private-cafe','event_type':'favorite'})
    sid=made['session_id']
    assert bob.get('/api/v2/product/sessions/'+sid).status_code==404
    denied=bob.post('/api/v2/product/sessions/'+sid+'/turns',json={'turn_id':'x','expected_version':0,'message':'收藏第一家'},headers={'X-CSRF-Token':bob_auth['csrf_token']})
    assert denied.status_code==404
    assert bob.get('/api/v2/product/conversations').json()['conversations']==[]
    assert bob.get('/api/v2/product/favorites').json()['favorites']==[]
    assert bob.delete('/api/v2/product/favorites/private-cafe',
        headers={'X-CSRF-Token':bob_auth['csrf_token']}).json()=={'removed':False}
    assert len(alice.get('/api/v2/product/favorites').json()['favorites'])==1
    assert alice.get('/api/v2/product/sessions/'+sid).status_code==200
    out=alice.post('/api/v2/product/logout',headers={'X-CSRF-Token':alice_auth['csrf_token']})
    assert out.status_code==200 and alice.get('/api/v2/product/me').status_code==401


def test_product_mode_closes_unprotected_legacy_routes(tmp_path,monkeypatch):
    client,_,_=setup_product(tmp_path,monkeypatch)
    monkeypatch.setenv('CAMPUSFOOD_MODE','product')
    for path in ['/demo','/agent','/api/v2/agent/sessions/unknown','/api/v2/events/metrics','/api/v2/users/yelp-user/favorites']:
        response=client.get(path)
        assert response.status_code==404,(path,response.text)
    assert client.post('/api/v2/recommend',json={}).status_code==404
    assert client.post('/api/v2/agent/sessions',json={'latitude':0,'longitude':0}).status_code==404
    assert client.get('/app').status_code==200
    assert client.get('/api/v2/system/status').json()['agent']['production_auth'] is True


def test_expired_conversations_are_not_offered_as_recoverable(tmp_path,monkeypatch):
    client,_,main=setup_product(tmp_path,monkeypatch)
    auth=register(client,'alice_1')
    repository=main.get_agent_repository()
    now=[repository.clock()]
    repository.clock=lambda:now[0]
    made=client.post('/api/v2/product/sessions',json={'latitude':0,'longitude':0},
        headers={'X-CSRF-Token':auth['csrf_token']}).json()
    assert len(client.get('/api/v2/product/conversations').json()['conversations'])==1
    now[0]+=repository.ttl+1
    assert client.get('/api/v2/product/conversations').json()['conversations']==[]
    assert client.get('/api/v2/product/sessions/'+made['session_id']).status_code==410
