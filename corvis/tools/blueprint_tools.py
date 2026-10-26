"""Blueprint tools: Corvis opens, designs, edits and tests the owner's hologram blueprints."""
from __future__ import annotations

from .. import blueprint_sim as sim
from ..blueprints import MATERIALS, SHAPES, TEMPLATES, BlueprintStore, describe
from .base import Tool, ToolContext, ToolRegistry, params

PART_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "shape": {"type": "string", "enum": list(SHAPES)},
        "size": {"type": "array", "items": {"type": "number"},
                 "description": "metres. box: [width, height, depth]; cylinder/cone/capsule: [radius, height, 0]; "
                                "sphere: [radius, 0, 0]; torus: [ring radius, tube radius, 0]"},
        "position": {"type": "array", "items": {"type": "number"}, "description": "centre [x, y, z] in metres; y is up"},
        "rotation": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z] degrees"},
        "material": {"type": "string", "enum": list(MATERIALS)},
        "group": {"type": "string", "description": "subsystem, e.g. Frame, Drive, Power"},
        "power_w": {"type": "number", "description": "watts it uses (negative if it supplies power)"},
        "battery_wh": {"type": "number"},
        "infill": {"type": "number", "description": "0.05-1: how solid it is (hollow frames, 3D-print infill)"},
        "notes": {"type": "string"},
    },
}


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    data_dir = ctx.state.get("data_dir")
    if not data_dir or (ctx.config.get("blueprints") or {}).get("enabled", True) is False:
        return
    store = BlueprintStore(data_dir)

    def list_blueprints() -> str:
        items = store.list()
        if not items:
            return "No blueprints yet. Templates you can start from: " + ", ".join(TEMPLATES)
        return "\n".join(f"- {b['name']} (id {b['id']}, {b['parts']} parts)" for b in items)

    def open_blueprints(blueprint: str = "") -> str:
        if blueprint:
            bp = store.find(blueprint)
            return f"Opening the {bp['name']} blueprint as a hologram for the owner (id {bp['id']})."
        return "Opening the blueprints hologram workshop for the owner."

    def show_blueprint(blueprint: str) -> str:
        return describe(store.find(blueprint))

    def create_blueprint(name: str, template: str = "blank", description: str = "",
                         parts: list | None = None) -> str:
        bp = store.create(name, template, description, parts)
        return f"Created blueprint '{bp['name']}' (id {bp['id']}) with {len(bp['parts'])} parts. " \
               "It's in the owner's Blueprints workshop."

    def edit_blueprint(blueprint: str, add_parts: list | None = None, update_parts: list | None = None,
                       remove_parts: list | None = None) -> str:
        bp = store.find(blueprint)
        bp = store.edit(bp["id"], add=add_parts, update=update_parts, remove=remove_parts)
        changes = [f"added {len(add_parts)}" if add_parts else "", f"updated {len(update_parts)}" if update_parts else "",
                   f"removed {len(remove_parts)}" if remove_parts else ""]
        return f"Updated '{bp['name']}' ({', '.join(c for c in changes if c) or 'no changes'}); " \
               f"it now has {len(bp['parts'])} parts. The hologram updates live."

    def delete_blueprint(blueprint: str) -> str:
        bp = store.find(blueprint)
        store.delete(bp["id"])
        return f"Deleted the blueprint '{bp['name']}'."

    def test_blueprint(blueprint: str, situation: str, settings: dict | None = None) -> str:
        bp = store.find(blueprint)
        return sim.report(sim.run(bp, situation, settings or {}), bp)

    reg.register(Tool("list_blueprints", "List the owner's hologram blueprints.", params([]), list_blueprints))
    reg.register(Tool(
        "open_blueprints",
        "Open the Blueprints hologram workshop on the owner's screen (optionally on one blueprint). "
        "Use when the owner says things like 'open blueprints' or 'show me the rover blueprint'.",
        params([], blueprint={"type": "string", "description": "name or id; leave empty for the library"}),
        open_blueprints))
    reg.register(Tool("show_blueprint", "Read a blueprint's parts, sizes, materials and mass.",
                      params(["blueprint"], blueprint={"type": "string"}), show_blueprint))
    reg.register(Tool(
        "create_blueprint",
        "Create a new hologram blueprint, from a template (" + ", ".join(TEMPLATES) + ") and/or your own parts. "
        "Build designs from simple parts; y is up and the floor is y=0.",
        params(["name"], name={"type": "string"}, template={"type": "string", "enum": list(TEMPLATES)},
               description={"type": "string"}, parts={"type": "array", "items": PART_SCHEMA}),
        create_blueprint))
    reg.register(Tool(
        "edit_blueprint",
        "Change a blueprint: add parts, update parts (each update = {'part': name or id, ...fields to change}), "
        "or remove parts by name or id. The owner sees the hologram change live.",
        params(["blueprint"], blueprint={"type": "string"},
               add_parts={"type": "array", "items": PART_SCHEMA},
               update_parts={"type": "array", "items": {"type": "object"}},
               remove_parts={"type": "array", "items": {"type": "string"}}),
        edit_blueprint))
    reg.register(Tool("delete_blueprint", "Delete a blueprint (asks the owner first).",
                      params(["blueprint"], blueprint={"type": "string"}), delete_blueprint, needs_approval=True))
    reg.register(Tool(
        "test_blueprint",
        "Run a quick test on a blueprint and get the weak points: load (settings: load_n), heat (ambient_c, "
        "extra_c, duty, airflow), drop (height_m, surface), wind (speed_ms) or power (duty). "
        "These are first-pass estimates; say so when you report them.",
        params(["blueprint", "situation"], blueprint={"type": "string"},
               situation={"type": "string", "enum": list(sim.SITUATIONS)}, settings={"type": "object"}),
        test_blueprint))
