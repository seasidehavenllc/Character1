"""Run Corvis.

  python -m corvis                     chat in the terminal
  python -m corvis --web               open the web app (model picker, workshop, avatar)
  python -m corvis --body robot        start in a robot body (simulated; add --ros2 for real)
  python -m corvis --hub               run the Corvis Hub on your home PC (accounts, sync, PC brain)
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

import yaml

from .account import Account, HubError
from .brain import Corvis
from .identity import Identity
from .memory import MemoryStore
from .models import ModelCatalog
from .runtime import EFFORTS, describe_api_error, make_body
from .workshop import Workshop

DEFAULT_WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"


def ask_approval(command: str) -> bool:
    answer = input(f"\n  Corvis wants to run:  {command}\n  Allow? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def terminal(corvis: Corvis, identity: Identity, ros2: bool) -> None:
    print(f"{identity.name} online — thinking with {corvis.model.label}.")
    print("Commands: /device  /models  /model <id|auto>  /effort <level>  /body <console|avatar|robot>")
    print("          /login <hub address> <username>  /register <hub address> <username>  /logout  /sync  exit\n")
    while True:
        try:
            text = input("You: ").strip()
        except EOFError:
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            break
        try:
            if text == "/device":
                d = corvis.catalog.device
                print(f" {d.system} {d.machine} · {d.summary()}")
                print(f" Recommended local model: {d.recommended_model} ({d.recommendation_reason})")
                print(f" Install it with:  ollama pull {d.recommended_model}")
                continue
            if text == "/models":
                corvis.catalog.refresh()
                for m in corvis.catalog.list():
                    mark = "*" if m.id == corvis.model.id else " "
                    print(f" {mark} {m.id:24} [{m.group}] {m.description}")
                continue
            if text.startswith("/model "):
                corvis.switch_model(text.split(maxsplit=1)[1])
                print(f"[Now thinking with {corvis.model.label}]")
                continue
            if text.startswith(("/login ", "/register ")):
                parts = text.split()
                if len(parts) != 3:
                    raise ValueError("Usage: /login <hub address, e.g. 192.168.1.20:8810> <username>")
                password = getpass.getpass("  Password: ")
                corvis.account.sign_in(parts[1], parts[2], password, register=parts[0] == "/register")
                corvis.catalog.refresh()
                got = corvis.sync(force=True)
                print(f"[Signed in as {corvis.account.username}. Synced {got or 0} memories from your other devices.]")
                continue
            if text == "/logout":
                corvis.account.sign_out()
                corvis.catalog.refresh()
                print("[Signed out. Memories stay on this device.]")
                continue
            if text == "/sync":
                got = corvis.sync(force=True)
                print("[Not signed in]" if not corvis.account.signed_in else
                      "[Home PC unreachable — will sync when it's back]" if got is None else
                      f"[Synced. {got} new from your other devices]")
                continue
            if text.startswith("/effort "):
                level = text.split(maxsplit=1)[1]
                if level not in EFFORTS:
                    raise ValueError(f"Effort must be one of {', '.join(EFFORTS)}")
                corvis.set_effort(level)
                print(f"[Effort set to {level}]")
                continue
            if text.startswith("/body "):
                corvis.transfer_to(make_body(text.split(maxsplit=1)[1], identity, ros2))
                print(f"[Corvis transferred to '{corvis.body.name}' body]")
                continue
            corvis.chat(text, on_event=lambda e: print(f"  · {e}"))
        except (KeyError, ValueError, RuntimeError, HubError) as e:
            print(f"[{e}]")
        except Exception as e:
            msg = describe_api_error(e)
            if msg is None:
                raise
            print(f"[{msg}]")


def main() -> None:
    ap = argparse.ArgumentParser(prog="corvis")
    ap.add_argument("--web", action="store_true", help="Open the web app instead of the terminal")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--body", choices=["console", "avatar", "robot"], default="console")
    ap.add_argument("--ros2", action="store_true", help="Drive a real ROS 2 robot instead of the simulator")
    ap.add_argument("--model", help="Model ID from config/models.yaml")
    ap.add_argument("--effort", choices=EFFORTS, default="high")
    ap.add_argument("--workspace", default=str(DEFAULT_WORKSPACE), help="Folder where Corvis builds projects")
    ap.add_argument("--hub", action="store_true", help="Run the Corvis Hub on this PC")
    ap.add_argument("--hub-port", type=int, default=8810)
    ap.add_argument("--hub-host", default="0.0.0.0", help="Network address the hub listens on")
    ap.add_argument("--no-register", action="store_true", help="Hub: don't allow new accounts")
    args = ap.parse_args()

    if args.hub:
        from .hub import serve_hub
        from .models import MODELS_FILE

        local_server = yaml.safe_load(MODELS_FILE.read_text(encoding="utf-8"))["local"]["server"]
        serve_hub(local_server, args.hub_host, args.hub_port, allow_register=not args.no_register)
        return

    identity = Identity.load()
    account = Account()
    catalog = ModelCatalog.load(account=account)
    if account.signed_in:
        print(f"Signed in as {account.username} · home PC {'online' if account.hub_online else 'offline'}")
    d = catalog.device
    print(f"Device: {d.summary()}")
    if not catalog.local:
        print(f"No local models found. For on-device AI, install Ollama (https://ollama.com) and run:\n"
              f"    ollama pull {d.recommended_model}      ({d.recommendation_reason})\n"
              f"Until then Corvis can only use your home PC (when signed in) or cloud models.")

    if args.web:
        from .web.server import serve

        serve(identity, catalog, account, Path(args.workspace), args.port, args.model, args.effort)
        return

    corvis = Corvis(identity, MemoryStore(), make_body(args.body, identity, args.ros2),
                    Workshop(args.workspace, approve=ask_approval), catalog, args.model, args.effort,
                    account=account)
    corvis.sync(force=True)
    try:
        terminal(corvis, identity, args.ros2)
    finally:
        corvis.body.shutdown()
        print("Corvis offline.")


if __name__ == "__main__":
    main()
