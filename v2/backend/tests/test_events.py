from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.events import EventRepository, register_event_routes


def exposed(tmp_path, user='alice'):
    repo = EventRepository(tmp_path / 'events.sqlite')
    request_id = repo.record_exposure({'user_id': user, 'query': 'coffee'}, {
        'recommendations': [{'business_id': 'cafe', 'name': 'Cafe'}]})
    UUID(request_id)
    return repo, request_id


def event(exposure_id, **kwargs):
    return {'event_id': 'one', 'request_id': exposure_id, 'user_id': 'alice',
            'business_id': 'cafe', 'event_type': 'click', **kwargs}


def test_exposure_persists_and_event_retries_are_idempotent(tmp_path):
    repo, request_id = exposed(tmp_path)
    first = repo.record_event(event(request_id))
    restored = EventRepository(tmp_path / 'events.sqlite')
    assert restored.record_event(event(request_id)) == first
    assert len(restored.history('alice')) == 1
    assert first['created_at']
    with pytest.raises(ValueError):
        repo.record_event(event(request_id, event_type='dislike'))


@pytest.mark.parametrize('override', [{'user_id': 'bob'}, {'business_id': 'external'},
    {'request_id': 'unknown'}, {'event_type': 'rating', 'rating': 6},
    {'event_type': 'rating'}, {'rating': 4}, {'created_at': 'yesterday'},
    {'event_type': 'unknown'}])
def test_only_matching_exposed_items_and_valid_payloads_are_accepted(tmp_path, override):
    repo, request_id = exposed(tmp_path)
    with pytest.raises(ValueError):
        repo.record_event(event(request_id, **override))
    assert repo.history('alice') == []


def test_parallel_retries_favorites_history_and_explicit_metric_denominators(tmp_path):
    repo, request_id = exposed(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: repo.record_event(event(request_id)), range(24)))
    assert all(item == results[0] for item in results)
    for event_id, kind in [('i', 'impression'), ('f', 'favorite'), ('r', 'rating')]:
        repo.record_event(event(request_id, event_id=event_id, event_type=kind,
                                **({'rating': 5} if kind == 'rating' else {})))
    assert repo.favorites('alice')[0]['business_id'] == 'cafe'
    assert repo.favorites('bob') == []
    assert len(repo.history('alice', limit=2)) == 2
    assert repo.metrics()['event_counts'] == {'impression': 1, 'click': 1, 'favorite': 1, 'dislike': 0, 'rating': 1}
    assert repo.metrics()['exposure_requests'] == 1
    assert repo.metrics()['exposed_items'] == 1
    assert repo.metrics()['ctr'] == 1
    assert repo.metrics()['ctr_denominator'] == 'impression_events'


def test_anonymous_exposure_cannot_be_used_by_named_user(tmp_path):
    repo, request_id = exposed(tmp_path, user=None)
    repo.record_event(event(request_id, user_id=None))
    with pytest.raises(ValueError):
        repo.record_event(event(request_id, event_id='bad'))


def test_unique_ctr_counts_only_clicked_impressed_exposure_items(tmp_path):
    repo, request_id = exposed(tmp_path)
    repo.record_event(event(request_id))
    assert repo.metrics()['bounded_unique_ctr'] is None
    assert repo.metrics()['clicked_impressed_exposure_items'] == 0
    repo.record_event(event(request_id, event_id='view', event_type='impression'))
    repo.record_event(event(request_id, event_id='repeat-view', event_type='impression'))
    repo.record_event(event(request_id, event_id='repeat-click'))
    second = repo.record_exposure({'user_id': 'alice'}, {'recommendations': [{'business_id': 'cafe'}]})
    repo.record_event(event(second, event_id='second-view', event_type='impression'))
    metrics = repo.metrics()
    assert metrics['impressed_exposure_items'] == 2
    assert metrics['clicked_impressed_exposure_items'] == 1
    assert metrics['bounded_unique_ctr'] == 0.5
    assert metrics['event_counts']['click'] == 2
    assert metrics['event_counts']['impression'] == 3


def test_routes_validate_and_expose_local_demo_data(tmp_path):
    repo, request_id = exposed(tmp_path)
    app = FastAPI()
    register_event_routes(app, lambda: repo)
    client = TestClient(app)
    assert client.post('/api/v2/events', json=event(request_id)).status_code == 200
    assert client.post('/api/v2/events', json=event(request_id, rating=3)).status_code == 422
    assert client.post('/api/v2/events', json=event(request_id, event_type='dislike')).status_code == 409
    assert client.post('/api/v2/events', json=event(request_id, event_id='bad', business_id='other')).status_code == 404
    assert client.get('/api/v2/users/alice/history').json()['events'][0]['business_id'] == 'cafe'
    assert client.get('/api/v2/users/alice/history?limit=1001').status_code == 422
    assert client.get('/api/v2/users/alice/favorites').json()['favorites'] == []
    assert client.get('/api/v2/events/metrics').json()['scope'] == 'local_demo_descriptive'
