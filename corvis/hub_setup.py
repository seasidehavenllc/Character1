"""Hub setup (run by deploy/install_hub.sh): python -m corvis hub-setup --host NAME --env-file PATH

Asks for the OpenRouter key, picks and tests a model, writes the hub's config.yaml and the
private key file, and sets the owner password. Safe to run again: it keeps what's there
unless you choose to change it.
"""
from __future__ import annotations

import getpass as _getpass
import os
from pathlib import Path

import requests

from .config_edit import remove_block, replace_block
from .llm import ChatLLM, LLMError

# Any OpenAI-compatible service works; OpenRouter is the default.
BASE_URL = os.environ.get("CORVIS_LLM_BASE_URL", "https://openrouter.ai/api/v1")
KEY_VAR = "OPENROUTER_API_KEY"
PREFERRED = ("qwen/qwen3-coder", "qwen3-coder", "deepseek", "glm", "kimi", "gpt-oss")
# For photos and screenshots (coding models are usually blind): cheap, good at reading text.
VISION_PREFERRED = ("google/gemini-2.5-flash", "gemini-2.5-flash", "gemini", "qwen2.5-vl", "qwen-vl",
                    "gpt-4o-mini", "gpt-4.1-mini")


def fetch_models() -> list[dict]:
    try:
        r = requests.get(f"{BASE_URL}/models", timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except (requests.RequestException, ValueError):
        return []


runner = {"models": fetch_models}


def tool_models(models: list[dict]) -> list[dict]:
    if not any("supported_parameters" in m for m in models):
        return models  # this service doesn't say which models support tools: trust the owner
    return [m for m in models if "tools" in (m.get("supported_parameters") or [])]


def suggest(models: list[dict]) -> str:
    ids = [m["id"] for m in tool_models(models)]
    for want in PREFERRED:
        for i in ids:
            if i.startswith(want) or want in i:
                return i
    return ids[0] if ids else ""


def sees_images(m: dict) -> bool:
    return "image" in ((m.get("architecture") or {}).get("input_modalities") or [])


def suggest_vision(models: list[dict]) -> str:
    ids = [m["id"] for m in models if sees_images(m) and ":free" not in m["id"]]
    for want in VISION_PREFERRED:
        for i in ids:
            if i.startswith(want) or want in i:
                return i
    return ""


def price(m: dict) -> str:
    p = m.get("pricing") or {}
    try:
        return f"${float(p.get('prompt', 0)) * 1e6:.2f} in / ${float(p.get('completion', 0)) * 1e6:.2f} out per million tokens"
    except (TypeError, ValueError):
        return "price unknown"


def read_env(env_file: Path) -> dict:
    out = {}
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def write_env(env_file: Path, values: dict) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("# Corvis hub secrets (read only by the service)\n" +
                        "".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    os.chmod(env_file, 0o600)


def hub_config(model: str, host: str, existing: str, vision: str = "") -> str:
    blocks = {
        "llm": ["llm:", "  # The hub's brain: a cloud model through OpenRouter. The key lives in the service's",
                "  # private environment file, not here.", f"  base_url: {BASE_URL}", f"  model: {model}",
                f"  api_key_env: {KEY_VAR}", "  temperature: 0.2", "  max_tokens: 8192", "  timeout: 600"],
        "agent": ["agent:", "  max_steps: 80", "  max_context_chars: 400000", "  tool_output_chars: 12000"],
        "web": ["web:", "  # Reached through Tailscale (tailscale serve), never directly from the internet.",
                "  host: 127.0.0.1", "  port: 8765", "  open_browser: false",
                "  default_workspace: /home/corvis/projects"],
        "remote": ["remote:", "  enabled: true", f"  allowed_hosts: [{host}]" if host else "  allowed_hosts: []"],
        "pc_access": ["pc_access:", "  # This server's own disk stays off limits. Your PC's files come through",
                      "  # Corvis Node when your PC is on.", "  enabled: false"],
        "apps": ["apps:", "  enabled: false   # apps and games are on your PC, through Corvis Node"],
        "vision": ["vision:", "  # Looks at photos and screenshots you send (the coding model can't see).",
                   f"  model: {vision}" if vision else '  model: ""', f"  base_url: {BASE_URL}",
                   "  main_model_sees_images: false"],
    }
    text = existing or "name: Corvis\n\n# How Corvis talks. Empty = the default.\npersonality: \"\"\n"
    for key, block in blocks.items():
        text = replace_block(text, key, block)
    for key in ("node", "data_dir"):  # PC-only settings, if this config came from the PC
        text = remove_block(text, key)
    return text


def run(config_path: Path, host: str, env_file: Path, data_dir: Path,
        ask=input, secret=_getpass.getpass, log=print) -> int:
    env = read_env(env_file)
    key = env.get(KEY_VAR, "")
    if key and ask("An OpenRouter key is already saved. Keep it? [Y/n] ").strip().lower() in ("", "y", "yes"):
        pass
    else:
        log("Paste your OpenRouter API key (it starts with sk-or-). It won't show as you paste.")
        key = secret("OpenRouter key: ").strip()
        if not key:
            log("No key given; stopping.")
            return 1

    models = runner["models"]()
    current = current_vision = ""
    if config_path.is_file():
        import yaml
        llm = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}).get("llm") or {}
        if "openrouter" in str(llm.get("base_url", "")):
            current = str(llm.get("model") or "")
        vis = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}).get("vision") or {}
        if "openrouter" in str(vis.get("base_url", "")):
            current_vision = str(vis.get("model") or "")
    default = current or suggest(models)
    if models:
        log(f"\n{len(tool_models(models))} OpenRouter models can use tools (Corvis needs that).")
        if default:
            m = next((m for m in models if m["id"] == default), None)
            log(f"Suggested: {default}" + (f"  ({price(m)})" if m else ""))
        log("Browse others at https://openrouter.ai/models (filter: Tools). Paste a model id to use it.")
    while True:
        model = ask(f"Model [{default}]: ").strip() or default
        if not model:
            continue
        if models and model not in {m["id"] for m in models}:
            close = [m["id"] for m in models if model.lower() in m["id"].lower()][:6]
            log(f"'{model}' isn't on OpenRouter." + (f" Did you mean: {', '.join(close)}" if close else ""))
            continue
        if models and model not in {m["id"] for m in tool_models(models)}:
            log(f"Warning: {model} doesn't support tool use, so Corvis couldn't act. Pick another.")
            continue
        log(f"Testing {model}...")
        try:
            reply = ChatLLM(base_url=BASE_URL, model=model, api_key=key, max_tokens=20, timeout=60).chat(
                [{"role": "user", "content": "Reply with exactly: online"}])
            log(f"  It answered: {reply.content.strip()[:60]!r}  ✓")
            break
        except LLMError as e:
            log(f"  That didn't work: {e}\n  Check the key and that your OpenRouter account has credit.")
            if ask("Try again with a different key? [y/N] ").strip().lower() in ("y", "yes"):
                key = secret("OpenRouter key: ").strip()

    env[KEY_VAR] = key
    write_env(env_file, env)
    existing = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    vision = current_vision or suggest_vision(models)
    if vision:
        log(f"Photos and screenshots will be read by {vision}.")
    else:
        log("No image model found, so Corvis will say he can't see photos. Set vision.model later if you like.")
    config_path.write_text(hub_config(model, host, existing, vision), encoding="utf-8")
    log(f"Saved settings to {config_path}.")

    from .web.auth import MIN_PASSWORD, Auth
    auth = Auth(data_dir)
    if not auth.has_password():
        log(f"\nChoose the owner password you'll sign in with on your phone (at least {MIN_PASSWORD} characters).")
        while True:
            first = secret("New password: ")
            if len(first) < MIN_PASSWORD:
                log("Too short.")
                continue
            if secret("Type it again: ") != first:
                log("Those didn't match.")
                continue
            auth.set_password(first)
            break
    else:
        log("Owner password is already set (it came with your chats).")
    return 0
