"""Run Corvis:  python -m corvis [--body console|avatar|robot] [--ros2]"""

from __future__ import annotations

import argparse

import anthropic

from .bodies import AvatarBody, ConsoleBody, RobotBody, Ros2Driver, SimulatedDriver
from .brain import Corvis
from .identity import Identity
from .memory import MemoryStore


def make_body(kind: str, identity: Identity, ros2: bool):
    if kind == "avatar":
        return AvatarBody(identity)
    if kind == "robot":
        return RobotBody(Ros2Driver() if ros2 else SimulatedDriver())
    return ConsoleBody()


def main() -> None:
    ap = argparse.ArgumentParser(prog="corvis")
    ap.add_argument("--body", choices=["console", "avatar", "robot"], default="console")
    ap.add_argument("--ros2", action="store_true", help="Drive a real ROS 2 robot instead of the simulator")
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], default="medium")
    args = ap.parse_args()

    identity = Identity.load()
    corvis = Corvis(identity, MemoryStore(), make_body(args.body, identity, args.ros2), effort=args.effort)
    print(f"{identity.name} online in '{args.body}' body. Type 'exit' to quit, '/body <kind>' to switch bodies.\n")

    try:
        while True:
            try:
                text = input("You: ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text.lower() in {"exit", "quit"}:
                break
            if text.startswith("/body "):
                kind = text.split(maxsplit=1)[1]
                corvis.transfer_to(make_body(kind, identity, args.ros2))
                print(f"[Corvis transferred to '{kind}' body]")
                continue
            try:
                corvis.chat(text)
            except anthropic.AuthenticationError:
                print("No valid Anthropic credentials. Set ANTHROPIC_API_KEY (see README).")
                break
            except anthropic.RateLimitError:
                print("[Rate limited — wait a moment and try again]")
            except anthropic.APIConnectionError:
                print("[Can't reach the Anthropic API — check your connection]")
            except anthropic.APIStatusError as e:
                print(f"[API error {e.status_code}: {e.message}]")
    finally:
        corvis.body.shutdown()
        print("Corvis offline.")


if __name__ == "__main__":
    main()
