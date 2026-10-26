"""Corvis agent tools for the optional local Graphify knowledge graph."""
from __future__ import annotations

import json
from ..graphify_integration import GraphifyIntegration
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    def integration() -> GraphifyIntegration:
        return GraphifyIntegration(ctx.workspace.root)

    def graphify_status() -> str:
        return json.dumps(integration().status("."), ensure_ascii=False, indent=2)

    def graphify_build() -> str:
        """Build/update the local graph. Approval is required because indexing can read project docs."""
        result = integration().build(".")
        return json.dumps(result, ensure_ascii=False, indent=2)

    def graphify_query(question: str) -> str:
        result = integration().query(question, ".")
        return result.get("output") or "Graphify returned no textual result."

    def graphify_explain(concept: str) -> str:
        result = integration().explain(concept, ".")
        return result.get("output") or "Graphify returned no textual result."

    def graphify_path(source: str, target: str) -> str:
        result = integration().path(source, target, ".")
        return result.get("output") or "Graphify returned no textual result."

    reg.register(Tool("graphify_status", "Check whether Graphify is installed and a knowledge graph exists for the current workspace.", params([]), graphify_status))
    reg.register(Tool("graphify_build", "Build/update a local Graphify knowledge graph for the current workspace. Requires owner approval because project files may be parsed and optional semantic backends may be configured.", params([]), graphify_build, needs_approval=True))
    reg.register(Tool("graphify_query", "Ask a question against the current workspace's existing Graphify knowledge graph. Prefer this for code architecture and file-relationship questions when a graph exists.", params(["question"], question={"type": "string", "maxLength": 1200}), graphify_query))
    reg.register(Tool("graphify_explain", "Explain a symbol or concept using the current workspace's Graphify graph, including connections and source references.", params(["concept"], concept={"type": "string", "maxLength": 300}), graphify_explain))
    reg.register(Tool("graphify_path", "Trace the graph path between two code symbols or concepts in the current workspace.", params(["source", "target"], source={"type": "string", "maxLength": 300}, target={"type": "string", "maxLength": 300}), graphify_path))
