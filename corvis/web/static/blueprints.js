/* Blueprints: hologram workbench. Draws a blueprint's parts as a hologram, splits it apart,
   edits parts, runs quick tests with live colouring, and lets the owner talk to Corvis. */
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";
import { TransformControls } from "/static/vendor/three/TransformControls.js";

const $ = (s) => document.querySelector(s);
const HOLO = new THREE.Color("#39d0ff");
const SELECT = new THREE.Color("#ffb347");
const STATUS = { ok: new THREE.Color("#3ddc97"), warn: new THREE.Color("#ffc857"), fail: new THREE.Color("#ff5d5d") };
const SIZE_LABELS = {
  box: "Size: width, height, depth (m)", cylinder: "Size: radius, height (m)", cone: "Size: radius, height (m)",
  sphere: "Size: radius (m)", torus: "Size: ring radius, tube radius (m)", capsule: "Size: radius, length (m)",
};

const state = {
  meta: null, bp: null, summary: null, version: 0, selected: null, hidden: new Set(), isolated: false,
  dirty: false, saveTimer: null, split: 0, splitShown: 0, test: null, testResult: null, params: {},
  anim: null, conv: null,
};

// ---------- api ----------
async function api(path, opts = {}) {
  const headers = { "X-Corvis": "1" };
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty */ }
  if (res.status === 401 && data.login) { location.replace("/login"); throw new Error("Sign in first."); }
  if (!res.ok) { const e = new Error(data.error || `Error ${res.status}`); e.status = res.status; throw e; }
  return data;
}
let toastTimer;
function toast(text, ms = 4000) {
  const t = $("#toast"); t.textContent = text; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), ms);
}
const num = (v) => (typeof v === "number" ? String(+v.toPrecision(3)) : String(v));
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }

// ---------- 3D scene ----------
const canvas = $("#holo");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.005, 200);
camera.position.set(0.9, 0.7, 1.1);
const orbit = new OrbitControls(camera, canvas);
orbit.enableDamping = true; orbit.autoRotate = true; orbit.autoRotateSpeed = 0.6;
const gizmo = new TransformControls(camera, canvas);
gizmo.setSize(0.8);
gizmo.addEventListener("dragging-changed", (e) => { orbit.enabled = !e.value; if (!e.value) commitGizmo(); });
scene.add(gizmo);

const world = new THREE.Group();           // tilts/falls during tests
const assembly = new THREE.Group();        // the parts
world.add(assembly);
scene.add(world);

