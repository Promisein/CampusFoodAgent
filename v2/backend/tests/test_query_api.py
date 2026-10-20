import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_personalized_api import payload, setup_service


def test_same_user_query_changes_results_before_historical_fusion(tmp_path, monkeypatch):
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    coffee = client.post('/api/v2/recommend', json={**payload(), 'query': '咖啡'}).json()
    pizza = client.post('/api/v2/recommend', json={**payload(), 'query': '想吃披萨'}).json()
    assert [r['business_id'] for r in coffee['recommendations']] == ['B']
    assert [r['business_id'] for r in pizza['recommendations']] == ['C']
    assert pizza['metadata']['query_used_for_ranking']
    assert 'query' in pizza['recommendations'][0]['channel_scores']
    assert pizza['metadata']['intent']['include_categories'] == ['pizza']


@pytest.mark.parametrize('user', ['u', 'unknown', None])
def test_limits_unknown_users_and_unsupported_hard_conditions(tmp_path, monkeypatch, user):
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    data = {**payload(), 'user_id': user, 'query': '披萨，价格等级1'}
    body = client.post('/api/v2/recommend', json=data).json()
    assert body['recommendations'] == []
    assert body['metadata']['resolved_constraints']['max_price_level'] == 1
    body = client.post('/api/v2/recommend', json={**data, 'query': '预算20元吃披萨'}).json()
    assert body['recommendations'] == []
    assert body['metadata']['intent']['needs_clarification']


def test_model_failure_and_evidence_failure_keep_query_constraints(tmp_path, monkeypatch):
    from app.serving.model import ServingRepository
    import app.main as main
    client, source, _, _ = setup_service(tmp_path, monkeypatch)
    monkeypatch.setattr(main, 'serving_repository', ServingRepository(tmp_path/'missing'))
    (source/'representative_reviews.jsonl').unlink()
    body = client.post('/api/v2/recommend', json={**payload(), 'query': '披萨 安静'}).json()
    assert [r['business_id'] for r in body['recommendations']] == ['C']
    assert 'evidence_unavailable' in body['metadata']['warnings']
    assert body['recommendations'][0]['evidence_status'] == 'insufficient'
    assert not body['recommendations'][0]['evidence']


def test_query_evidence_scoped_to_selected_business_and_concurrent_requests(tmp_path, monkeypatch):
    client, source, _, _ = setup_service(tmp_path, monkeypatch)
    reviews = [{'review_id': 'wrong', 'business_id': 'C', 'user_id': 'x', 'rating': 5,
                'review_date': '2020-01-01', 'useful': 0, 'text': 'Very quiet pizza.', 'source': 'fixture'},
               {'review_id': 'right', 'business_id': 'B', 'user_id': 'x', 'rating': 2,
                'review_date': '2020-01-01', 'useful': 0, 'text': 'Not quiet at all.', 'source': 'fixture'}]
    (source/'representative_reviews.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in reviews))
    def run(query):
        body = client.post('/api/v2/recommend', json={**payload(), 'query': query}).json()
        # Each call now creates a distinct exposure; ranking remains deterministic.
        assert body['metadata'].pop('request_id')
        return body
    queries = ['咖啡 安静', '披萨'] * 5
    expected = {q: run(q) for q in set(queries)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, queries))
    assert results == [expected[q] for q in queries]
    coffee = expected['咖啡 安静']['recommendations'][0]
    assert coffee['evidence'][0]['document_id'] == 'right'
    assert coffee['evidence_status'] == 'related_mentions'
    assert all('quiet restaurant' not in r.lower() for r in coffee['reasons'])


def test_query_filter_applied_before_channel_budget(tmp_path, monkeypatch):
    from app.models import RecommendationRequest
    from app.serving.model import RequestRecallIndex, ServingRepository
    client, _, out, businesses = setup_service(tmp_path, monkeypatch)
    index = RequestRecallIndex(ServingRepository(out).load(), businesses,
                               RecommendationRequest(**payload()), allowed_ids={'C'})
    assert [r['business_id'] for r in index.recommend('u', 'popularity', limit=1)] == ['C']


def test_query_channel_failure_keeps_filtered_history_and_warns(tmp_path, monkeypatch):
    import app.personalized as service
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise TimeoutError('query channel unavailable')
    monkeypatch.setattr(service, 'recall_query', fail)
    body = client.post('/api/v2/recommend', json={**payload(), 'query': '披萨'}).json()
    assert [r['business_id'] for r in body['recommendations']] == ['C']
    assert 'query_unavailable' in body['metadata']['warnings']


@pytest.mark.parametrize('query', ['pizza price level < 2', 'pizza price level > 2', 'pizza within 500 m', 'pizza between 2 and 5 km'])
def test_unsupported_numeric_requests_do_not_return_false_matches(tmp_path, monkeypatch, query):
    client, _, _, _ = setup_service(tmp_path, monkeypatch)
    response = client.post('/api/v2/recommend', json={**payload(), 'query': query})
    assert response.status_code == 200
    body = response.json()
    assert body['engine'] == 'query_needs_clarification'
    assert body['metadata']['intent']['needs_clarification']
    assert not body['recommendations']
