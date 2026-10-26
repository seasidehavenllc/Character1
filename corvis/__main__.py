"""Command line entry point.

  python -m corvis code --repo "D:/Games/MyGame" "add a stamina system to the player"
  python -m corvis code --repo "D:/Games/MyGame"          (interactive chat)
  python -m corvis self-edit "add a tool that runs Blender scripts headless"
  python -m corvis self-edit                              (interactive self-edit)
  python -m corvis check                                  (test the model connection)
  python -m corvis web                                    (chat app in your browser)
  python -m corvis set-password                           (owner password for phone access)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CORVIS_HOME, agent_name, build_agent, console_approver, load_config
from .llm import ChatLLM, LLMError

COLORS = {"tool": "\033[36m", "result": "\033[90m", "thinking": "\033[35m",
          "error": "\033[31m", "done": "\033[32m", "warn": "\033[33m"}
RESET = "\033[0m"
NAME = "Corvis"


def pretty_event(kind: str, text: str) -> None:
    if kind == "done":
        print(f"\n{COLORS['done']}{NAME}:{RESET} {text}\n")
    elif kind == "tool":
        print(f"{COLORS['tool']}→ {text}{RESET}")
    elif kind == "result":
        first = text.strip().splitlines()[0][:160] if text.strip() else "(empty)"
        print(f"{COLORS['result']}  {first}{RESET}")
    else:
        print(f"{COLORS.get(kind, '')}{text}{RESET}")


def show_plugin_errors(agent) -> None:
    for err in agent.registry.ctx.state.get("plugin_errors", []):
        pretty_event("warn", f"⚠ {err}")


def is_own_folder(repo: str) -> bool:
    return Path(repo).expanduser().resolve() == CORVIS_HOME


def prompt_loop(handle) -> None:
    while True:
        try:
            task = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if task.lower() in {"exit", "quit"}:
            break
        if task:
            handle(task)


def cmd_code(args, cfg) -> None:
    if is_own_folder(args.repo) and not args.force:
        print(f"That's {NAME}'s own folder. Editing it in 'code' mode skips the safety branch,\n"
              f"tests, and your approval. Use self-edit instead:\n"
              f"  python -m corvis self-edit\n"
              f"(Or add --force if you really mean it.)")
        sys.exit(2)
    agent = build_agent(args.repo, cfg, approver=console_approver,
                        auto_approve=args.yes, on_event=pretty_event)
    show_plugin_errors(agent)
    if args.task:
        agent.run(" ".join(args.task))
        return
    print(f"{NAME} coder ready in {agent.registry.ctx.workspace.root}. Type 'exit' to quit.\n")
    prompt_loop(agent.run)


def cmd_self_edit(args, cfg) -> None:
    from .selfedit import self_edit

    def handle(task: str) -> None:
        print(self_edit(task, cfg, approver=console_approver,
                        auto_approve_commands=args.yes, on_event=pretty_event))

    if args.task:
        handle(" ".join(args.task))
        return
    print(f"{NAME} self-edit mode. Each request runs on its own branch, gets tested,\n"
          f"and only merges if you approve. Type 'exit' to quit.\n")
    prompt_loop(handle)


def cmd_check(args, cfg) -> None:
    l = cfg.get("llm", {})
    from .config import api_key
    llm = ChatLLM(base_url=l.get("base_url", "http://localhost:11434/v1"),
                  model=l.get("model", "qwen3-coder:30b"), api_key=api_key(l), max_tokens=50)
    try:
        r = llm.chat([{"role": "user", "content": "Reply with exactly: online"}])
        print(f"Model '{llm.model}' replied: {r.content.strip()}")
    except LLMError as e:
        print(e)
        sys.exit(1)


def cmd_web(args, cfg) -> None:
    from .web.server import run_web
    sys.exit(run_web(cfg, open_browser=not args.no_browser, port=args.port))


def cmd_phone_setup(args, cfg) -> None:
    from pathlib import Path

    from .config import DEFAULT_CONFIG
    from .phone_setup import run
    path = Path(args.config) if args.config else DEFAULT_CONFIG
    sys.exit(run(cfg, path, lambda: cmd_set_password(args, cfg)))


def cmd_set_password(args, cfg) -> None:
    import getpass

    from .config import data_dir
    from .web.auth import MIN_PASSWORD, Auth

    auth = Auth(data_dir(cfg))
    print("Set the owner password for using Corvis from your phone or other devices.")
    print(f"Use at least {MIN_PASSWORD} characters. A short sentence works well.")
    if auth.has_password():
        print("(This replaces the current password and signs out every device.)")
    while True:
        first = getpass.getpass("New password: ")
        if len(first) < MIN_PASSWORD:
            print(f"Too short: use at least {MIN_PASSWORD} characters.")
            continue
        if getpass.getpass("Type it again: ") != first:
            print("Those didn't match. Try again.")
            continue
        auth.set_password(first)
        print("Saved. Use this password to sign in on your phone.")
        return


def cmd_serve(args, cfg) -> None:
    from .supervisor import serve
    sys.exit(serve(cfg, args.config, open_browser=not args.no_browser))


def cmd_node(args, cfg) -> None:
    from .node import Node
    print("Corvis Node: lending this PC to the hub. Keep this window open.")
    sys.exit(Node(cfg).run_forever())


def cmd_link_pc(args, cfg) -> None:
    from pathlib import Path

    from .config import DEFAULT_CONFIG
    from .node import link
    hub = args.hub or input("Hub address (e.g. https://corvis-hub.tail1234.ts.net): ").strip()
    code = args.code or input("Pairing code from the hub: ").strip()
    try:
        url = link(cfg, Path(args.config) if args.config else DEFAULT_CONFIG, hub, code, args.name or "")
    except Exception as e:
        print(f"Couldn't link: {e}")
        sys.exit(1)
    print(f"Linked to {url}. Start the node with Start_Corvis_Node.bat.")


def cmd_hub_setup(args, cfg) -> None:
    from pathlib import Path

    from .config import DEFAULT_CONFIG, data_dir
    from .hub_setup import run
    try:
        code = run(Path(args.config) if args.config else DEFAULT_CONFIG, args.host or "",
                   Path(args.env_file), data_dir(cfg))
    except (EOFError, KeyboardInterrupt):
        print("\nSetup stopped before it finished. Run the installer again to pick up where you left off.")
        code = 1
    sys.exit(code)


def cmd_pair_pc(args, cfg) -> None:
    from .config import data_dir
    from .nodes import NodeHub
    hub = NodeHub(data_dir(cfg))
    if args.if_none and hub.paired():
        names = ", ".join(n["name"] for n in hub.paired())
        print(f"Your PC is already linked ({names}). To link another computer, run:\n"
              "  sudo corvis pair-pc --name \"Laptop\"")
        return
    _, token = hub.pair(args.name)
    print("\nPairing code for your PC (keep it private; it's shown only once):\n")
    print(f"  {token}\n")
    print("On the PC, double-click Link_PC_To_Hub.bat and paste it when asked.")


def main() -> None:
    global NAME
    p = argparse.ArgumentParser(prog="corvis")
    p.add_argument("--config", help="Path to config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("code", help="Work on a project")
    c.add_argument("--repo", default=".", help="Project folder (Corvis can only touch files in here)")
    c.add_argument("-y", "--yes", action="store_true", help="Auto-approve commands (careful)")
    c.add_argument("--force", action="store_true", help="Allow code mode on Corvis's own folder")
    c.add_argument("task", nargs="*")

    s = sub.add_parser("self-edit", help="Have Corvis change its own code (safely, on a branch)")
    s.add_argument("-y", "--yes", action="store_true", help="Auto-approve commands during the edit")
    s.add_argument("task", nargs="*")

    sub.add_parser("check", help="Test the connection to your local model")

    sub.add_parser("set-password", help="Set the owner password for phone and remote access")
    sub.add_parser("phone-setup", help="Set up phone access through Tailscale, step by step")

    sv = sub.add_parser("serve", help="Run Corvis and keep him running (restarts, rolls back bad updates)")
    sv.add_argument("--no-browser", action="store_true")
    sub.add_parser("node", help="Lend this PC to the Corvis hub (files, apps, games)")
    lk = sub.add_parser("link-pc", help="Link this PC to a Corvis hub")
    lk.add_argument("hub", nargs="?")
    lk.add_argument("code", nargs="?")
    lk.add_argument("--name")
    hs = sub.add_parser("hub-setup", help="On the hub: brain, settings and password (used by the installer)")
    hs.add_argument("--host", default="")
    hs.add_argument("--env-file", default="/etc/corvis.env")
    pp = sub.add_parser("pair-pc", help="On the hub: make a pairing code for a PC")
    pp.add_argument("--name", default="My PC")
    pp.add_argument("--if-none", action="store_true", help="Only if no PC is linked yet")

    w = sub.add_parser("web", help="Open the Corvis chat app in your browser")
    w.add_argument("--no-browser", action="store_true", help="Start the server without opening a tab")
    w.add_argument("--port", type=int, help="Port to use (default from config.yaml, 8765)")

    args = p.parse_args()
    cfg = load_config(args.config)
    NAME = agent_name(cfg)
    {"code": cmd_code, "self-edit": cmd_self_edit, "check": cmd_check, "web": cmd_web,
     "set-password": cmd_set_password, "phone-setup": cmd_phone_setup, "serve": cmd_serve,
     "node": cmd_node, "link-pc": cmd_link_pc, "pair-pc": cmd_pair_pc, "hub-setup": cmd_hub_setup}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