// floor: grid, rings and a slow scan line
const floor = new THREE.Group();
scene.add(floor);
function buildFloor(radius) {
  floor.clear();
  const grid = new THREE.GridHelper(radius * 4, 24, 0x1d6f93, 0x123a52);
  grid.material.transparent = true; grid.material.opacity = 0.35;
  floor.add(grid);
  for (const [r, o] of [[radius * 1.15, 0.6], [radius * 1.35, 0.25], [radius * 0.6, 0.18]]) {
    const ring = new THREE.Mesh(new THREE.RingGeometry(r, r * 1.008, 128),
      new THREE.MeshBasicMaterial({ color: HOLO, transparent: true, opacity: o, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.001;
    floor.add(ring);
  }
}
const scan = new THREE.Mesh(new THREE.CircleGeometry(0.5, 96),
  new THREE.MeshBasicMaterial({ color: HOLO, transparent: true, opacity: 0.06, side: THREE.DoubleSide, depthWrite: false,
    blending: THREE.AdditiveBlending }));
scan.rotation.x = -Math.PI / 2;
scene.add(scan);

// wind streaks and load arrows (shown during those tests)
const effects = new THREE.Group();
scene.add(effects);

function geometryFor(p) {
  const [x, y, z] = p.size;
  switch (p.shape) {
    case "box": return new THREE.BoxGeometry(x, y, z);
    case "cylinder": return new THREE.CylinderGeometry(x, x, y, 40);
    case "cone": return new THREE.ConeGeometry(x, y, 40);
    case "sphere": return new THREE.SphereGeometry(x, 24, 16);
    case "torus": return new THREE.TorusGeometry(x, Math.max(y, 0.0005), 12, 64);
    default: return new THREE.CapsuleGeometry(x, y, 6, 20);
  }
}
const meshes = new Map(); // part id -> {group, fill, lines, part}

function makePart(p) {
  const geom = geometryFor(p);
  const color = new THREE.Color(p.color || HOLO);
  const fill = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
  const curved = ["sphere", "torus", "capsule"].includes(p.shape);
  const lineGeom = curved ? new THREE.WireframeGeometry(p.shape === "sphere" ? new THREE.SphereGeometry(p.size[0], 14, 8)
    : p.shape === "torus" ? new THREE.TorusGeometry(p.size[0], Math.max(p.size[1], 0.0005), 6, 28)
    : new THREE.CapsuleGeometry(p.size[0], p.size[1], 3, 10)) : new THREE.EdgesGeometry(geom, 25);
  const lines = new THREE.LineSegments(lineGeom, new THREE.LineBasicMaterial({
    color, transparent: true, opacity: curved ? 0.45 : 0.9, blending: THREE.AdditiveBlending }));
  const group = new THREE.Group();
  group.add(fill, lines);
  group.rotation.set(...p.rotation.map((d) => THREE.MathUtils.degToRad(d)));
  group.position.set(...p.position);
  group.userData.partId = p.id;
  fill.userData.partId = p.id;
  return { group, fill, lines, part: p, base: new THREE.Vector3(...p.position), color };
}

let center = new THREE.Vector3(), radius = 0.5;
function rebuild(keepView = true) {
  for (const m of meshes.values()) {
    m.group.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
  }
  gizmo.detach();
  assembly.clear(); meshes.clear();
  const parts = state.bp ? state.bp.parts : [];
  for (const p of parts) {
    const m = makePart(p);
    meshes.set(p.id, m);
    assembly.add(m.group);
  }
  const box = new THREE.Box3().setFromObject(assembly);
  if (!box.isEmpty()) { box.getCenter(center); radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.05); }
  else { center.set(0, 0.1, 0); radius = 0.3; }
  buildFloor(radius);
  scan.scale.set(radius * 2.6, radius * 2.6, 1);
  if (!keepView) fitView();
  if (state.selected && !meshes.has(state.selected)) state.selected = null;
  placeParts(true);
  paint();
  if ($("#move").classList.contains("on") && state.selected) gizmo.attach(meshes.get(state.selected).group);
}

function fitView() {
  orbit.target.copy(center);
  const rect = canvas.getBoundingClientRect();
  const aspect = rect.width / Math.max(rect.height, 1);
  const half = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * Math.min(1, aspect);  // narrower of the two
  const d = radius / half * 1.15 * splitZoom(state.splitShown);
  camera.position.copy(center).add(new THREE.Vector3(0.75, 0.55, 0.95).normalize().multiplyScalar(d));
  camera.near = d / 200; camera.far = d * 50; camera.updateProjectionMatrix();
}

// split: push each part away from the centre of the assembly (the camera backs off to keep it in view)
const splitZoom = (s) => 1 + s * 1.3;
function placeParts(instant) {
  if (instant) state.splitShown = state.split;
  let i = 0;
  for (const m of meshes.values()) {
    const dir = m.base.clone().sub(center);
    if (dir.lengthSq() < 1e-8) dir.set(Math.cos(i * 2.4), 0.3, Math.sin(i * 2.4));
    dir.normalize();
    const away = state.splitShown * radius * 1.4 * (0.6 + 0.4 * ((i * 37) % 10) / 10);
    if (gizmo.object !== m.group || !gizmo.dragging) m.group.position.copy(m.base).addScaledVector(dir, away);
    i++;
  }
}

// colours: selection, isolation, hidden parts, and test results
function paint() {
  const res = state.testResult;
  for (const [id, m] of meshes) {
    let color = m.color, fillOp = 0.12, lineOp = 0.9;
    if (res && res.parts[id]) {
      const r = res.parts[id];
      color = state.test === "heat" ? heatColor(r.ratio) : statusColor(r.ratio);
      fillOp = 0.22;
    }
    if (id === state.selected) { color = SELECT; fillOp = 0.28; }
    const dim = state.hidden.has(id) || (state.isolated && state.selected && id !== state.selected);
    m.group.visible = !state.hidden.has(id);
    m.fill.material.color.copy(color); m.lines.material.color.copy(color);
    m.fill.material.opacity = dim ? 0.02 : fillOp;
    m.lineOp = dim ? 0.06 : lineOp * (["sphere", "torus", "capsule"].includes(m.part.shape) ? 0.5 : 1);
    m.lines.material.opacity = m.lineOp;
  }
}
function statusColor(ratio) {
  if (ratio <= 0.5) return STATUS.ok.clone().lerp(STATUS.warn, ratio / 0.5 * 0.35);
  if (ratio <= 1) return STATUS.warn.clone().lerp(STATUS.fail, (ratio - 0.5) / 0.5 * 0.5);
  return STATUS.fail;
}
function heatColor(ratio) {
  const cold = new THREE.Color("#3d7dff"), warm = new THREE.Color("#ffc857");
  return ratio <= 0.6 ? cold.lerp(warm, ratio / 0.6) : ratio <= 1 ? warm.lerp(STATUS.fail, (ratio - 0.6) / 0.4) : STATUS.fail;
}

// ---------- resize and render loop ----------
function resize() {
  const r = canvas.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / Math.max(r.height, 1); camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas);
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
  if (Math.abs(state.splitShown - state.split) > 0.001) {
    const before = state.splitShown;
    state.splitShown += (state.split - state.splitShown) * Math.min(1, dt * 8);
    const offset = camera.position.clone().sub(orbit.target).multiplyScalar(splitZoom(state.splitShown) / splitZoom(before));
    camera.position.copy(orbit.target).add(offset);
    placeParts(false);
  }
  scan.position.set(center.x, center.y + Math.sin(t * 0.8) * radius * 0.9, center.z);
  scan.material.opacity = 0.05 + 0.03 * Math.sin(t * 3);
  for (const [id, m] of meshes) {   // gentle shimmer; parts that use power pulse
    const pulse = m.part.power_w > 0 && (state.test === "power" || state.test === "heat") ? 0.5 + 0.5 * Math.sin(t * 6 + id.charCodeAt(0)) : 0;
    m.lines.material.opacity = (m.lineOp ?? 0.9) * (0.9 + 0.1 * Math.sin(t * 2 + id.charCodeAt(1)));
    if (pulse) m.fill.material.opacity = 0.12 + 0.18 * pulse;
  }
  if (state.anim) state.anim(dt, t);
  orbit.update();
  renderer.render(scene, camera);
});

