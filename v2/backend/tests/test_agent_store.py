import pytest


def test_turns_persist_are_idempotent_and_reject_stale_versions(tmp_path):
    from app.agent.store import SessionRepository,SessionError
    repo=SessionRepository(tmp_path/'sessions.sqlite3',clock=lambda:100)
    session=repo.create({'latitude':0,'longitude':0})
    calls=[]
    def handler(state):calls.append(1);return {'status':'completed','message':'ok'}
    payload={'turn_id':'one','expected_version':0,'message':'coffee'}
    first=repo.turn(session['session_id'],payload,handler)
    assert first['version']==1 and len(calls)==1
    assert SessionRepository(repo.path,clock=lambda:101).turn(session['session_id'],payload,handler)==first
    assert len(calls)==1
    with pytest.raises(SessionError) as conflict:repo.turn(session['session_id'],{**payload,'message':'pizza'},handler)
    assert conflict.value.status==409
    with pytest.raises(SessionError):repo.turn(session['session_id'],{**payload,'turn_id':'two'},handler)
    assert repo.get(session['session_id'])['version']==1


def test_expired_sessions_and_turn_limit(tmp_path):
    from app.agent.store import SessionRepository,SessionError
    now=[100]
    repo=SessionRepository(tmp_path/'sessions.sqlite3',clock=lambda:now[0],max_turns=1,ttl=10)
    session=repo.create({'latitude':0,'longitude':0})
    repo.turn(session['session_id'],{'turn_id':'one','expected_version':0},lambda s:{'message':'ok'})
    with pytest.raises(SessionError):repo.turn(session['session_id'],{'turn_id':'two','expected_version':1},lambda s:{})
    now[0]=111
    with pytest.raises(SessionError) as expired:repo.get(session['session_id'])
    assert expired.value.status==410


def test_two_concurrent_turns_cannot_overwrite_same_version(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.agent.store import SessionRepository,SessionError
    repo=SessionRepository(tmp_path/'sessions.sqlite3')
    session=repo.create({'latitude':0,'longitude':0})
    def execute(index):
        try:return repo.turn(session['session_id'],{'turn_id':str(index),'expected_version':0},lambda s:{'message':'ok'})['version']
        except SessionError as error:return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(execute,[1,2]))==[1,409]
