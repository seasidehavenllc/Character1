"""Routines: bots doing work on a schedule.

"Every weekday at 8:00, Sales Outbound checks for new leads and drafts replies."
Each routine runs one bot with a written request and posts the result in that routine's
own chat (marked unread until the owner opens it). The scheduler runs inside Corvis, so on
the cloud hub routines keep running while your PC and phone are off.

Stored in data/routines.json. Times are in the owner's time zone.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EVERY = ("day", "weekday", "week", "hours", "once")
TICK_SECONDS = 20
MAX_RUNS_KEPT = 50


def zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def check_schedule(s: dict) -> dict:
    """Validate and normalise a schedule. Raises ValueError with a friendly message."""
    every = str(s.get("every", "day")).lower()
    if every not in EVERY:
        raise ValueError("Schedule 'every' must be once, day, weekday, week or hours.")
    if every == "hours":
        hours = int(s.get("hours") or 0)
        if not 1 <= hours <= 168:
            raise ValueError("Every N hours: N must be between 1 and 168.")
        return {"every": "hours", "hours": hours}
    at = str(s.get("at") or "09:00").strip()
    try:
        h, m = (int(x) for x in at.split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AssertionError):
        raise ValueError("Time must look like 08:30 (24-hour).") from None
    out = {"every": every, "at": f"{h:02d}:{m:02d}"}
    if every == "once":
        try:
            day = dt.date.fromisoformat(str(s.get("date") or "").strip())
        except ValueError:
            raise ValueError("A one-time task needs a date like 2026-11-03.") from None
        out["date"] = day.isoformat()
    if every == "week":
        day = str(s.get("day") or "mon").lower()[:3]
        if day not in DAYS:
            raise ValueError("Day must be mon, tue, wed, thu, fri, sat or sun.")
        out["day"] = day
    return out


def next_run(s: dict, tz: str | None, after: float) -> float:
    if s["every"] == "hours":
        return after + s["hours"] * 3600
    z = zone(tz)
    h, m = (int(x) for x in s["at"].split(":"))
    if s["every"] == "once":   # the moment itself, even if it has passed (callers check)
        d = dt.date.fromisoformat(s["date"])
        return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=z).timestamp()
    start = dt.datetime.fromtimestamp(after, z)
    for add in range(0, 9):
        day = (start + dt.timedelta(days=add)).date()
        when = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=z)
        if when.timestamp() <= after:
            continue
        wd = when.weekday()
        if s["every"] == "weekday" and wd >= 5:
            continue
        if s["every"] == "week" and wd != DAYS.index(s["day"]):
            continue
        return when.timestamp()
    raise AssertionError("unreachable")


def describe(s: dict) -> str:
    if s["every"] == "hours":
        return "Every hour" if s["hours"] == 1 else f"Every {s['hours']} hours"
    at = s["at"]
    if s["every"] == "once":
        return f"Once, {dt.date.fromisoformat(s['date']).strftime('%a %d %b %Y')} at {at}"
    if s["every"] == "day":
        return f"Every day at {at}"
    if s["every"] == "weekday":
        return f"Weekdays at {at}"
    return f"Every {DAY_NAMES[DAYS.index(s['day'])]} at {at}"


class RoutineStore:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "routines.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def list(self) -> list[dict]:
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        for r in items:
            r["when"] = describe(r["schedule"])
        return items

    def _write(self, items: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        clean = [{k: v for k, v in r.items() if k != "when"} for r in items]
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, rid: str) -> dict:
        for r in self.list():
            if r["id"] == rid:
                return r
        raise KeyError(rid)

    def create(self, name: str, bot: str, prompt: str, schedule: dict, tz: str | None,
               now: float | None = None, fresh: bool = False) -> dict:
        name = " ".join(str(name).split())[:60]
        prompt = str(prompt).strip()[:4000]
        if not name or not prompt:
            raise ValueError("A routine needs a name and a request.")
        sched = check_schedule(schedule)
        now = time.time() if now is None else now
        r = {"id": uuid.uuid4().hex[:8], "name": name, "bot": bot or "corvis", "prompt": prompt,
             "schedule": sched, "tz": str(zone(tz)), "enabled": True, "created": now,
             "next_run": next_run(sched, tz, now), "last_run": None, "last_status": None,
             "conversation_id": None, "fresh": bool(fresh), "runs": []}
        if sched["every"] == "once" and r["next_run"] <= now:
            raise ValueError("That time has already passed. Pick a time in the future.")
        with self._lock:
            items = self.list()
            items.append(r)
            self._write(items)
        r["when"] = describe(sched)
        return r

    def update(self, rid: str, data: dict, now: float | None = None) -> dict:
        with self._lock:
            items = self.list()
            for r in items:
                if r["id"] != rid:
                    continue
                for k in ("name", "prompt", "bot"):
                    if k in data and str(data[k]).strip():
                        r[k] = str(data[k]).strip()[:4000 if k == "prompt" else 60]
                if "enabled" in data:
                    r["enabled"] = bool(data["enabled"])
                if "fresh" in data:
                    r["fresh"] = bool(data["fresh"])
                if "tz" in data:
                    r["tz"] = str(zone(data["tz"]))
                if "schedule" in data:
                    r["schedule"] = check_schedule(data["schedule"])
                if {"schedule", "tz", "enabled"} & set(data):
                    t = time.time() if now is None else now
                    r["next_run"] = next_run(r["schedule"], r["tz"], t)
                    if r["schedule"]["every"] == "once" and r["enabled"] and r["next_run"] <= t:
                        raise ValueError("That one-time task's moment has passed. Pick a new date and time.")
                for k in ("conversation_id", "last_run", "last_status", "next_run"):
                    if k in data:
                        r[k] = data[k]
                if "run" in data:   # one entry of run history: when, how it went, which chat
                    r["runs"] = (r.get("runs") or []) + [data["run"]]
                    r["runs"] = r["runs"][-MAX_RUNS_KEPT:]
                self._write(items)
                r["when"] = describe(r["schedule"])
                return r
        raise KeyError(rid)

    def delete(self, rid: str) -> bool:
        with self._lock:
            items = self.list()
            kept = [r for r in items if r["id"] != rid]
            self._write(kept)
        return len(kept) != len(items)

    def due(self, now: float) -> list[dict]:
        return [r for r in self.list() if r["enabled"] and r["next_run"] <= now]


class Scheduler:
    """Checks for due routines every few seconds and starts them."""

    def __init__(self, store: RoutineStore, fire: Callable[[dict], str], log=print):
        self.store = store
        self.fire = fire       # starts the routine's run; returns a status line
        self.log = log
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def tick(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        fired = []
        for r in self.store.due(now):
            # Schedule the next one first, so a crash can't make it fire over and over.
            # If Corvis was off for a while, a missed routine runs once, not once per miss.
            if r["schedule"]["every"] == "once":
                self.store.update(r["id"], {"enabled": False, "last_run": now}, now=now - 1)
            else:
                self.store.update(r["id"], {"next_run": next_run(r["schedule"], r["tz"], now), "last_run": now})
            try:
                status = self.fire(r)
            except Exception as e:  # one broken routine must not stop the others
                status = f"Couldn't start: {e}"
            self.store.update(r["id"], {"last_status": status})
            fired.append(r["id"])
        return fired

    def start(self) -> None:
        def loop():
            while not self._stop.wait(TICK_SECONDS):
                try:
                    self.tick()
                except Exception as e:
                    self.log(f"Routine scheduler problem: {e}")
        self.thread = threading.Thread(target=loop, daemon=True, name="corvis-routines")
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
