"""Files and photos you send Corvis in chat.

Stored in data/uploads/<id>/<filename>. When you send a message with attachments,
Corvis gets their contents along with it: text and code inline (big files in parts),
PDFs and Word documents as extracted text, zip archives as a file list, and images as
a description from the vision model.
"""
from __future__ import annotations

import json
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_MESSAGE = 10
INLINE_CHARS_PER_FILE = 12_000
INLINE_CHARS_TOTAL = 30_000

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
TEXT_EXTS = set("""
.txt .md .markdown .rst .log .csv .tsv .json .jsonc .yaml .yml .toml .ini .cfg .conf .env.example
.xml .html .htm .css .scss .less .js .jsx .mjs .cjs .ts .tsx .vue .svelte .py .pyw .rb .php .pl
.lua .go .rs .java .kt .kts .scala .swift .c .h .cc .cpp .cxx .hpp .hh .inl .cs .fs .vb .m .mm
.gd .gdshader .tscn .tres .godot .shader .hlsl .glsl .vert .frag .comp .usf .ush .uproject
.uplugin .asmdef .unity .prefab .mat .meta .sh .bash .zsh .ps1 .psm1 .bat .cmd .sql .graphql
.proto .gradle .cmake .mk .makefile .dockerfile .gitignore .editorconfig .svg .tex .r .dart
.ex .exs .erl .clj .hs .ml .zig .nim .jl .sol .ipynb
""".split())
LANG_BY_EXT = {".py": "python", ".cs": "csharp", ".cpp": "cpp", ".cc": "cpp", ".h": "cpp",
               ".hpp": "cpp", ".c": "c", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
               ".gd": "gdscript", ".rs": "rust", ".go": "go", ".java": "java", ".json": "json",
               ".yaml": "yaml", ".yml": "yaml", ".md": "markdown", ".html": "html", ".css": "css",
               ".sh": "bash", ".ps1": "powershell", ".bat": "batch", ".sql": "sql", ".lua": "lua",
               ".hlsl": "hlsl", ".glsl": "glsl", ".xml": "xml", ".toml": "toml", ".ini": "ini"}

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    name = Path(str(name).replace("\\", "/")).name.strip().strip(".")
    name = _UNSAFE.sub("_", name)[:120]
    return name or "file"


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} MB"


def detect_kind(name: str, data: bytes, mime: str = "") -> tuple[str, str]:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_TYPES:
        return "image", IMAGE_TYPES[ext]
    if ext == ".pdf" or data[:5] == b"%PDF-":
        return "pdf", "application/pdf"
    if ext == ".docx":
        return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".zip":
        return "archive", "application/zip"
    if ext in TEXT_EXTS or Path(name).name.lower() in {"makefile", "dockerfile", "readme", "license"}:
        return "text", "text/plain"
    sample = data[:4096]
    if b"\x00" not in sample:
        try:
            sample.decode("utf-8")
            return "text", "text/plain"
        except UnicodeDecodeError:
            pass
    return "binary", mime or "application/octet-stream"


