import json
from corvis.workspace_features import WorkspaceStore


def test_notes_tasks_documents_and_drafts_persist(tmp_path):
    s = WorkspaceStore(tmp_path)
    note = s.create('notes', {'title':'Idea', 'content':'A durable thought'})
    task = s.create('tasks', {'title':'Ship it', 'description':'Run tests', 'priority':'high'})
    doc = s.create('documents', {'title':'Spec', 'content':'# Draft'})
    draft = s.create('email_drafts', {'title':'Intro', 'to':'test@example.com', 'subject':'Hello', 'body':'Draft only'})
    event = s.create('events', {'title':'Review', 'start_at':'2026-10-27T10:00', 'end_at':'2026-10-27T10:30'})
    s.update('tasks', task['id'], {'status':'done'})
    s2 = WorkspaceStore(tmp_path)
    assert s2.list('notes')[0]['content'] == 'A durable thought'
    assert s2.list('documents')[0]['content'] == '# Draft'
    assert s2.list('email_drafts')[0]['to'] == 'test@example.com'
    assert s2.list('events')[0]['start_at'] == '2026-10-27T10:00'
    assert s2.list('tasks')[0]['status'] == 'done'
    assert s2.summary()['open_tasks'] == 0


def test_rejects_empty_title_and_invalid_status(tmp_path):
    s = WorkspaceStore(tmp_path)
    try:
        s.create('notes', {'title':'  '})
        assert False, 'expected validation error'
    except ValueError: pass
    try:
        s.create('tasks', {'title':'Bad', 'status':'mystery'})
        assert False, 'expected validation error'
    except ValueError: pass


def test_delete_and_unknown_collection(tmp_path):
    s = WorkspaceStore(tmp_path)
    note = s.create('notes', {'title':'Temporary'})
    assert s.delete('notes', note['id']) is True
    assert s.delete('notes', note['id']) is False
    try:
        s.list('secrets')
        assert False, 'expected validation error'
    except ValueError: pass