// ---------- picking ----------
const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
let downAt = null;
function hit(ev) {
  const r = canvas.getBoundingClientRect();
  pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(pointer, camera);
  const fills = [...meshes.values()].filter((m) => m.group.visible).map((m) => m.fill);
  return ray.intersectObjects(fills, false)[0];
}
canvas.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
canvas.addEventListener("pointerup", (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5 || gizmo.dragging) return;
  const h = hit(e);
  select(h ? h.object.userData.partId : null);
});
canvas.addEventListener("pointermove", (e) => {
  const tip = $("#tooltip");
  if (e.pointerType !== "mouse") return (tip.hidden = true);
  const h = hit(e);
  if (!h) return (tip.hidden = true);
  const m = meshes.get(h.object.userData.partId);
  const r = state.testResult && state.testResult.parts[m.part.id];
  tip.textContent = m.part.name + (r ? ` · ${num(r.value)} ${r.unit}` : "");
  const box = canvas.getBoundingClientRect();
  tip.style.left = `${e.clientX - box.left}px`; tip.style.top = `${e.clientY - box.top}px`;
  tip.hidden = false;
});

function select(id) {
  state.selected = id;
  if (id && $("#move").classList.contains("on")) { setSplit(0); gizmo.attach(meshes.get(id).group); } else gizmo.detach();
  paint(); renderPartForm(); renderPartList();
  if (id) showTab("part");
}

function commitGizmo() {
  const m = state.selected && meshes.get(state.selected);
  if (!m) return;
  const p = m.group.position;
  m.part.position = [p.x, p.y, p.z].map((v) => Math.round(v * 1000) / 1000);
  m.base.copy(p);
  changed(false);
  renderPartForm();
}

