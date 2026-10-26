"""Small edits to config.yaml that keep its comments and layout (no YAML library rewrite)."""
from __future__ import annotations

import re


def replace_block(text: str, key: str, block: list[str]) -> str:
    """Replace the top-level `key:` section with `block` lines (or append it)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}:\s*(#.*)?$", ln)), None)
    if start is None:
        return (text.rstrip("\n") + "\n\n" if text.strip() else "") + "\n".join(block) + "\n"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i] and not lines[i].startswith((" ", "\t", "#"))), len(lines))
    # keep comment lines that directly precede the next section with that section
    while end > start + 1 and lines[end - 1].startswith("#"):
        end -= 1
    return "\n".join(lines[:start] + block + lines[end:]).rstrip("\n") + "\n"


def remove_block(text: str, key: str) -> str:
    """Drop the top-level `key:` section, if there is one."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}:(\s|$)", ln)), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines))
                if lines[i] and not lines[i].startswith((" ", "\t", "#"))), len(lines))
    while end > start + 1 and lines[end - 1].startswith("#"):
        end -= 1
    while start > 0 and lines[start - 1].startswith("#"):  # its own comment lines go too
        start -= 1
    out = lines[:start] + lines[end:]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n") + "\n"
