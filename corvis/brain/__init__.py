"""Corvis's second brain: a Git-backed knowledge base, autonomous learning and long-term memory.

    kb.py          knowledge files, health scores, the review workflow, dashboard and reports
    learner.py     learn / research / verify sessions and the background job queue
    continuity.py  session summaries, conversation digests, project memory and greetings
    repo.py        the Git repository and GitHub sync
    service.py     ties them together for the app (one per data folder)
"""
from .service import BrainService, brain_cfg, shared

__all__ = ["BrainService", "brain_cfg", "shared"]