// ---------- library ----------
async function loadLibrary() {
  state.meta = await api("/api/blueprints");
  renderLibrary();
  fillSelects();
  renderSituations();
}
function renderLibrary() {
  const list = $("#bp-list");
  list.innerHTML = "";
  if (!state.meta.blueprints.length) list.appendChild(el("li", "empty", "No blueprints yet."));
  for (const b of state.meta.blueprints) {
    const li = el("li", state.bp && state.bp.id === b.id ? "on" : "");
    const open = el("button", "open");
    open.type = "button";
    open.append(el("b", "", b.name), el("small", "", `${b.parts} parts · ${new Date(b.updated * 1000).toLocaleDateString()}`));
    open.addEventListener("click", () => { openBlueprint(b.id); document.body.classList.remove("lib-open"); });
    const del = el("button", "del", "🗑");
    del.type = "button"; del.title = `Delete ${b.name}`; del.setAttribute("aria-label", `Delete ${b.name}`);
    del.addEventListener("click", async () => {
      if (!confirm(`Delete the blueprint "${b.name}"? This can't be undone.`)) return;
      try { state.meta.blueprints = (await api(`/api/blueprints/${b.id}`, { method: "DELETE" })).blueprints; }
      catch (err) { return toast(err.message); }
      if (state.bp && state.bp.id === b.id) closeBlueprint();
      renderLibrary();
    });
    li.append(open, del);
    list.appendChild(li);
  }
  const tpl = $("#templates");
  tpl.innerHTML = "";
  for (const [key, t] of Object.entries(state.meta.templates)) {
    const btn = el("button");
    btn.type = "button";
    btn.append(el("b", "", key === "blank" ? "Blank" : t.name), el("small", "", t.description || "Start from nothing"));
    btn.addEventListener("click", async () => {
      try {
        const r = await api("/api/blueprints", { method: "POST", body: { template: key, name: $("#new-name").value.trim() } });
        $("#new-name").value = ""; $("#new-box").hidden = true;
        state.meta = await api("/api/blueprints");
        renderLibrary();
        openBlueprint(r.blueprint.id);
        document.body.classList.remove("lib-open");
      } catch (err) { toast(err.message); }
    });
    tpl.appendChild(btn);
  }
}
$("#new-toggle").addEventListener("click", () => { $("#new-box").hidden = !$("#new-box").hidden; });

async function openBlueprint(id, keepView = false) {
  let r;
  try { r = await api(`/api/blueprints/${id}`); } catch (err) { return toast(err.message); }
  const switching = !state.bp || state.bp.id !== id;
  state.bp = r.blueprint; state.summary = r.summary; state.version = r.blueprint.version; state.dirty = false;
  if (switching) { state.selected = null; state.hidden.clear(); state.isolated = false; state.testResult = null; clearEffects(); }
  history.replaceState(null, "", `/blueprints?id=${id}`);
  $("#bp-name").value = state.bp.name; $("#bp-name").disabled = false;
  $("#empty-state").hidden = true;
  rebuild(keepView && !switching);
  renderStats(); renderPartForm(); renderPartList(); renderLibrary();
  if (state.test) runTest();
  setSave("Saved");
}
function closeBlueprint() {
  state.bp = null; state.selected = null; state.testResult = null;
  $("#bp-name").value = ""; $("#bp-name").disabled = true; $("#empty-state").hidden = false;
  history.replaceState(null, "", "/blueprints");
  rebuild(); renderStats(); renderPartForm(); renderPartList(); showHeadline(null);
}

// ---------- saving (and seeing Corvis's changes live) ----------
function setSave(text, live = false) { const s = $("#save-state"); s.textContent = text; s.classList.toggle("live", live); }
function changed(rebuildNow = true) {
  state.dirty = true;
  setSave("Saving…");
  if (rebuildNow) rebuild();
  renderStats();
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(save, 500);
}
async function save() {
  if (!state.bp) return;
  try {
    const r = await api(`/api/blueprints/${state.bp.id}`, { method: "PUT",
      body: { name: state.bp.name, description: state.bp.description, parts: state.bp.parts, version: state.version } });
    state.version = r.blueprint.version; state.summary = r.summary; state.dirty = false;
    for (const p of r.blueprint.parts) { const local = state.bp.parts.find((q) => q.id === p.id); if (local) Object.assign(local, p); }
    setSave("Saved"); renderStats();
    if (state.test) runTest();
    const item = state.meta.blueprints.find((b) => b.id === state.bp.id);
    if (item) { item.name = state.bp.name; item.parts = state.bp.parts.length; renderLibrary(); }
  } catch (err) {
    if (err.status === 409) { toast("Corvis changed this blueprint at the same time. Showing his version."); openBlueprint(state.bp.id, true); }
    else { setSave("Not saved"); toast(err.message); }
  }
}
setInterval(async () => {
  if (!state.bp || state.dirty || document.hidden) return;
  try {
    const r = await api(`/api/blueprints/${state.bp.id}`);
    if (r.blueprint.version !== state.version) {
      await openBlueprint(state.bp.id, true);
      setSave("Updated by Corvis just now", true);
    }
  } catch (_) { /* offline for a moment */ }
}, 2000);
$("#bp-name").addEventListener("change", () => {
  if (!state.bp) return;
  state.bp.name = $("#bp-name").value.trim() || state.bp.name;
  changed(false);
});