class AttachmentStore:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, data: bytes, mime: str = "") -> dict:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"That file is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        if not data:
            raise ValueError("That file is empty.")
        name = safe_name(name)
        kind, mime = detect_kind(name, data, mime)
        aid = uuid.uuid4().hex[:16]
        folder = self.root / aid
        folder.mkdir(parents=True)
        (folder / name).write_bytes(data)
        meta = {"id": aid, "name": name, "size": len(data), "kind": kind, "mime": mime, "ts": time.time()}
        (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def get(self, aid: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{16}", aid or ""):
            raise KeyError(aid)
        path = self.root / aid / "meta.json"
        if not path.is_file():
            raise KeyError(aid)
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, meta: dict) -> None:
        (self.root / meta["id"] / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def path(self, meta: dict) -> Path:
        return self.root / meta["id"] / meta["name"]

    # --- reading ----------------------------------------------------------------
    def text(self, meta: dict) -> str | None:
        """The attachment as text, or None if it has no readable text."""
        cache = self.root / meta["id"] / "extracted.txt"
        if cache.is_file():
            return cache.read_text(encoding="utf-8")
        kind, path = meta["kind"], self.path(meta)
        if kind == "text":
            raw = path.read_bytes()
            enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
            out = raw.decode(enc, errors="replace")
        elif kind == "pdf":
            out = _pdf_text(path)
        elif kind == "docx":
            out = _docx_text(path)
        elif kind == "archive":
            out = _zip_listing(path)
        else:
            return None
        if out is not None and kind != "text":
            cache.write_text(out, encoding="utf-8")
        return out


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "(Corvis can't read PDFs yet: run Setup_Corvis.bat again to install pypdf.)"
    try:
        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages, 1):
            pages.append(f"--- page {i} ---\n{(page.extract_text() or '').strip()}")
        text = "\n\n".join(pages).strip()
        if not any(p.split("\n", 1)[-1].strip() for p in pages):
            return "(This PDF has no text layer; it's probably scanned images.)"
        return text
    except Exception as e:
        return f"(Couldn't read this PDF: {e})"


def _docx_text(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except Exception as e:
        return f"(Couldn't read this Word document: {e})"
    paras = []
    for p in root.iter(f"{ns}p"):
        parts = []
        for node in p.iter():
            if node.tag == f"{ns}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{ns}tab":
                parts.append("\t")
        paras.append("".join(parts))
    return "\n".join(paras).strip()


def _zip_listing(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        return "(This zip file is damaged.)"
    lines = [f"{i.filename} ({human_size(i.file_size)})" for i in infos[:300] if not i.is_dir()]
    more = f"\n... and {len(infos) - 300} more" if len(infos) > 300 else ""
    return f"Zip archive with {len(infos)} entries:\n" + "\n".join(lines) + more


# --- building the message Corvis sees ------------------------------------------------
def message_block(metas: list[dict], store: AttachmentStore, cfg: dict,
                  emit: Callable[[str, str], None] = lambda k, t: None) -> str:
    """Text added to the owner's message so the model knows what was attached."""
    if not metas:
        return ""
    from .vision import look, vision_cfg
    from .llm import LLMError

    lines = ["\n\n[The owner attached these files to this message. Attachment ids work with "
             "read_attachment, look_at_image and save_attachment.]"]
    budget = INLINE_CHARS_TOTAL
    can_see = vision_cfg(cfg) is not None
    for meta in metas:
        head = f"\n### {meta['name']} ({human_size(meta['size'])}, attachment {meta['id']})"
        if meta["kind"] == "image":
            if not can_see:
                lines.append(head + "\n(Image. You can't see images because no vision model is set "
                             "up. Tell the owner they can add one under vision: in config.yaml, "
                             "for example qwen2.5vl:7b.)")
                continue
            emit("tool", f"look_at_image attachment={meta['name']}")
            try:
                desc = meta.get("description") or look(store.path(meta), meta["mime"], cfg)
                if not meta.get("description"):
                    meta["description"] = desc
                    store.update(meta)
                emit("result", desc)
                lines.append(head + "\nImage. What it shows (from the vision model):\n" + desc)
            except LLMError as e:
                emit("result", f"ERROR: {e}")
                lines.append(head + f"\n(Image. Couldn't look at it: {e})")
            continue

        text = store.text(meta)
        if text is None:
            lines.append(head + "\n(Binary file. Use save_attachment to copy it into the project if needed.)")
            continue
        take = min(len(text), INLINE_CHARS_PER_FILE, max(0, budget))
        budget -= take
        lang = LANG_BY_EXT.get(Path(meta["name"]).suffix.lower(), "")
        body = text[:take]
        fence = "```" if "```" not in body else "~~~~"
        part = f"{head}\n{fence}{lang}\n{body}\n{fence}"
        if take < len(text):
            part += (f"\n[Showing {take} of {len(text)} characters. Call read_attachment with "
                     f"attachment={meta['id']} and start={take} to read the rest.]")
        lines.append(part)
    return "\n".join(lines)
