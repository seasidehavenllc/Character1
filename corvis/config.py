"""Load config.yaml and wire the agent together."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

import yaml

from .agent import CodingAgent, Event, _default_event
from .llm import ChatLLM
from .attachments import AttachmentStore
from .memory import Memory
from .pc import PCPolicy
from . import apps as apps_mod
from .prompts import build_system_prompt
from .safety import DEFAULT_ALWAYS_BLOCK, DEFAULT_AUTO_ALLOW, CommandPolicy, Workspace
from .tools import ToolContext, build_registry

CORVIS_HOME = Path(__file__).resolve().parent.parent  # the folder containing corvis/
DEFAULT_CONFIG = CORVIS_HOME / "config.yaml"


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_CONFIG
    example = CORVIS_HOME / "config.example.yaml"
    if path is None and not p.is_file() and example.is_file():
        # First run: start from the example. Updates ship only the example, so your
        # own config.yaml is never overwritten when you unzip a new version.
        shutil.copyfile(example, p)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def data_dir(cfg: dict) -> Path:
    """Where chats and memory live (data/ inside Corvis's folder unless config says otherwise)."""
    return Path(cfg.get("data_dir") or (CORVIS_HOME / "data")).expanduser()


def memory_cfg(cfg: dict) -> dict:
    m = cfg.get("memory", {}) or {}
    return {"enabled": m.get("enabled", True), "auto_recall": m.get("auto_recall", True),
            "recall_chats": int(m.get("recall_chats", 3))}


def api_key(lcfg: dict) -> str:
    """The model service's key. Cloud keys belong in an environment variable (llm.api_key_env),
    not in config.yaml, so they're never synced to GitHub or copied around."""
    env = lcfg.get("api_key_env")
    if env and os.environ.get(env):
        return os.environ[env]
    return str(lcfg.get("api_key") or "local")


def make_llm(lcfg: dict):
    """The model Corvis thinks with. With `llm.fallbacks` set, a ModelRouter tries each
    fallback in order when the one before it is unreachable (e.g. the PC is off)."""
    from .model_router import ModelRouter

    def client(c: dict, base: dict) -> ChatLLM:
        merged = {**base, **c}
        return ChatLLM(
            base_url=merged.get("base_url", "http://localhost:11434/v1"),
            model=merged.get("model", "qwen3-coder:30b"),
            api_key=api_key(merged),
            temperature=merged.get("temperature", 0.2),
            max_tokens=merged.get("max_tokens", 8192),
            timeout=merged.get("timeout", 900),
            native_tools=not base.get("text_tool_mode", False),
        )

    base = {k: v for k, v in lcfg.items() if k != "fallbacks"}
    primary = client({}, base)
    fallbacks = [f for f in (lcfg.get("fallbacks") or []) if isinstance(f, dict) and f.get("model")]
    if not fallbacks:
        return primary
    # A fallback doesn't inherit the primary's key: each names its own key (api_key_env).
    shared = {k: v for k, v in base.items() if k not in ("api_key", "api_key_env", "base_url", "model")}
    return ModelRouter(primary, [client(f, shared) for f in fallbacks])


def agent_name(cfg: dict) -> str:
    """The assistant's display name. Change it in config.yaml; nothing else needs editing."""
    return str(cfg.get("name") or "Corvis")


def console_approver(prompt: str) -> bool:
    print(f"\n⚠  Corvis wants to run:\n{prompt}")
    return input("Allow? [y/N] ").strip().lower() in {"y", "yes"}


def build_agent(
    workspace: str | Path,
    cfg: dict,
    approver: Callable[[str], bool] = console_approver,
    auto_approve: bool = False,
    on_event: Event = _default_event,
    llm: ChatLLM | None = None,
    conversation_id: str | None = None,
    conversation_attachments: Callable[[], list[dict]] | None = None,
    node_hub=None,
    bot: dict | None = None,
    depth: int = 0,
    emit: Callable[..., object] | None = None,
    extra_state: dict | None = None,
    project: dict | None = None,
) -> CodingAgent:
    """Build one bot (the lead, Corvis, unless `bot` says otherwise) ready to work.

    emit(kind, text, **extra) records events with extra detail (which bot did what);
    without it, events go to on_event(kind, text)."""
    from .bots import BotStore, tool_filter

    lcfg = cfg.get("llm", {})
    acfg = cfg.get("agent", {})
    scfg = cfg.get("safety", {})
    emit = emit or (lambda kind, text, **_: on_event(kind, text))

    llm = llm or make_llm(lcfg)
    bots = BotStore(data_dir(cfg), agent_name(cfg))
    bot = bot or bots.lead()
    ws = Workspace(workspace)
    policy = CommandPolicy(
        mode="auto" if auto_approve else scfg.get("approval", "ask"),
        auto_allow=DEFAULT_AUTO_ALLOW + (scfg.get("extra_auto_allow") or []),
        always_block=DEFAULT_ALWAYS_BLOCK + (scfg.get("extra_block") or []),
        approver=approver,
    )
    ctx = ToolContext(
        workspace=ws,
        policy=policy,
        approver=(lambda _: True) if auto_approve else approver,
        output_limit=acfg.get("tool_output_chars", 12000),
        config=cfg,
    )
    mcfg = memory_cfg(cfg)
    memory = Memory(data_dir(cfg)) if mcfg["enabled"] else None
    ctx.state["memory"] = memory
    # Persistent cognition stores are separate from conversational memory: beliefs are
    # revisable claims; experiences are records of observed task outcomes.
    from .beliefs import BeliefStore
    from .experience import ExperienceStore
    beliefs = BeliefStore(data_dir(cfg)) if mcfg["enabled"] else None
    experiences = ExperienceStore(data_dir(cfg)) if mcfg["enabled"] else None
    ctx.state["beliefs"] = beliefs
    ctx.state["experiences"] = experiences
    ctx.state["conversation_id"] = conversation_id
    ctx.state["attachments"] = AttachmentStore(data_dir(cfg))
    ctx.state["conversation_attachments"] = conversation_attachments
    ctx.state["data_dir"] = str(data_dir(cfg))
    ctx.state["pc_policy"] = PCPolicy(cfg, CORVIS_HOME, data_dir(cfg))
    ctx.state.setdefault("app_index", apps_mod.shared_index())
    ctx.state["node_hub"] = node_hub
    ctx.state.update(bot=bot, bots=bots, depth=depth, emit=emit)
    ctx.state.update(extra_state or {})
    ctx.state["project"] = project
    if "routines" not in ctx.state:
        from .routines import RoutineStore
        ctx.state["routines"] = RoutineStore(data_dir(cfg))
        ctx.state["owner_tz"] = lambda: str(cfg.get("timezone") or "UTC")
    holder: dict = {}

    def spawn_bot(target: dict, request: str) -> str:
        """ask_bot: run a teammate on a request and bring back its answer."""
        emit("handoff", request, bot=target["id"], bot_name=target["name"], color=target.get("color"),
             by=bot["name"])

        def sub_event(kind: str, text: str, **extra) -> None:
            if kind == "done":
                return  # their answer is shown by handoff_done
            emit(kind, text, **{"bot": target["id"], "bot_name": target["name"], **extra})

        teammate = build_agent(
            workspace, cfg, approver=lambda p: approver(f"{target['name']}: {p}"),
            auto_approve=auto_approve, llm=llm, conversation_id=conversation_id,
            conversation_attachments=conversation_attachments, node_hub=node_hub,
            bot=target, depth=depth + 1, emit=sub_event, extra_state=extra_state, project=project)
        parent = holder.get("agent")
        answer = teammate.run(f"Your teammate {bot['name']} asks:\n{request}",
                              should_stop=getattr(parent, "should_stop", lambda: False))
        emit("handoff_done", answer, bot=target["id"], bot_name=target["name"], color=target.get("color"))
        return f"{target['name']} replied:\n{answer}"

    ctx.state["spawn_bot"] = spawn_bot
    registry = build_registry(ctx)
    registry.allow = tool_filter(bot)
    tool_names = {s["function"]["name"] for s in registry.schemas()}
    if node_hub is not None and node_hub.paired() and "pc" in (bot.get("abilities") or []):
        tool_names |= {"pc_list", "open_app"}  # the PC's tools come and go; keep its rules in mind
    team = [b for b in bots.list() if b["id"] != bot["id"]]
    system = build_system_prompt(ws.root, registry.schemas(), text_tools=not llm.native_tools,
                                 name=agent_name(cfg), tool_names=tool_names,
                                 personality=str(cfg.get("personality") or ""),
                                 bot=bot, team=team, lead_name=agent_name(cfg),
                                 skills=ctx.state.get("skills") if registry.allow is None or registry.allow("use_skill") else None)
    if project:
        from .projects import ProjectStore
        system += ProjectStore(data_dir(cfg)).prompt_block(project)

    brain = ctx.state.get("brain")
    continuity = getattr(brain, "continuity", None)

    def context() -> str:  # refreshed before every task
        text = memory.facts.block(bot["id"]) if memory else ""
        if node_hub is not None and "pc" in (bot.get("abilities") or []):
            text += node_hub.status_line()
        if continuity is not None and depth == 0:
            try:
                text += continuity.context_block()
            except Exception:
                pass  # memory must never block a task
        return text

    context_provider = context if (memory is not None or node_hub is not None or continuity is not None) else None
    recall_provider = None
    if depth == 0 and memory and mcfg["auto_recall"]:
        def recall(task: str) -> tuple[str, list[str]]:
            blocks: list[str] = []
            titles: list[str] = []
            if brain is not None:   # memory first: validated knowledge, then past conversations and projects
                try:
                    hits = [h for h in brain.kb.search(task, limit=3, expand=False) if h["score"] >= 4]
                    if hits:
                        blocks.append("\n\n[From your knowledge base — read_knowledge for the full file]\n" + "\n".join(
                            f"- [{h['id']}] {h['title']} (confidence {h.get('confidence', 0)}%, health "
                            f"{h['health']['score']}% {h['health']['label']}): {h.get('summary', '')}" for h in hits))
                        titles.extend(f"knowledge: {h['title']}" for h in hits)
                    if continuity is not None:
                        block, found = continuity.recall(task)
                        if block:
                            blocks.append(block)
                            titles.extend(found)
                except Exception:
                    pass
            try:
                block, found_titles = memory.recall(task, exclude=conversation_id, limit=mcfg["recall_chats"])
                if block: blocks.append(block)
                titles.extend(found_titles)
            except Exception:
                pass  # memory retrieval must not block a task
            belief_block = beliefs.context(task, limit=5) if beliefs else ""
            if belief_block: blocks.append("\n[Corvis belief context — claims are revisable, not guaranteed facts]\n" + belief_block)
            episodes = experiences.recent(limit=3, query=task) if experiences else []
            if episodes:
                lines = ["\n[Relevant past task experiences; outcomes may be incomplete or unverified]"]
                for episode in episodes:
                    lines.append(f"- Goal: {episode.get('goal','')} | Outcome: {episode.get('outcome','')} | Verified: {episode.get('verified', False)} | Lesson: {episode.get('lesson','')}")
                blocks.append("\n".join(lines))
            return ("\n\n".join(blocks), titles)
        recall_provider = recall

    agent = CodingAgent(
        llm, registry, system,
        max_steps=acfg.get("max_steps", 60),
        max_context_chars=acfg.get("max_context_chars", 200_000),
        on_event=lambda kind, text: emit(kind, text),
        context_provider=context_provider,
        recall_provider=recall_provider,
    )
    agent.bot = bot
    holder["agent"] = agent
    return agent