// ---------- part editor ----------
function fillSelects() {
  $("#shape-select").innerHTML = state.meta.shapes.map((s) => `<option value="${s}">${s}</option>`).join("");
  $("#material-select").innerHTML = Object.entries(state.meta.materials)
    .map(([k, m]) => `<option value="${k}">${m.label}</option>`).join("");
  const add = $("#add-row");
  add.innerHTML = "";
  add.appendChild(el("span", "hint", "Add:"));
  for (const s of state.meta.shapes) {
    const b = el("button", "", s); b.type = "button";
    b.addEventListener("click", () => addPart(s));
    add.appendChild(b);
  }
}
function selectedPart() { return state.bp && state.selected ? state.bp.parts.find((p) => p.id === state.selected) : null; }
function renderPartForm() {
  const p = selectedPart(), form = $("#part-form");
  $("#part-empty").hidden = !!p; form.hidden = !p;
  if (!p) return;
  const f = form.elements;
  f.name.value = p.name; f.shape.value = p.shape; f.material.value = p.material;
  [0, 1, 2].forEach((i) => { f[`size${i}`].value = p.size[i]; f[`pos${i}`].value = p.position[i]; f[`rot${i}`].value = p.rotation[i]; });
  f.power_w.value = p.power_w; f.battery_wh.value = p.battery_wh; f.infill.value = Math.round(p.infill * 100);
  f.group.value = p.group || ""; f.notes.value = p.notes || "";
  $("#size-legend").textContent = SIZE_LABELS[p.shape];
  const used = { box: 3, cylinder: 2, cone: 2, capsule: 2, torus: 2, sphere: 1 }[p.shape];
  [0, 1, 2].forEach((i) => (f[`size${i}`].hidden = i >= used));
  const mat = state.meta.materials[p.material];
  const r = state.testResult && state.testResult.parts[p.id];
  $("#part-facts").textContent = `${(mass(p) * 1000).toFixed(0)} g · ${mat.label} · strength ${mat.yield_mpa} MPa · max ${mat.max_temp_c} °C`
    + (r ? `\n${state.meta.situations[state.test].label}: ${num(r.value)} ${r.unit} (${Math.round(r.ratio * 100)}% of limit)` : "");
}
$("#part-form").addEventListener("input", (e) => {
  const p = selectedPart();
  if (!p) return;
  const f = $("#part-form").elements, num = (v, d) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : d);
  p.name = f.name.value; p.shape = f.shape.value; p.material = f.material.value;
  p.size = [0, 1, 2].map((i) => Math.max(0.001, num(f[`size${i}`].value, p.size[i])));
  p.position = [0, 1, 2].map((i) => num(f[`pos${i}`].value, p.position[i]));
  p.rotation = [0, 1, 2].map((i) => num(f[`rot${i}`].value, p.rotation[i]));
  p.power_w = num(f.power_w.value, 0); p.battery_wh = Math.max(0, num(f.battery_wh.value, 0));
  p.infill = Math.min(1, Math.max(0.05, num(f.infill.value, 100) / 100));
  p.group = f.group.value; p.notes = f.notes.value;
  const geometryChanged = ["shape", "size0", "size1", "size2", "pos0", "pos1", "pos2", "rot0", "rot1", "rot2"].includes(e.target.name);
  changed(geometryChanged);
  if (e.target.name === "shape") renderPartForm();
  renderPartList();
});
function addPart(shape) {
  if (!state.bp) return toast("Open or create a blueprint first.");
  const s = Math.max(radius * 0.25, 0.02);
  const size = { box: [s, s, s], cylinder: [s / 2, s, 0], cone: [s / 2, s, 0], sphere: [s / 2, 0, 0], torus: [s / 2, s / 10, 0], capsule: [s / 3, s, 0] }[shape];
  const part = { id: Math.random().toString(16).slice(2, 10), name: `New ${shape}`, shape, size,
    position: [center.x, center.y + radius * 0.6, center.z], rotation: [0, 0, 0], material: "aluminum",
    group: "", power_w: 0, battery_wh: 0, infill: 1, notes: "" };
  state.bp.parts.push(part);
  changed();
  select(part.id);
}
$("#dup-part").addEventListener("click", () => {
  const p = selectedPart(); if (!p) return;
  const copy = { ...structuredClone(p), id: Math.random().toString(16).slice(2, 10), name: `${p.name} copy` };
  copy.position = [p.position[0] + radius * 0.15, p.position[1], p.position[2]];
  state.bp.parts.push(copy); changed(); select(copy.id);
});
$("#del-part").addEventListener("click", () => {
  const p = selectedPart(); if (!p) return;
  state.bp.parts = state.bp.parts.filter((q) => q.id !== p.id);
  state.selected = null; changed(); renderPartForm(); renderPartList();
});

