"""Reports which local model and server Corvis is using.

(Rewritten from the first self-edit version, which imported a module that
doesn't exist and so never loaded.)
"""
from corvis.tools.base import Tool, params


def register(reg, ctx):
    def current_model() -> str:
        llm = ctx.config.get("llm", {})
        model = llm.get("model", "qwen3-coder:30b (default)")
        server = llm.get("base_url", "http://localhost:11434/v1 (default)")
        return f"Current model: {model}\nServer: {server}"

    reg.register(Tool(
        "current_model",
        "Tell the owner which local AI model and model server Corvis is running on.",
        params([]),
        current_model,
    ))
