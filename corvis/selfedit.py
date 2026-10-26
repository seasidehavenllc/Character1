"""Self-editing: Corvis changes its own code safely.

1. Requires a clean Git tree (so nothing of yours gets mixed in).
2. Refuses to start from a leftover self-edit branch (that's how history gets tangled).
3. Creates a branch  corvis/self-edit-<time>.
4. Runs the coding agent with Corvis's own folder as the workspace.
5. Runs the test suite.
6. Shows you the diff summary. You approve -> merged. You decline -> branch kept, nothing merged.
7. Whatever happens (crash, Ctrl+C), you end up back on your original branch.
"""
from __future__ import annotations

import datetime
import subprocess
import sys
from typing import Callable

from .config import CORVIS_HOME, build_agent
from .tools.git_tools import git

BRANCH_PREFIX = "corvis/self-edit-"


def _ensure_repo() -> None:
    code, _ = git(CORVIS_HOME, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        git(CORVIS_HOME, "init")
        git(CORVIS_HOME, "add", "-A")
        git(CORVIS_HOME, "commit", "-m", "Initial Corvis snapshot")


def run_tests() -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"],
                          cwd=CORVIS_HOME, capture_output=True, text=True, errors="replace")
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]


def current_branch() -> str:
    _, out = git(CORVIS_HOME, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip()


def self_edit(task: str, cfg: dict, approver: Callable[[str], bool],
              auto_approve_commands: bool = False,
              should_stop: Callable[[], bool] = lambda: False, **agent_kwargs) -> str:
    _ensure_repo()
    code, status = git(CORVIS_HOME, "status", "--porcelain")
    if status.strip():
        return ("Self-edit needs a clean Git tree. Commit or stash your own changes first:\n"
                + status)

    original = current_branch()
    if original.startswith((BRANCH_PREFIX, "agent/self-edit-", "jarvis/self-edit-")):
        return (f"You're on a leftover self-edit branch ({original}), probably from an edit "
                "that was interrupted. Switch back first:\n  git checkout main\n"
                f"Then merge it if you want its changes:  git merge {original}")

    branch = BRANCH_PREFIX + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    git(CORVIS_HOME, "checkout", "-b", branch)

    try:
        agent = build_agent(CORVIS_HOME, cfg, approver=approver,
                            auto_approve=auto_approve_commands, **agent_kwargs)
        summary = agent.run(
            "You are editing your OWN source code (the Corvis project). Be careful: keep every "
            "existing feature working, keep tools registered through register(reg, ctx), and add "
            "or update tests in tests/ for what you change. Never write placeholder functions "
            "that return fixed strings; implement real behaviour or say what's missing.\n\n"
            "Task: " + task,
            should_stop=should_stop,
        )

        git(CORVIS_HOME, "add", "-A")
        _, changed = git(CORVIS_HOME, "status", "--porcelain")
        if not changed.strip() and not _branch_has_commits(original, branch):
            git(CORVIS_HOME, "checkout", original)
            git(CORVIS_HOME, "branch", "-D", branch)
            return f"No changes were made.\n\n{summary}"
        if changed.strip():
            git(CORVIS_HOME, "commit", "-m", f"Self-edit: {task[:60]}")

        passed, test_out = run_tests()
        _, stat = git(CORVIS_HOME, "diff", "--stat", f"{original}...{branch}")
        report = (f"{summary}\n\nBranch: {branch}\nChanges:\n{stat}\n\n"
                  f"Tests {'PASSED' if passed else 'FAILED'}:\n{test_out[-1500:]}")
        emit = agent_kwargs.get("on_event")
        if emit:
            emit("report", report)
        else:
            print(report)
    except BaseException:
        # Crash or Ctrl+C mid-edit: save whatever was done on the branch, go home.
        git(CORVIS_HOME, "add", "-A")
        git(CORVIS_HOME, "commit", "-m", f"Self-edit (interrupted): {task[:50]}")
        git(CORVIS_HOME, "checkout", original)
        print(f"\nSelf-edit stopped. Partial work saved on branch {branch}; you're back on {original}.")
        raise

    git(CORVIS_HOME, "checkout", original)
    _, before = git(CORVIS_HOME, "rev-parse", "HEAD")
    question = "Merge these changes into Corvis?" + ("" if passed else " (tests FAILED)")
    if approver(question):
        code, out = git(CORVIS_HOME, "merge", "--no-ff", branch, "-m", f"Merge {branch}")
        if code != 0:
            git(CORVIS_HOME, "merge", "--abort")
            return f"Merge failed, nothing changed: {out}"
        from .supervisor import record_update
        record_update(cfg, before.strip(), branch)  # lets the supervisor undo it if it won't start
        return "Merged. Restart Corvis to load the new code. (Undo: git revert -m 1 HEAD)"
    return f"Not merged. The work is saved on branch {branch}."


def _branch_has_commits(base: str, branch: str) -> bool:
    _, out = git(CORVIS_HOME, "rev-list", "--count", f"{base}..{branch}")
    return out.strip() not in {"", "0"}
