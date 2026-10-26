"""Drop new tool modules here. Each needs:

    from corvis.tools.base import Tool, params

    def register(reg, ctx):
        reg.register(Tool("my_tool", "What it does", params(["x"], x={"type": "string"}), my_func))

They load automatically on startup. Blender, Unreal, Unity, and system-control
tools will live here, and Corvis can write new ones itself via self-edit.
"""
