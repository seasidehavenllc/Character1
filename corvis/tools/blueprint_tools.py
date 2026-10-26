"""Blueprint tools: Corvis finds, opens, designs, edits, tests and exports the owner's hologram
blueprints, and steers the hologram the owner is watching."""
from __future__ import annotations

from .. import blueprint_finder as finder
from .. import blueprint_geom as geom
from .. import blueprint_sim as sim
from ..blueprints import MATERIALS, SHAPES, TEMPLATES, BlueprintStore, describe
from ..internet import WebError
from ..meshes import MeshStore, ModelError, import_model
from ..shape_library import ShapeLibrary
from .base import Tool, ToolContext, ToolRegistry, params

DESIGN_SHAPES = [s for s in SHAPES if s != "mesh"]
PART_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "from_library": {"type": "string", "description": "id of a shape from find_shapes; other fields override it"},
        "shape": {"type": "string", "enum": DESIGN_SHAPES},
        "size": {"type": "array", "items": {"type": "number"},
                 "description": "metres. box: [width, height, depth]; cylinder/cone/capsule: [radius, height, 0]; "
                                "sphere: [radius, 0, 0]; torus: [ring radius, tube radius, 0]; tube: [outer radius, "
                                "height, inner radius]; extrude: [width, height, depth] of the extruded outline; "
                                "lathe: [diameter, height, diameter]"},
        "profile": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                    "description": "extrude/lathe only: the 2D outline as [x, y] points in metres. extrude pushes it "
                                   "out along z (car body side views, brackets, wings); lathe spins it round the y "
                                   "axis with x as the radius (wheel rims, nozzles, vases, domes)"},
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
ACTIONS = ("open", "split", "assemble", "isolate", "show_all", "focus", "hide", "show", "highlight", "spin",
           "stop_spin", "test", "export", "reset_view")