function renderPartList() {
  const ul = $("#part-list");
  ul.innerHTML = "";
  if (!state.bp) return;
  const groups = {};
  for (const p of state.bp.parts) (groups[p.group || "Other"] ||= []).push(p);
  for (const [g, parts] of Object.entries(groups)) {
    ul.appendChild(el("li", "group", g));
    for (const p of parts) {
      const li = el("li", `part${p.id === state.selected ? " on" : ""}${state.hidden.has(p.id) ? " hidden-part" : ""}`);
      const eye = el("button", "eye", state.hidden.has(p.id) ? "◌" : "◉");
      eye.type = "button"; eye.title = state.hidden.has(p.id) ? "Show" : "Hide";
      eye.addEventListener("click", (e) => {
        e.stopPropagation();
        state.hidden.has(p.id) ? state.hidden.delete(p.id) : state.hidden.add(p.id);
        paint(); renderPartList();
      });
      li.append(eye, el("span", "", p.name), el("small", "", `${(mass(p) * 1000).toFixed(0)} g`));
      li.addEventListener("click", () => select(p.id));
      ul.appendChild(li);
    }
  }
}

// mass for display (same formulas as corvis/blueprints.py)
function mass(p) {
  const [x, y, z] = p.size;
  const v = { box: x * y * z, cylinder: Math.PI * x * x * y, sphere: 4 / 3 * Math.PI * x ** 3, cone: Math.PI * x * x * y / 3,
    torus: 2 * Math.PI ** 2 * x * y * y, capsule: Math.PI * x * x * y + 4 / 3 * Math.PI * x ** 3 }[p.shape];
  return v * (p.infill ?? 1) * state.meta.materials[p.material].density;
}
function renderStats() {
  const s = $("#stats");
  if (!state.bp) return (s.innerHTML = "");
  const total = state.bp.parts.reduce((a, p) => a + mass(p), 0);
  const power = state.bp.parts.reduce((a, p) => a + Math.max(p.power_w, 0), 0);
  const battery = state.bp.parts.reduce((a, p) => a + p.battery_wh, 0);
  s.innerHTML = `PARTS <b>${state.bp.parts.length}</b><br>MASS <b>${total < 1 ? (total * 1000).toFixed(0) + " g" : total.toFixed(2) + " kg"}</b>`
    + (power ? `<br>POWER <b>${power.toFixed(1)} W</b>` : "") + (battery ? `<br>BATTERY <b>${battery} Wh</b>` : "");
}

// ---------- tools: split, spin, move, isolate ----------
function setSplit(v) { state.split = v; $("#split").value = Math.round(v * 100); }
$("#split").addEventListener("input", (e) => {
  state.split = e.target.value / 100;
  if (state.split > 0 && gizmo.object) gizmo.detach();
});
$("#spin").addEventListener("click", (e) => { orbit.autoRotate = !orbit.autoRotate; e.target.classList.toggle("on", orbit.autoRotate); });
$("#move").addEventListener("click", (e) => {
  const on = !e.target.classList.contains("on");
  e.target.classList.toggle("on", on);
  if (on) {
    orbit.autoRotate = false; $("#spin").classList.remove("on"); setSplit(0); placeParts(true);
    if (state.selected) gizmo.attach(meshes.get(state.selected).group); else toast("Click a part to move it.");
  } else gizmo.detach();
});
$("#isolate").addEventListener("click", () => { if (!state.selected) return toast("Select a part first."); state.isolated = true; paint(); });
$("#show-all").addEventListener("click", () => { state.isolated = false; state.hidden.clear(); paint(); renderPartList(); });
$("#fit").addEventListener("click", fitView);

