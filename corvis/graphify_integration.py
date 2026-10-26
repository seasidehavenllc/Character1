"""Optional, local-first integration with Graphify-Labs/graphify.

Corvis never installs Graphify implicitly. All subprocesses use argv (never a shell),
are bounded by timeouts, and operate only inside the configured workspace.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

GRAPHIFY_URL = "https://github.com/Graphify-Labs/graphify"


class GraphifyIntegration:
    def __init__(self, workspace: str | Path, executable: str | None = None):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.executable = executable or shutil.which("graphify")

    def project_path(self, relative: str | None = ".") -> Path:
        value = str(relative or ".").strip()
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            raise ValueError("Choose a project folder relative to Corvis's configured workspace.")
        if any(part == ".." for part in candidate.parts):
            raise ValueError("Parent-directory traversal is not allowed.")
        resolved = (self.workspace / candidate).resolve()
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise ValueError("The selected folder must remain inside the configured workspace.")
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError("That project folder does not exist inside the workspace.")
        return resolved

    def _artifacts(self, project: Path) -> dict[str, Any]:
        out = project / "graphify-out"
        return {
            "graph_json": (out / "graph.json").is_file(),
            "report": (out / "GRAPH_REPORT.md").is_file(),
            "visualization": (out / "graph.html").is_file(),
            "output_dir": str(out),
        }

    def status(self, relative: str | None = ".") -> dict[str, Any]:
        project = self.project_path(relative)
        artifacts = self._artifacts(project)
        installed = bool(self.executable)
        return {
            "id": "graphify", "name": "Graphify knowledge graph", "url": GRAPHIFY_URL,
            "installed": installed, "executable": self.executable,
            "ready": installed and artifacts["graph_json"], "project": str(project),
            "project_relative": str(project.relative_to(self.workspace)) if project != self.workspace else ".",
            "artifacts": artifacts,
            "install_command": "uv tool install graphifyy",
            "note": ("Local graph found. Queries use the graph in this project." if installed and artifacts["graph_json"]
                     else "Graphify CLI is installed; build a graph for this project." if installed
                     else "Optional integration. Install the official graphifyy package to enable local code-graph queries."),
        }

    def _run(self, args: list[str], project: Path, timeout: int) -> dict[str, Any]:
        if not self.executable:
            raise RuntimeError("Graphify is not installed. Install it with: uv tool install graphifyy")
        try:
            result = subprocess.run(
                [self.executable, *args], cwd=str(project), capture_output=True,
                text=True, timeout=timeout, check=False, shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Graphify command timed out after {timeout} seconds.") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not launch Graphify: {exc}") from exc
        output = (result.stdout or "")
        if result.stderr:
            output += ("\n" if output else "") + "STDERR:\n" + result.stderr
        output = output[-80_000:]
        if result.returncode != 0:
            raise RuntimeError(f"Graphify exited with code {result.returncode}.\n{output}".strip())
        return {"ok": True, "returncode": result.returncode, "output": output}

    def build(self, relative: str | None = ".") -> dict[str, Any]:
        project = self.project_path(relative)
        result = self._run([".", "--no-viz"], project, timeout=300)
        result.update({"operation": "build", "status": self.status(relative)})
        return result

    def query(self, question: str, relative: str | None = ".") -> dict[str, Any]:
        question = str(question or "").strip()
        if not question or len(question) > 1200:
            raise ValueError("Enter a question up to 1,200 characters.")
        project = self.project_path(relative)
        if not self._artifacts(project)["graph_json"]:
            raise ValueError("Build a Graphify knowledge graph for this project before querying it.")
        result = self._run(["query", question], project, timeout=90)
        result.update({"operation": "query", "question": question})
        return result

    def explain(self, concept: str, relative: str | None = ".") -> dict[str, Any]:
        concept = str(concept or "").strip()
        if not concept or len(concept) > 300:
            raise ValueError("Enter a concept or symbol up to 300 characters.")
        project = self.project_path(relative)
        if not self._artifacts(project)["graph_json"]:
            raise ValueError("Build a Graphify knowledge graph for this project before explaining a concept.")
        result = self._run(["explain", concept], project, timeout=60)
        result.update({"operation": "explain", "concept": concept})
        return result

    def path(self, source: str, target: str, relative: str | None = ".") -> dict[str, Any]:
        source, target = str(source or "").strip(), str(target or "").strip()
        if not source or not target or len(source) > 300 or len(target) > 300:
            raise ValueError("Enter source and target concepts, each up to 300 characters.")
        project = self.project_path(relative)
        if not self._artifacts(project)["graph_json"]:
            raise ValueError("Build a Graphify knowledge graph for this project before tracing paths.")
        result = self._run(["path", source, target], project, timeout=60)
        result.update({"operation": "path", "source": source, "target": target})
        return result