_found: dict[str, list[dict]] = {}   # the last search's results, per chat


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    data_dir = ctx.state.get("data_dir")
    if not data_dir or (ctx.config.get("blueprints") or {}).get("enabled", True) is False:
        return
    store = BlueprintStore(data_dir)
    meshes = MeshStore(data_dir)
    library = ShapeLibrary(data_dir)
    conv = ctx.state.get("conversation_id") or "-"

    def part_ids(bp: dict, refs) -> list[str]:
        """Part names or ids -> ids. 'wheels' matches every part with 'wheel' in its name."""
        if not refs:
            return []
        out = []
        for ref in [refs] if isinstance(refs, str) else refs:
            r = str(ref).strip().lower()
            hits = [p["id"] for p in bp["parts"] if p["id"] == r or p["name"].lower() == r]
            if not hits:
                stem = r[:-1] if r.endswith("s") else r
                hits = [p["id"] for p in bp["parts"] if stem and stem in p["name"].lower()]
            if not hits:
                raise KeyError(f"No part called '{ref}' in {bp['name']}.")
            out.extend(h for h in hits if h not in out)
        return out

    def expand(parts: list | None) -> list | None:
        """Parts that say from_library become full parts from the shape library."""
        if not parts:
            return parts
        return [library.to_part(p["from_library"], p) if isinstance(p, dict) and p.get("from_library") else p
                for p in parts]

    def show(bp: dict, action: str, parts: list[str] | None = None, amount=None, say: str = "") -> None:
        store.command(bp["id"], action, parts, amount, say)

    def list_blueprints() -> str:
        items = store.list()
        if not items:
            return "No blueprints yet. Templates you can start from: " + ", ".join(TEMPLATES)
        return "\n".join(f"- {b['name']} (id {b['id']}, {b['parts']} parts)" for b in items)

    def open_blueprints(blueprint: str = "") -> str:
        if blueprint:
            bp = store.find(blueprint)
            show(bp, "open")
            return f"Opening the {bp['name']} blueprint as a hologram for the owner (id {bp['id']})."
        store.command(None, "open")
        return "Opening the blueprints hologram workshop for the owner."

    def show_blueprint(blueprint: str) -> str:
        return describe(store.find(blueprint))

    def create_blueprint(name: str, template: str = "blank", description: str = "", parts: list | None = None) -> str:
        bp = store.create(name, template, description, expand(parts), source={"kind": "corvis", "site": "Corvis"})
        show(bp, "open", say=f"New blueprint: {bp['name']}")
        return f"Created blueprint '{bp['name']}' (id {bp['id']}) with {len(bp['parts'])} parts. " \
               "It's open in the owner's hologram."

    def edit_blueprint(blueprint: str, add_parts: list | None = None, update_parts: list | None = None,
                       remove_parts: list | None = None) -> str:
        bp = store.find(blueprint)
        before = {p["id"] for p in bp["parts"]}
        changed = [u.get("part") for u in update_parts or [] if isinstance(u, dict)]
        changed_ids = part_ids(bp, changed) if changed else []
        bp = store.edit(bp["id"], add=expand(add_parts), update=update_parts, remove=remove_parts)
        new = [p["id"] for p in bp["parts"] if p["id"] not in before]
        named = lambda ids: ", ".join(p["name"] for p in bp["parts"] if p["id"] in ids)
        bits = [f"added {named(new)}" if new else "", f"changed {named(changed_ids)}" if changed_ids else "",
                f"removed {', '.join(map(str, remove_parts))}" if remove_parts else ""]
        summary = "; ".join(b for b in bits if b) or "no changes"
        show(bp, "highlight", new + changed_ids, say=summary[:1].upper() + summary[1:])
        return f"Updated '{bp['name']}' ({summary}); it now has {len(bp['parts'])} parts. The owner watched it change."

    def delete_blueprint(blueprint: str) -> str:
        bp = store.find(blueprint)
        store.delete(bp["id"])
        return f"Deleted the blueprint '{bp['name']}'."

    def undo_blueprint(blueprint: str) -> str:
        bp = store.undo(store.find(blueprint)["id"])
        show(bp, "highlight", say="Undid the last change")
        return f"Undid the last change to '{bp['name']}' ({len(bp['parts'])} parts now)."

    def test_blueprint(blueprint: str, situation: str, settings: dict | None = None) -> str:
        bp = store.find(blueprint)
        show(bp, "test", [situation], settings or {})
        return sim.report(sim.run(bp, situation, settings or {}), bp)

    def hologram(action: str, blueprint: str = "", parts: list | None = None, amount: float | None = None,
                 format: str = "", say: str = "") -> str:
        if action not in ACTIONS:
            raise ValueError(f"Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}.")
        bp = store.find(blueprint) if blueprint else (store.get(store.list()[0]["id"]) if store.list() else None)
        if bp is None:
            raise ValueError("There's no blueprint to show yet.")
        if action == "export":
            parts = [format or "stl"]
        elif action == "test":
            parts = parts or ["load"]
        else:
            parts = part_ids(bp, parts)
        show(bp, action, parts, amount, say)
        return f"Done: {action.replace('_', ' ')} on {bp['name']}" + (f" ({len(parts)} parts)" if parts and action not in ("export", "test") else "") + "."

    def find_blueprint(query: str) -> str:
        r = finder.find(query, ctx.config, data_dir)
        if r["blocked"]:
            return r["blocked"]
        _found[conv] = r["results"]
        lines = [f"Search for '{r['search']}':"] + [f"NOTE: {n}" for n in r["notes"]]
        for i, x in enumerate(r["results"], 1):
            lines.append(f"{i}. {x['title']} [{x['format'].upper()}] from {x['site']} — "
                         f"{'official' if x['kind'] == 'official' else 'community-made'}; licence: {x['license'] or 'unknown'}"
                         + (f"; by {x['author']}" if x.get("author") else "") + f"\n   {x['url']}")
        if r["pages"]:
            lines.append("Pages that may have models (need a direct file link):")
            lines.extend(f"- {p['title']} {p['url']}" for p in r["pages"][:5])
        lines.extend(f"PROBLEM: {p}" for p in r["problems"])
        lines.append("Tell the owner honestly what you found (official or community-made, and the notes above). "
                     "Use import_blueprint with a result number to pull one into the hologram.")
        return "\n".join(lines)

    def import_blueprint(result: int = 0, url: str = "", name: str = "", real_height_m: float = 0,
                         real_length_m: float = 0, units: str = "auto", material: str = "", into: str = "") -> str:
        found = _found.get(conv, [])
        if result:
            if not 1 <= int(result) <= len(found):
                raise ValueError("No such search result. Run find_blueprint first, or give a direct url.")
            pick = found[int(result) - 1]
        elif url:
            pick = {"url": url, "title": "", "site": "", "kind": "community", "license": "unknown", "author": ""}
        else:
            raise ValueError("Give a result number from find_blueprint, or a direct model url.")
        try:
            fname, data = finder.download(pick["url"], ctx.config)
        except WebError as e:
            return f"ERROR: couldn't download it: {e}"
        fit = ("height", real_height_m) if real_height_m else ("length", real_length_m) if real_length_m else None
        source = {"title": pick.get("title") or fname, "url": pick.get("page") or pick["url"], "site": pick.get("site") or "",
                  "author": pick.get("author", ""), "license": pick.get("license", ""), "kind": pick.get("kind", "community")}
        try:
            parts, facts = import_model(meshes, fname, data, units=units, fit=fit, source=source)
        except ModelError as e:
            return f"ERROR: {e}"
        if material:
            for p in parts:
                p["material"] = material
        label = name or pick.get("title") or fname.rsplit(".", 1)[0]
        if into:
            bp = store.edit(store.find(into)["id"], add=parts)
        else:
            bp = store.create(label, "blank", f"Imported from {source['site'] or 'the web'}.", parts, source=source)
        learned = library.learn(bp["parts"][-len(parts):], label, source)
        show(bp, "open", say=f"Pulled in {label}")
        s = facts["size_m"]
        return (f"Pulled '{label}' into the hologram (blueprint {bp['id']}): {facts['components']} components, "
                f"{facts['triangles']:,} triangles{' (simplified from ' + format(facts['original_triangles'], ',') + ')' if facts['simplified'] else ''}, "
                f"about {s[0]:g} x {s[1]:g} x {s[2]:g} m{'' if fit else ' (scale guessed from the file; give real_height_m or real_length_m to fix it)'}. "
                f"Source: {source['site'] or source['url']} ({'official' if source['kind'] == 'official' else 'community-made'}, "
                f"licence {source['license'] or 'unknown'}). {learned} new shapes added to the library.")

    def find_shapes(query: str = "") -> str:
        items = library.search(query)
        if not items:
            return "No shapes in the library match. Shapes are added when models are imported or saved."
        return "\n".join(f"- {s['name']} (id {s['id']}; {s['part']['shape']}; size {s['part']['size']}"
                         + (f"; from {s['learned_from']}" if s.get("learned_from") else "") + ")" for s in items)

    def save_shape(blueprint: str, part: str, name: str = "", tags: str = "") -> str:
        bp = store.find(blueprint)
        pid = part_ids(bp, part)[0]
        p = next(x for x in bp["parts"] if x["id"] == pid)
        s = library.add(p, name or p["name"], tags, bp.get("source"), learned_from=bp["name"])
        return f"Saved '{s['name']}' to the shape library (id {s['id']})."

    def export_blueprint(blueprint: str, format: str = "stl", parts: list | None = None) -> str:
        bp = store.find(blueprint)
        data, fname = geom.export(bp, format, meshes, part_ids(bp, parts) or None)
        target = ctx.workspace.resolve(f"blueprint_exports/{fname}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return (f"Exported {bp['name']} as {format.upper()} ({len(data) // 1024 or 1} KB) to {target}. "
                f"{geom.FORMATS.get(format.lower(), '')}. The owner can also download it from the hologram's Export menu.")

    reg.register(Tool("list_blueprints", "List the owner's hologram blueprints.", params([]), list_blueprints))
    reg.register(Tool(
        "open_blueprints",
        "Open the Blueprints hologram workshop on the owner's screen (optionally on one blueprint). "
        "Use when the owner says things like 'open blueprints' or 'show me the rover blueprint'.",
        params([], blueprint={"type": "string", "description": "name or id; leave empty for the library"}),
        open_blueprints))
    reg.register(Tool("show_blueprint", "Read a blueprint's parts, sizes, materials, mass and source.",
                      params(["blueprint"], blueprint={"type": "string"}), show_blueprint))
    reg.register(Tool(
        "create_blueprint",
        "Create a new hologram blueprint, from a template (" + ", ".join(TEMPLATES) + ") and/or your own parts. "
        "Use smooth shapes (extrude, lathe, tube) and library shapes (find_shapes) for realistic designs, not "
        "just boxes; y is up and the floor is y=0.",
        params(["name"], name={"type": "string"}, template={"type": "string", "enum": list(TEMPLATES)},
               description={"type": "string"}, parts={"type": "array", "items": PART_SCHEMA}),
        create_blueprint))
    reg.register(Tool(
        "edit_blueprint",
        "Change a blueprint: add parts (new ones, or from_library), update parts (each update = {'part': name or "
        "id, ...fields to change}; e.g. replace a part's shape, move it, resize it), or remove parts. The owner "
        "watches the hologram animate each change.",
        params(["blueprint"], blueprint={"type": "string"},
               add_parts={"type": "array", "items": PART_SCHEMA},
               update_parts={"type": "array", "items": {"type": "object"}},
               remove_parts={"type": "array", "items": {"type": "string"}}),
        edit_blueprint))
    reg.register(Tool("delete_blueprint", "Delete a blueprint (asks the owner first).",
                      params(["blueprint"], blueprint={"type": "string"}), delete_blueprint, needs_approval=True))
    reg.register(Tool("undo_blueprint", "Undo the last change to a blueprint (yours or the owner's).",
                      params(["blueprint"], blueprint={"type": "string"}), undo_blueprint))
    reg.register(Tool(
        "test_blueprint",
        "Run a quick test on a blueprint and get the weak points: load (settings: load_n), heat (ambient_c, "
        "extra_c, duty, airflow), drop (height_m, surface), wind (speed_ms) or power (duty). The owner sees it "
        "play out on the hologram. These are first-pass estimates; say so when you report them.",
        params(["blueprint", "situation"], blueprint={"type": "string"},
               situation={"type": "string", "enum": list(sim.SITUATIONS)}, settings={"type": "object"}),
        test_blueprint))
    reg.register(Tool(
        "hologram",
        "Control the hologram the owner is looking at, live: open a blueprint, split it apart (amount 0-1) or put "
        "it back together, isolate/hide/show/highlight/focus on parts, spin, reset the view, run a test, or "
        "export (format: stl, 3mf, obj, glb, dxf, svg; the file downloads on the owner's screen). Use it whenever "
        "the owner asks to see something, e.g. 'split it', 'show me just the wheels'.",
        params(["action"], action={"type": "string", "enum": list(ACTIONS)}, blueprint={"type": "string"},
               parts={"type": "array", "items": {"type": "string"}}, amount={"type": "number"},
               format={"type": "string"}, say={"type": "string", "description": "a short caption to show"}),
        hologram))
    reg.register(Tool(
        "find_blueprint",
        "Search online for a real, downloadable 3D model or blueprint of something (Wikimedia Commons, NASA's "
        "3D library, the web). Results say if they're official or community-made and their licence. Be honest: "
        "if the real design is classified or a company's private CAD, or nothing downloadable exists, say so.",
        params(["query"], query={"type": "string"}), find_blueprint))
    reg.register(Tool(
        "import_blueprint",
        "Pull a 3D model into the hologram as a new blueprint (or into an existing one) from a find_blueprint "
        "result number or a direct model url (STL, OBJ, GLB, 3MF, PLY, or a zip of one). Its pieces become parts "
        "the owner can split, move and edit, and are filed in the shape library. Give real_height_m or "
        "real_length_m when you know the real size (the Eiffel Tower is 330 m tall).",
        params([], result={"type": "integer"}, url={"type": "string"}, name={"type": "string"},
               real_height_m={"type": "number"}, real_length_m={"type": "number"},
               units={"type": "string", "enum": ["auto", "mm", "cm", "m", "in", "ft"]},
               material={"type": "string", "enum": list(MATERIALS)},
               into={"type": "string", "description": "a blueprint to add it to, instead of a new one"}),
        import_blueprint))
    reg.register(Tool("find_shapes", "Search the shape library (shapes learned from imported models and saved parts).",
                      params([], query={"type": "string"}), find_shapes))
    reg.register(Tool("save_shape", "Save a blueprint part's shape to the shape library for reuse.",
                      params(["blueprint", "part"], blueprint={"type": "string"}, part={"type": "string"},
                             name={"type": "string"}, tags={"type": "string"}), save_shape))
    reg.register(Tool(
        "export_blueprint",
        "Save a blueprint as a file in the project folder (blueprint_exports/): " + "; ".join(
            f"{k}: {v}" for k, v in geom.FORMATS.items()) + ".",
        params(["blueprint"], blueprint={"type": "string"}, format={"type": "string", "enum": list(geom.FORMATS)},
               parts={"type": "array", "items": {"type": "string"}}),
        export_blueprint))