// ---------- tabs and phone panels ----------
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll("section.tab").forEach((s) => (s.hidden = s.dataset.tab !== name));
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#lib-toggle").addEventListener("click", () => { document.body.classList.toggle("lib-open"); document.body.classList.remove("panel-open"); });
$("#panel-toggle").addEventListener("click", () => { document.body.classList.toggle("panel-open"); document.body.classList.remove("lib-open"); });

// ---------- tests ----------
function renderSituations() {
  const box = $("#situations");
  box.innerHTML = "";
  for (const [key, s] of Object.entries(state.meta.situations)) {
    const b = el("button", state.test === key ? "on" : "", s.label);
    b.type = "button";
    b.addEventListener("click", () => {
      state.test = state.test === key ? null : key;
      if (!state.test) { state.testResult = null; clearEffects(); paint(); showHeadline(null); $("#results").innerHTML = ""; }
      renderSituations(); renderParams();
      if (state.test) runTest(true);
    });
    box.appendChild(b);
  }
}
function renderParams() {
  const box = $("#params");
  box.innerHTML = "";
  if (!state.test) return;
  const spec = state.meta.situations[state.test].params;
  const values = (state.params[state.test] ||= Object.fromEntries(Object.entries(spec).map(([k, v]) => [k, v.default])));
  for (const [k, p] of Object.entries(spec)) {
    const label = el("label");
    const shown = el("span", "", String(values[k]));
    label.append(`${p.label} `, shown);
    let input;
    if (p.options) {
      input = el("select");
      input.innerHTML = p.options.map((o) => `<option>${o}</option>`).join("");
    } else {
      input = el("input"); input.type = "range"; input.min = p.min; input.max = p.max; input.step = p.step;
    }
    input.value = values[k];
    input.addEventListener("input", () => {
      values[k] = p.options ? input.value : parseFloat(input.value);
      shown.textContent = String(values[k]);
      clearTimeout(state.testTimer);
      state.testTimer = setTimeout(() => runTest(false), 120);
    });
    label.appendChild(input);
    box.appendChild(label);
  }
}
async function runTest(animate = false) {
  if (!state.bp || !state.test) return;
  let r;
  try { r = await api(`/api/blueprints/${state.bp.id}/test`, { method: "POST", body: { situation: state.test, params: state.params[state.test] || {} } }); }
  catch (err) { return toast(err.message); }
  state.testResult = r;
  paint(); renderResults(r); showHeadline(r); renderPartForm();
  playEffect(r, animate);
}
function showHeadline(r) {
  const h = $("#headline");
  if (!r) return (h.hidden = true);
  const failing = Object.values(r.parts).some((p) => p.status === "fail") || r.tips;
  h.className = `headline ${failing ? "fail" : "ok"}`;
  h.textContent = r.headline;
  h.hidden = false;
}
function renderResults(r) {
  const box = $("#results");
  box.innerHTML = "";
  const names = Object.fromEntries(state.bp.parts.map((p) => [p.id, p.name]));
  const rows = Object.entries(r.parts).sort((a, b) => b[1].ratio - a[1].ratio);
  for (const [id, x] of rows) {
    const row = el("div", `r ${x.status}`);
    row.append(el("b", "", names[id] || id), el("em", "", `${num(x.value)} ${x.unit}`), el("small", "", `${Math.round(x.ratio * 100)}% of limit · ${x.detail}`));
    row.addEventListener("click", () => select(id));
    box.appendChild(row);
  }
  box.appendChild(el("p", "assumes", `Assumes: ${r.assumes}`));
}

