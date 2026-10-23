"""Run Corvis.

  python -m corvis                     chat in the terminal
  python -m corvis --web               open the web app (model picker, workshop, avatar)
  python -m corvis --body robot        start in a robot body (simulated; add --ros2 for real)
"""

from __future__ import annotations

import argparse
from pathlib import Path

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
    print("Commands: /models  /model <id>  /effort <level>  /body <console|avatar|robot>  exit\n")
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
            if text == "/models":
                for m in corvis.catalog.list():
                    mark = "*" if m.id == corvis.model.id else " "
                    print(f" {mark} {m.id:22} {m.label} — {m.description}")
                continue
            if text.startswith("/model "):
                corvis.switch_model(text.split(maxsplit=1)[1])
                print(f"[Now thinking with {corvis.model.label}]")
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
        except (KeyError, ValueError, RuntimeError) as e:
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
    args = ap.parse_args()

    identity = Identity.load()
    catalog = ModelCatalog.load()

    if args.web:
        from .web.server import serve

        serve(identity, catalog, Path(args.workspace), args.port, args.model, args.effort)
        return

    corvis = Corvis(identity, MemoryStore(), make_body(args.body, identity, args.ros2),
                    Workshop(args.workspace, approve=ask_approval), catalog, args.model, args.effort)
    try:
        terminal(corvis, identity, args.ros2)
    finally:
        corvis.body.shutdown()
        print("Corvis offline.")


if __name__ == "__main__":
    main()
