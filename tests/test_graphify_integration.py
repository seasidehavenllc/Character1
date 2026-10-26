import os
from pathlib import Path
import pytest
from corvis.graphify_integration import GraphifyIntegration


def test_graphify_status_and_workspace_path_guard(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    project = workspace / 'demo'
    project.mkdir()
    graph = project / 'graphify-out'
    graph.mkdir()
    (graph / 'graph.json').write_text('{"nodes": [], "edges": []}', encoding='utf-8')
    integration = GraphifyIntegration(workspace, executable='/fake/graphify')
    status = integration.status('demo')
    assert status['ready'] is True
    assert status['artifacts']['graph_json'] is True
    with pytest.raises(ValueError):
        integration.project_path('../outside')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (workspace / 'escape').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        integration.project_path('escape')


def test_graphify_query_requires_graph_and_limits_question(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    integration = GraphifyIntegration(workspace, executable='/fake/graphify')
    with pytest.raises(ValueError, match='Build'):
        integration.query('Where is auth?')
    with pytest.raises(ValueError, match='1,200'):
        integration.query('x' * 1201)


def test_graphify_commands_use_argv_no_shell_and_store_output(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    project = workspace / 'demo'
    project.mkdir()
    out = project / 'graphify-out'
    out.mkdir()
    (out / 'graph.json').write_text('{}', encoding='utf-8')
    integration = GraphifyIntegration(workspace, executable='/fake/graphify')
    seen = {}
    class Result:
        returncode = 0
        stdout = 'query result'
        stderr = ''
    def fake_run(args, **kwargs):
        seen['args'] = args
        seen.update(kwargs)
        return Result()
    monkeypatch.setattr('corvis.graphify_integration.subprocess.run', fake_run)
    result = integration.query('auth; echo no', 'demo')
    assert result['output'] == 'query result'
    assert seen['args'] == ['/fake/graphify', 'query', 'auth; echo no']
    assert seen['shell'] is False
    assert seen['cwd'] == str(project.resolve())


def test_graphify_agent_tools_are_registered(tmp_path):
    from corvis.tools.base import ToolContext, ToolRegistry
    from corvis.safety import CommandPolicy, Workspace
    from corvis.tools.graphify_tools import register
    workspace = Workspace(tmp_path)
    ctx = ToolContext(workspace=workspace, policy=CommandPolicy(workspace), approver=lambda _: False)
    registry = ToolRegistry(ctx)
    register(registry, ctx)
    tools = registry.all_tools()
    assert {'graphify_status', 'graphify_build', 'graphify_query', 'graphify_explain', 'graphify_path'} <= set(tools)
    assert tools['graphify_build'].needs_approval is True