// effects: drop animation, wind streaks and tipping, load arrows
function clearEffects() {
  effects.clear(); state.anim = null;
  world.position.set(0, 0, 0); world.rotation.set(0, 0, 0);
}
function playEffect(r, animate) {
  clearEffects();
  if (state.test === "drop" && animate) {
    const h = radius * 2.2; let y = h, v = 0, bounces = 0;
    state.anim = (dt) => {
      v -= 9.81 * radius * 1.5 * dt; y += v * dt;
      if (y <= 0) { y = 0; v = -v * 0.35; bounces++; if (bounces > 3 || Math.abs(v) < 0.02) { state.anim = null; } }
      world.position.y = y;
    };
  } else if (state.test === "wind") {
    const n = 90, pts = new Float32Array(n * 3), speeds = [];
    for (let i = 0; i < n; i++) {
      pts.set([center.x - radius * 2 + Math.random() * radius * 4, Math.random() * radius * 2, center.z - radius * 1.5 + Math.random() * radius * 3], i * 3);
      speeds.push(0.5 + Math.random());
    }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(pts, 3));
    effects.add(new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xbfefff, size: radius * 0.03, transparent: true, opacity: 0.7 })));
    const speed = (state.params.wind?.speed_ms ?? 10) / 10;
    let tilt = 0;
    state.anim = (dt) => {
      for (let i = 0; i < n; i++) {
        pts[i * 3] += speeds[i] * speed * radius * dt * 1.5;
        if (pts[i * 3] > center.x + radius * 2) pts[i * 3] = center.x - radius * 2;
      }
      geo.attributes.position.needsUpdate = true;
      const target = r.tips ? -Math.PI / 2.2 : -0.04 * Math.min(speed, 4);
      tilt += (target - tilt) * Math.min(1, dt * (r.tips ? 1.5 : 4));
      world.rotation.z = tilt;
    };
  } else if (state.test === "load") {
    const top = new THREE.Box3().setFromObject(assembly).max.y;
    const count = Math.min(9, 1 + Math.round((state.params.load?.load_n ?? 200) / 300));
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2, rr = count > 1 ? radius * 0.35 : 0;
      const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, -1, 0),
        new THREE.Vector3(center.x + Math.cos(a) * rr, top + radius * 0.6, center.z + Math.sin(a) * rr), radius * 0.5, 0xff8a5c, radius * 0.12, radius * 0.07);
      effects.add(arrow);
    }
  }
}

// ---------- talk to Corvis ----------
const talkLog = $("#talk-log");
function logLine(cls, text) { talkLog.hidden = false; const d = el("div", cls, text); talkLog.appendChild(d); talkLog.scrollTop = talkLog.scrollHeight; return d; }
async function ensureConversation() {
  if (state.conv) return state.conv;
  const info = await api("/api/info");
  state.conv = (await api("/api/conversations", { method: "POST", body: { mode: "project", workspace: info.default_workspace } })).id;
  return state.conv;
}
$("#talk").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#talk-input").value.trim();
  if (!text) return;
  $("#talk-input").value = "";
  logLine("me", text);
  const waiting = logLine("him working", "Corvis is working on it…");
  const context = state.bp ? `[I'm in the Blueprints hologram workshop, looking at the blueprint "${state.bp.name}" (id ${state.bp.id})`
    + (selectedPart() ? `, with the part "${selectedPart().name}" selected` : "") + ".] " : "[I'm in the Blueprints hologram workshop.] ";
  try {
    const cid = await ensureConversation();
    await api(`/api/conversations/${cid}/messages`, { method: "POST", body: { text: context + text } });
    for (let i = 0; i < 900; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      if (!(await api(`/api/conversations/${cid}/status`)).running) break;
    }
    const conv = await api(`/api/conversations/${cid}`);
    const last = [...conv.messages].reverse().find((m) => m.role === "assistant");
    waiting.className = "him"; waiting.textContent = last ? last.text : "(no reply)";
    await loadLibrary();
    const newest = state.meta.blueprints[0];
    if (!state.bp && newest) openBlueprint(newest.id);
  } catch (err) { waiting.className = "him"; waiting.textContent = err.message; }
});

// voice: the browser's speech recognition
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
$("#mic").addEventListener("click", () => {
  if (rec) return rec.stop();
  if (!SR) return toast("Voice isn't supported in this browser. Try Chrome, Edge or Safari.");
  rec = new SR(); rec.lang = navigator.language || "en-US"; rec.interimResults = true;
  rec.onresult = (e) => { $("#talk-input").value = [...e.results].map((r) => r[0].transcript).join(""); };
  rec.onend = () => { $("#mic").classList.remove("on"); rec = null; if ($("#talk-input").value.trim()) $("#talk").requestSubmit(); };
  rec.onerror = (e) => toast(e.error === "not-allowed" ? "Microphone permission was denied." : `Voice error: ${e.error}`);
  rec.start(); $("#mic").classList.add("on");
});

// ---------- start ----------
(async () => {
  try { await loadLibrary(); } catch (err) { return toast(err.message, 8000); }
  rebuild(false);
  const want = new URLSearchParams(location.search).get("id");
  const low = (want || "").toLowerCase();
  const all = state.meta.blueprints;
  const target = want && (all.find((b) => b.id === want || b.name.toLowerCase() === low)
    || all.find((b) => b.name.toLowerCase().includes(low)));
  if (target) openBlueprint(target.id);
})();
