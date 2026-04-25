from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_session_and_chat_roundtrip():
    created = client.post('/sessions', json={'client_timezone': 'America/New_York'})
    assert created.status_code == 200
    body = created.json()
    assert body['success'] is True
    session_id = body['data']['session_id']

    chat = client.post('/chat', json={'session_id': session_id, 'message': 'Astoria 的安全怎么样？', 'debug': True})
    assert chat.status_code == 200
    payload = chat.json()
    assert payload['success'] is True
    assert payload['data']['message_type'] == 'answer'
    assert payload['data']['profile_snapshot']['target_area']['area_name'] == 'Astoria'
    assert payload['data']['debug']['trace_summary']


def test_metrics_requires_session():
    response = client.get('/areas/QN0101/metrics?session_id=missing')
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
