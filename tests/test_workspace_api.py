from starlette.testclient import TestClient
from corvis.web.server import create_app


def test_workspace_crud_and_model_inventory(tmp_path):
    cfg = {'data_dir': str(tmp_path), 'web': {'default_workspace': str(tmp_path / 'workspace')},
           'memory': {'enabled': False}, 'computer': {'enabled': False},
           'llm': {'base_url': 'http://127.0.0.1:1/v1', 'model': 'test-model'}}
    app = create_app(cfg, tmp_path)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        h = {'X-Corvis': '1'}
        assert client.get('/workspace').status_code == 200
        created = client.post('/api/workspace/notes', headers=h, json={'title':'Idea','content':'remember this'})
        assert created.status_code == 201
        item = created.json()['item']
        assert client.get('/api/workspace/notes', headers=h).json()['items'][0]['content'] == 'remember this'
        patched = client.patch(f"/api/workspace/notes/{item['id']}", headers=h, json={'title':'Renamed'})
        assert patched.json()['item']['title'] == 'Renamed'
        assert client.delete(f"/api/workspace/notes/{item['id']}", headers=h).json()['ok']
        assert client.get('/api/models', headers=h).status_code == 200
        assert client.post('/api/models/compare', headers=h, json={'prompt':'test','models':[]}).status_code == 400
