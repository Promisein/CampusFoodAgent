from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.demo import register_demo_routes


def test_local_demo_serves_both_paths_without_remote_assets():
    app = FastAPI()
    register_demo_routes(app)
    client = TestClient(app)
    first = client.get('/')
    assert first.status_code == 200
    assert first.headers['content-type'].startswith('text/html')
    assert client.get('/demo').text == first.text
    assert '/api/v2/recommend' in first.text
    assert '/api/v2/events' in first.text
    assert '/api/v2/system/status' in first.text
    assert 'innerHTML' not in first.text
    assert 'https://' not in first.text
