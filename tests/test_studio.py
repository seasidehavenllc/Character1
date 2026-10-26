import json
from corvis.studio import CreativeStudio


def test_studio_persists_plans_and_reports_real_tool_detection(tmp_path):
    s = CreativeStudio(tmp_path / 'data', tmp_path / 'workspace', {})
    job = s.create_job({'title':'Launch film','kind':'video','prompt':'Make a 20 second cinematic launch film'})
    assert job['status'] == 'planned'
    assert job['progress'] == 0
    assert len(job['plan']) >= 3
    assert 'not started' in job['events'][0]['message']
    s2 = CreativeStudio(tmp_path / 'data', tmp_path / 'workspace', {})
    assert s2.get(job['id'])['title'] == 'Launch film'
    apps = s2.applications()
    assert any(a['id'] == 'blender' and isinstance(a['installed'], bool) for a in apps)


def test_studio_requires_brief_and_rejects_unknown_type(tmp_path):
    s = CreativeStudio(tmp_path / 'data', tmp_path / 'workspace')
    try: s.create_job({'kind':'image','prompt':' '})
    except ValueError as e: assert 'Describe' in str(e)
    else: assert False
    try: s.create_job({'kind':'unknown','prompt':'something'})
    except ValueError as e: assert 'Unsupported' in str(e)
    else: assert False


def test_studio_cancel_and_approval_are_truthful(tmp_path):
    s = CreativeStudio(tmp_path / 'data', tmp_path / 'workspace')
    j = s.create_job({'kind':'3d','prompt':'Model a bracket'})
    assert s.cancel(j['id'])['status'] == 'cancelled'
    assert s.get(j['id'])['progress'] == 0


