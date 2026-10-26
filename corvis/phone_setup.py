"""One-step phone access through Tailscale (python -m corvis phone-setup).

1. Makes sure there's an owner password.
2. Finds Tailscale (or opens its download page).
3. Signs this PC in to Tailscale if needed.
4. Serves Corvis over HTTPS on your private Tailscale network.
5. Writes the settings into config.yaml (a backup is kept as config.yaml.bak).
6. Prints the address to open on your phone.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path

DOWNLOAD_URL = "https://tailscale.com/download"


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _stream(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    """Run a command while showing its output live, opening any Tailscale link it prints.

    `tailscale serve` may stop and wait for you to turn on HTTPS in your browser; its
    message (with the link) has to be visible, so it can't run silently.
    """
    import time

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors="replace", bufsize=1)
    out, opened, deadline = [], False, time.monotonic() + timeout
    assert proc.stdout is not None
    for line in proc.stdout:
        out.append(line)
        print("  " + line.rstrip())
        link = re.search(r"https://login\.tailscale\.com/\S+", line)
        if link and not opened:
            opened = True
            webbrowser.open(link.group(0))
            print("  -> Opened that page in your browser. Turn it on there; this continues by itself.")
        if time.monotonic() > deadline:
            proc.kill()
            return 1, "".join(out) + "\nTimed out waiting for Tailscale."
    return proc.wait(), "".join(out)


runner = {"run": _run, "interactive": lambda cmd: subprocess.call(cmd), "stream": _stream}


def find_tailscale() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for guess in (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tailscale/tailscale.exe",
                  Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")):
        if guess.is_file():
            return str(guess)
    return None


def status(ts: str) -> dict:
    code, out = runner["run"]([ts, "status", "--json"])
    try:
        return json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        return {"BackendState": "Unknown", "_raw": out}


def machine_name(st: dict) -> str:
    return (st.get("Self", {}) or {}).get("DNSName", "").rstrip(".")


def update_remote_config(text: str, host: str) -> str:
    """Turn on remote access and allow `host`, keeping the rest of config.yaml (and its comments)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^remote:\s*(#.*)?$", ln)), None)
    if start is None:
        return text.rstrip("\n") + f"\n\nremote:\n  enabled: true\n  allowed_hosts: [{host}]\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "#"))),
               len(lines))
    block = lines[start + 1:end]
    seen_enabled = seen_hosts = False
    for i, ln in enumerate(block):
        if re.match(r"^\s+enabled:", ln):
            block[i] = "  enabled: true"
            seen_enabled = True
        m = re.match(r"^\s+allowed_hosts:\s*\[(.*)\]\s*$", ln)
        if m:
            hosts = [h.strip().strip("'\"") for h in m.group(1).split(",") if h.strip()]
            if host not in hosts:
                hosts.append(host)
            block[i] = f"  allowed_hosts: [{', '.join(hosts)}]"
            seen_hosts = True
    if not seen_enabled:
        block.insert(0, "  enabled: true")
    if not seen_hosts:
        block.append(f"  allowed_hosts: [{host}]")
    return "\n".join(lines[:start + 1] + block + lines[end:]) + "\n"


def run(cfg: dict, config_path: Path, ask_password) -> int:
    from .config import data_dir
    from .web.auth import Auth

    port = int((cfg.get("web") or {}).get("port", 8765))
    print("\nSetting up Corvis on your phone (through Tailscale).\n")

    if not Auth(data_dir(cfg)).has_password():
        print("Step 1: an owner password, so only you can sign in from your phone.")
        ask_password()
    else:
        print("Step 1: owner password is set. ✓")

    ts = find_tailscale()
    if not ts:
        print("\nStep 2: Tailscale isn't installed on this PC yet.\n"
              f"  Opening {DOWNLOAD_URL} - install it, sign in, then run this again.")
        webbrowser.open(DOWNLOAD_URL)
        return 1
    print("Step 2: Tailscale is installed. ✓")

    st = status(ts)
    if st.get("BackendState") != "Running":
        print("Step 3: signing this PC in to Tailscale (a browser window may open)...")
        runner["interactive"]([ts, "up"])
        st = status(ts)
        if st.get("BackendState") != "Running":
            print("  Tailscale still isn't connected. Open the Tailscale app, sign in, then run this again.")
            return 1
    print("Step 3: this PC is on your Tailscale network. ✓")

    host = machine_name(st)
    if not host:
        print("  Tailscale didn't report a name for this PC. In the Tailscale admin console, turn on "
              "MagicDNS (DNS page), then run this again.")
        webbrowser.open("https://login.tailscale.com/admin/dns")
        return 1

    print("Step 4: asking Tailscale to serve Corvis over HTTPS...")
    code, out = runner["stream"]([ts, "serve", "--bg", str(port)], 600)
    if code != 0:
        print("  Couldn't start Tailscale serve. Fix the issue above, then run this again.")
        return 1
    print(f"Step 4: Corvis is served privately at https://{host} ✓")

    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    if text:
        config_path.with_suffix(".yaml.bak").write_text(text, encoding="utf-8")
    config_path.write_text(update_remote_config(text, host), encoding="utf-8")
    print("Step 5: remote access turned on in config.yaml. ✓")

    print(f"""
All set. Now, on your phone:
  1. Install Tailscale from the App Store / Google Play and sign in with the same account.
  2. Open  https://{host}  and sign in with your owner password.
  3. Add it to your home screen:
       iPhone:  Safari > Share > Add to Home Screen
       Android: Chrome > ⋮ > Install app
If Corvis is already running, restart him (the restart button, or close and reopen Start_Corvis.bat).
""")
    return 0
