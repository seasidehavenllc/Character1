"""A tiny MCP server over stdio, for tests. Tools: echo (read-only), add_note (changes things), fail."""
import json
import sys

NOTES = []
TOOLS = [
    {"name": "echo", "description": "Repeat the text back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "add_note", "description": "Save a note.",
     "inputSchema": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}},
    {"name": "fail", "description": "Always fails.", "inputSchema": {"type": "object", "properties": {}}},
]


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        continue  # notification
    if method == "initialize":
        reply(mid, {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "0.1"}})
    elif method == "tools/list":
        if not params.get("cursor"):
            reply(mid, {"tools": TOOLS[:2], "nextCursor": "page2"})
        else:
            reply(mid, {"tools": TOOLS[2:]})
    elif method == "tools/call":
        name, args = params["name"], params.get("arguments") or {}
        if name == "echo":
            reply(mid, {"content": [{"type": "text", "text": args["text"]}]})
        elif name == "add_note":
            NOTES.append(args["note"])
            reply(mid, {"content": [{"type": "text", "text": f"saved ({len(NOTES)} notes)"}]})
        else:
            reply(mid, {"content": [{"type": "text", "text": "it broke"}], "isError": True})
    else:
        reply(mid, error={"code": -32601, "message": "no such method"})
