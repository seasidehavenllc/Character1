from pathlib import Path
from starlette.testclient import TestClient
from corvis.web.server import create_app


def test_studio_api_and_page(tmp_path):
    cfg = {'data_dir': str(tmp_path), 'web': {'default_workspace': str(tmp_path / 'workspace')},
           'memory': {'enabled': False}, 'computer': {'enabled': False}}
    app = create_app(cfg, tmp_path)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        headers = {'X-Corvis': '1'}
        assert client.get('/studio').status_code == 200
        status = client.get('/api/studio', headers=headers)
        assert status.status_code == 200
        assert 'applications' in status.json() and 'models' in status.json()
        created = client.post('/api/studio/jobs', headers=headers,
                              json={'kind':'design','title':'Poster','prompt':'Design a poster'} )
        assert created.status_code == 201
        jid = created.json()['job']['id']
        assert client.get(f'/api/studio/jobs/{jid}', headers=headers).json()['job']['status'] == 'planned'
        assert client.post(f'/api/studio/jobs/{jid}/approve', headers=headers, json={}).json()['job']['status'] == 'waiting_approval'
        assert 'blocked' in client.get(f'/api/studio/jobs/{jid}', headers=headers).json()['job']['execution_note']
        assert client.post(f'/api/studio/jobs/{jid}/cancel', headers=headers, json={}).json()['job']['status'] == 'cancelled'


def test_graphify_api_is_workspace_scoped_and_status_is_visible(tmp_path):
    cfg = {'data_dir': str(tmp_path), 'web': {'default_workspace': str(tmp_path / 'workspace')},
           'memory': {'enabled': False}, 'computer': {'enabled': False}}
    app = create_app(cfg, tmp_path)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        headers = {'X-Corvis': '1'}
        status = client.get('/api/graphify', headers=headers)
        assert status.status_code == 200
        assert status.json()['id'] == 'graphify'
        blocked = client.post('/api/graphify/query', headers=headers, json={'question':'test','project':'../outside'})
        assert blocked.status_code == 400
        assert 'Parent-directory' in blocked.json()['error']
