"""Background runs for the web app.

When you send a message, Corvis works in a background thread. Everything he does
(tool calls, results, approval requests) becomes an event the browser streams live.
If you reload the page mid-run, the browser replays the events and keeps following.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Callable

from ..agent import CodingAgent
from ..attachments import AttachmentStore, message_block
from ..bots import LEAD_ID, BotStore
from ..config import CORVIS_HOME, agent_name, build_agent, data_dir
from ..conversations.store import ConversationStore, make_title

APPROVAL_TIMEOUT = 600  # seconds before an unanswered request counts as "deny"
STOP_GRACE = 4          # after Stop, wait this long for the current step, then end the reply anyway
STOPPED_TEXT = "Stopped. Tell me how you'd like to continue."
STORED_RESULT_CHARS = 2000
CATCH_UP_CHARS = 6000
EVENT_EXTRAS = ("id", "bot", "bot_name", "color", "by")


class Run:
    def __init__(self, conv_id: str, bot: dict | None = None):
        self.id = uuid.uuid4().hex[:10]
        self.conv_id = conv_id
        self.bot = bot or {"id": LEAD_ID, "name": "Corvis"}
        self.routine: dict | None = None
        self.events: list[dict] = []
        self.done = False
        self.stop_requested = False
        self.abandoned = False      # ended early by Stop; the worker's late result is thrown away
        self.finish_lock = threading.Lock()
        self._approvals: dict[str, dict] = {}
        self._lock = threading.Lock()

    # --- events -------------------------------------------------------------
    def emit(self, kind: str, text: str = "", **extra) -> dict:
        with self._lock:
            ev = {"seq": len(self.events), "kind": kind, "text": text, "ts": time.time(), **extra}
            self.events.append(ev)
        return ev

    def should_stop(self) -> bool:
        return self.stop_requested

    def stop(self) -> None:
        self.stop_requested = True
        for a in list(self._approvals.values()):
            a["event"].set()  # unanswered approvals become "deny"

    # --- approvals ----------------------------------------------------------
    def ask(self, prompt: str) -> bool:
        """Called from the worker thread; blocks until you click Allow or Deny."""
        aid = uuid.uuid4().hex[:10]
        slot = {"event": threading.Event(), "allow": False}
        self._approvals[aid] = slot
        self.emit("approval", prompt, id=aid, bot_name=self.bot.get("name"))
        deadline = time.monotonic() + APPROVAL_TIMEOUT
        while not slot["event"].wait(0.25):
            if self.stop_requested or time.monotonic() > deadline:
                break
        allowed = bool(slot["allow"]) and not self.stop_requested
        self._approvals.pop(aid, None)
        self.emit("approval_result", "allowed" if allowed else "denied", id=aid)
        return allowed

    def answer(self, aid: str, allow: bool) -> bool:
        slot = self._approvals.get(aid)
        if not slot:
            return False
        slot["allow"] = allow
        slot["event"].set()
        return True


def stored_events(events: list[dict]) -> list[dict]:
    """The work log saved with a reply: everything except bookkeeping, outputs trimmed."""
    out = []
    for ev in events:
        if ev["kind"] in {"end", "done", "start"}:
            continue
        e = {"kind": ev["kind"], "text": ev["text"][:STORED_RESULT_CHARS]}
        for k in EVENT_EXTRAS:
            if ev.get(k) is not None:
                e[k] = ev[k]
        out.append(e)
    return out


class RunManager:
    def __init__(self, store: ConversationStore, cfg: dict,
                 agent_factory: Callable[..., CodingAgent] = build_agent, node_hub=None):
        self.store = store
        self.cfg = cfg
        self.agent_factory = agent_factory
        self.node_hub = node_hub
        self.runs: dict[str, Run] = {}
        self.agents: dict[str, CodingAgent] = {}
        self.bots = BotStore(data_dir(cfg), agent_name(cfg))
        self.extra_state: dict = {}   # shared with every bot (e.g. routines, the computer)
        self._self_edit_lock = threading.Lock()
        self._start_lock = threading.Lock()

    # --- queries ------------------------------------------------------------
    def active(self, conv_id: str) -> Run | None:
        run = self.runs.get(conv_id)
        return run if run and not run.done else None

    def any_active(self) -> bool:
        return any(not r.done for r in self.runs.values())

    def find_approval(self, aid: str) -> Run | None:
        for run in self.runs.values():
            if aid in run._approvals:
                return run
        return None

    def stop(self, conv_id: str) -> Run | None:
        """Stop a reply. A slow model can take minutes to finish its current step, so if it
        hasn't stopped after a few seconds the reply ends anyway and its late answer is dropped."""
        run = self.active(conv_id)
        if run is None:
            return None
        run.stop()

        def give_up() -> None:
            time.sleep(STOP_GRACE)
            if not run.done:
                run.abandoned = True
                self._finish(run, STOPPED_TEXT, "stopped")
        threading.Thread(target=give_up, daemon=True, name=f"corvis-stop-{conv_id}").start()
        return run

    def _finish(self, run: Run, reply: str, status: str) -> None:
        """Save the reply and end the run, exactly once."""
        with run.finish_lock:
            if run.done:
                return
            try:
                conv = self.store.get(run.conv_id)
                conv["messages"].append({
                    "role": "assistant", "text": reply, "status": status, "bot": run.bot["id"],
                    "events": stored_events(run.events), "ts": time.time(),
                })
                conv.setdefault("seen", {})[run.bot["id"]] = len(conv["messages"])
                if run.routine:
                    conv["unread"] = True  # nobody watched it happen
                self.store.save(conv)
            except KeyError:
                pass  # chat was deleted while working
            run.done = True
            run.emit("end", status)

    def forget(self, conv_id: str) -> None:
        self.runs.pop(conv_id, None)
        self.agents.pop(conv_id, None)

    # --- starting work ------------------------------------------------------
    def start(self, conv_id: str, text: str, attachments: list[dict] | None = None,
              bot_id: str | None = None, routine: dict | None = None) -> Run:
        with self._start_lock:
            if self.active(conv_id):
                raise RuntimeError("Corvis is still working on this chat. Wait or press Stop.")
            conv = self.store.get(conv_id)
            attachments = attachments or []
            bot = self._pick_bot(conv, text, bot_id)
            if not conv["messages"]:
                conv["title"] = routine["name"] if routine else make_title(
                    text or "Sent " + ", ".join(a["name"] for a in attachments))
            msg = {"role": "user", "text": text, "ts": time.time()}
            if attachments:
                msg["attachments"] = attachments
                conv.setdefault("attachments", []).extend(attachments)
            if bot["id"] != conv.get("bot", LEAD_ID):
                msg["to"] = bot["id"]
            if routine:
                msg["routine"] = routine["name"]
            conv["messages"].append(msg)
            self.store.save(conv)
            run = Run(conv_id, bot)
            run.routine = routine
            self.runs[conv_id] = run
        run.emit("start", bot=bot["id"], bot_name=bot["name"], color=bot.get("color"))
        threading.Thread(target=self._work, args=(run, text, attachments), daemon=True,
                         name=f"corvis-run-{conv_id}").start()
        return run

    def _pick_bot(self, conv: dict, text: str, bot_id: str | None) -> dict:
        """Who answers: the bot asked for, an @mentioned bot, or the chat's own bot."""
        if bot_id:
            try:
                return self.bots.get(bot_id)
            except KeyError:
                pass
        mentioned = self.bots.mentioned(text or "")
        if mentioned:
            return mentioned
        try:
            return self.bots.get(conv.get("bot"))
        except KeyError:
            return self.bots.lead()  # that bot was deleted

    @staticmethod
    def _history_key(conv: dict, bot: dict) -> str | None:
        return None if bot["id"] == conv.get("bot", LEAD_ID) else bot["id"]

    def _agent_for(self, conv: dict, bot: dict | None = None) -> CodingAgent:
        conv_id = conv["id"]
        bot = bot or self.bots.get(conv.get("bot"))
        # Built fresh for every message, so edits to a bot's job or the team apply at once.
        # Approvals and events always go to whichever run is current for this chat.
        agent = self.agent_factory(
            conv["workspace"], self.cfg,
            approver=lambda prompt: self.runs[conv_id].ask(prompt),
            on_event=lambda kind, text: self.runs[conv_id].emit(kind, text),
            emit=lambda kind, text, **extra: self.runs[conv_id].emit(kind, text, **extra),
            conversation_id=conv_id,
            conversation_attachments=lambda: self.store.get(conv_id).get("attachments", []),
            node_hub=self.node_hub,
            bot=bot,
            extra_state=self.extra_state,
        )
        key = self._history_key(conv, bot)
        history = conv.get("llm_history", []) if key is None else conv.get("bot_history", {}).get(key, [])
        agent.messages.extend(history)  # pick up where we left off
        self.agents[conv_id] = agent
        return agent

    def _catch_up(self, conv: dict, bot: dict) -> str:
        """What happened in this chat since this bot last took part (other bots' replies)."""
        seen = conv.get("seen", {}).get(bot["id"])
        msgs = conv["messages"][:-1]  # not the message being answered
        if seen is None:  # chats from before bots: the lead's history already covers them
            legacy = self._history_key(conv, bot) is None and conv.get("llm_history")
            seen = len(msgs) if legacy else 0
        lines = []
        for m in msgs[seen:]:
            if m["role"] == "user":
                who = "Owner"
            else:
                try:
                    who = self.bots.get(m.get("bot")).get("name")
                except KeyError:
                    who = "A teammate"
            if m.get("text"):
                lines.append(f"{who}: {m['text']}")
        if not lines:
            return ""
        text = "\n\n".join(lines)[-CATCH_UP_CHARS:]
        return f"Earlier in this chat, while you weren't involved:\n{text}\n\nNow the owner says to you:\n"

    def _work(self, run: Run, text: str, attachments: list[dict] | None = None) -> None:
        status, reply = "ok", ""
        try:
            conv = self.store.get(run.conv_id)
            extra = ""
            if attachments:
                files = AttachmentStore(data_dir(self.cfg))
                extra = message_block([files.get(a["id"]) for a in attachments], files, self.cfg, run.emit)
            if conv["mode"] == "self":
                reply = self._self_edit(run, text + extra)
            else:
                agent = self._agent_for(conv, run.bot)
                command = self._plugin_command(text)
                if command:
                    run.emit("thinking", f"Running the {text.split()[0]} command from a plugin.")
                task = self._catch_up(conv, run.bot) + (command or text)
                if run.routine:
                    task = (f"(This is your scheduled routine \"{run.routine['name']}\". The owner may not "
                            "be watching: do the work, and leave a clear summary for them to read later.)\n"
                            + task)
                reply = agent.run(task, should_stop=run.should_stop, extra=extra)
                if run.abandoned:
                    return  # the owner stopped this and may already have moved on
                conv = self.store.get(run.conv_id)
                key = self._history_key(conv, run.bot)
                if key is None:
                    conv["llm_history"] = agent.messages[1:]
                else:
                    conv.setdefault("bot_history", {})[key] = agent.messages[1:]
                self.store.save(conv)
            if run.stop_requested:
                status = "stopped"
        except Exception as e:  # never let a crash leave the chat stuck "working"
            status = "error"
            reply = f"Something went wrong inside Corvis: {type(e).__name__}: {e}"
            run.emit("error", reply)
        finally:
            if any(ev["kind"] == "error" for ev in run.events) and status == "ok":
                status = "error"
            if not run.abandoned:
                self._finish(run, reply, status)

    def _plugin_command(self, text: str) -> str | None:
        """'/name words' typed by the owner runs a plugin's slash command."""
        if not text.startswith("/") or (self.cfg.get("plugins") or {}).get("enabled", True) is False:
            return None
        from ..plugin_store import PluginStore
        try:
            return PluginStore(data_dir(self.cfg)).expand_command(text)
        except Exception:
            return None

    def _self_edit(self, run: Run, text: str) -> str:
        from ..selfedit import self_edit

        if not self._self_edit_lock.acquire(blocking=False):
            return "Another self-edit is already running. Wait for it to finish, then try again."
        try:
            summary = {"text": ""}

            def on_event(kind: str, t: str) -> None:
                if kind == "done":
                    summary["text"] = t
                run.emit(kind, t)

            result = self_edit(text, self.cfg, approver=run.ask, should_stop=run.should_stop,
                               on_event=on_event, **self._self_edit_extra())
            return f"{summary['text']}\n\n{result}".strip()
        finally:
            self._self_edit_lock.release()

    def _self_edit_extra(self) -> dict:
        """Hook for tests to inject a fake model into self-edit."""
        return {}


def corvis_home() -> str:
    return str(CORVIS_HOME)
