/* The knowledge graph drawn as a living brain (Knowledge → Graph).
   Each knowledge file is a neuron in the brain region for its category; relationships are synapses
   with signals travelling along them. A timeline replays how the brain grew, file by file, from the
   first thing Corvis learned to today, and new knowledge sprouts live while a session runs.
   Used by knowledge.js: CorvisBrainView.mount(box, graph, { colorFor, catName, onOpen, load }). */
(function () {
  "use strict";

  const TAU = Math.PI * 2;
  const DAY = 864e5;
  const reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- small helpers ----------
  function rng(seed) {
    return function () {
      seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hash(s) {
    let x = 2166136261;
    for (const c of String(s)) { x ^= c.charCodeAt(0); x = Math.imul(x, 16777619); }
    return x >>> 0;
  }
  function dayOf(date) {
    const m = String(date || "").match(/^(\d{4})-(\d\d)-(\d\d)/);
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) / DAY : null;
  }
  function today() { const d = new Date(); return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY; }
  function fmtDay(day) {
    return new Date(day * DAY).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ease = (p) => 1 - Math.pow(1 - p, 3);
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  // ---------- the brain's anatomy (side view, front to the left; coordinates 0..1) ----------
  const REGIONS = {
    Research: { x: 0.15, y: 0.40, name: "Prefrontal cortex" },
    Business: { x: 0.27, y: 0.23, name: "Frontal lobe" },
    Projects: { x: 0.29, y: 0.45, name: "Frontal lobe" },
    Engineering: { x: 0.40, y: 0.16, name: "Premotor cortex" },
    Robotics: { x: 0.51, y: 0.25, name: "Motor cortex" },
    Programming: { x: 0.64, y: 0.19, name: "Parietal lobe" },
    Electronics: { x: 0.67, y: 0.39, name: "Parietal lobe" },
    ArtificialIntelligence: { x: 0.84, y: 0.37, name: "Occipital lobe" },
    Personal: { x: 0.46, y: 0.61, name: "Temporal lobe · memory" },
  };
  const SPARE = [{ x: 0.39, y: 0.40 }, { x: 0.56, y: 0.47 }, { x: 0.76, y: 0.23 }, { x: 0.22, y: 0.57 }, { x: 0.59, y: 0.62 }];
  function regionFor(cat) {
    return REGIONS[cat] || { ...SPARE[hash(cat) % SPARE.length], name: "Association cortex" };
  }

  const OUTLINE = (() => {   // the cerebrum: a dome on top, the temporal lobe bulging below the front half
    const pts = [];
    for (let i = 0; i < 260; i++) {
      const t = (i / 260) * TAU, c = Math.cos(t), s = Math.sin(t);
      const ry = s < 0 ? 0.36 : 0.2 + 0.13 * Math.exp(-(((c + 0.1) / 0.38) ** 2));
      const bump = 1 + 0.016 * Math.sin(t * 13) + 0.01 * Math.sin(t * 29 + 1);
      pts.push([0.5 + 0.46 * c * bump, 0.42 + ry * s * bump]);
    }
    return pts;
  })();
  function inside(x, y) {
    let inn = false;
    for (let i = 0, j = OUTLINE.length - 1; i < OUTLINE.length; j = i++) {
      const [xi, yi] = OUTLINE[i], [xj, yj] = OUTLINE[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inn = !inn;
    }
    return inn;
  }
  const SULCI = (() => {   // folds: seeded random walks that stay inside the cerebrum
    const r = rng(7), out = [];
    while (out.length < 78) {
      let x = 0.08 + r() * 0.84, y = 0.08 + r() * 0.62, a = r() * TAU;
      if (!inside(x, y)) continue;
      const line = [[x, y]];
      for (let k = 0; k < 6 + Math.floor(r() * 7); k++) {
        a += (r() - 0.5) * 2.1;
        x += Math.cos(a) * 0.02; y += Math.sin(a) * 0.018;
        if (!inside(x, y)) break;
        line.push([x, y]);
      }
      if (line.length > 3) out.push(line);
    }
    return out;
  })();
  const FISSURES = [
    [[0.53, 0.07], [0.52, 0.12], [0.535, 0.17], [0.505, 0.23], [0.515, 0.29], [0.485, 0.35], [0.47, 0.42]],   // central sulcus
    [[0.27, 0.57], [0.38, 0.52], [0.5, 0.49], [0.6, 0.47], [0.66, 0.44]],   // lateral (Sylvian) fissure
    [[0.86, 0.17], [0.84, 0.27], [0.86, 0.35]],                               // parieto-occipital
  ];
  const CEREBELLUM_FOLDS = Array.from({ length: 7 }, (_, i) => i);

  function smooth(ctx, pts) {
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2;
      ctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, my);
    }
    const last = pts[pts.length - 1];
    ctx.lineTo(last[0], last[1]);
  }
  const CEREBRUM = (() => { const p = new Path2D(); p.moveTo(...OUTLINE[0]); OUTLINE.forEach((q) => p.lineTo(...q)); p.closePath(); return p; })();

  // ---------- placing neurons ----------
  function layout(nodes, edges, keep) {
    const byCat = {};
    nodes.forEach((n) => (byCat[n.category] = byCat[n.category] || []).push(n));
    for (const [cat, list] of Object.entries(byCat)) {
      const R = regionFor(cat);
      list.sort((a, b) => (a.created || "").localeCompare(b.created || "") || a.id.localeCompare(b.id));
      list.forEach((n, i) => {
        n.rx = R.x; n.ry = R.y;
        if (keep[n.id]) { n.x = keep[n.id].x; n.y = keep[n.id].y; n.fixed = true; return; }
        const r = rng(hash(n.id));
        const a = i * 2.39996 + r() * 0.6, d = 0.026 * Math.sqrt(i + 0.6) + r() * 0.006;
        n.x = R.x + Math.cos(a) * d; n.y = R.y + Math.sin(a) * d * 0.85;
      });
    }
    const loose = nodes.filter((n) => !n.fixed);
    const rounds = nodes.length > 400 ? 30 : 110;
    for (let it = 0; it < rounds && loose.length; it++) {
      for (const a of loose) {
        for (const b of nodes) {
          if (a === b) continue;
          const dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
          if (d2 < 0.0009 && d2 > 1e-9) { const d = Math.sqrt(d2), f = ((0.03 - d) * 0.3) / d; a.x += dx * f; a.y += dy * f; }
        }
        a.x += (a.rx - a.x) * 0.012; a.y += (a.ry - a.y) * 0.012;
        if (!inside(a.x, a.y)) { a.x += (a.rx - a.x) * 0.25; a.y += (a.ry - a.y) * 0.25; }
      }
    }
    for (const e of edges) {   // a gentle arc for each synapse, bowing away from the brain's centre
      const mx = (e.a.x + e.b.x) / 2, my = (e.a.y + e.b.y) / 2;
      const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, len = Math.hypot(dx, dy) || 1;
      let px = -dy / len, py = dx / len;
      if ((mx - 0.5) * px + (my - 0.4) * py < 0) { px = -px; py = -py; }
      e.cx = mx + px * len * 0.18; e.cy = my + py * len * 0.18;
    }
  }
  function onCurve(e, t) {
    const u = 1 - t;
    return [u * u * e.a.x + 2 * u * t * e.cx + t * t * e.b.x, u * u * e.a.y + 2 * u * t * e.cy + t * t * e.b.y];
  }

  // ---------- the view ----------
  function mount(box, graph, opts) {
    const { colorFor, catName = (c) => c, onOpen = () => {}, load } = opts;
    box.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "brain-view hub-card";
    wrap.innerHTML = `
      <div class="brain-stage"><canvas aria-label="Corvis's knowledge, drawn as a brain"></canvas>
        <p class="brain-empty" hidden>An empty mind, ready to learn. Start a learning session and watch the first neurons appear.</p></div>
      <div class="brain-time">
        <button class="btn ghost small" type="button" data-play>▶ Replay growth</button>
        <input type="range" min="0" max="1000" value="1000" aria-label="Brain as of date">
        <span class="brain-when"></span>
      </div>
      <div class="brain-spark"><svg viewBox="0 0 400 44" preserveAspectRatio="none" aria-hidden="true"><path class="area"/><path class="line"/><line class="mark" y1="0" y2="44"/></svg></div>
      <p class="brain-stats"></p>
      <div class="k-legend"></div>
      <p class="hint">Each glowing neuron is a knowledge file, in the brain region for its subject; brighter and bigger means healthier. Lines are connections between topics. Drag to move, scroll to zoom, double-click to reset, click a neuron to read it.</p>`;
    box.appendChild(wrap);
    const cv = wrap.querySelector("canvas"), ctx = cv.getContext("2d");
    const slider = wrap.querySelector("input"), playBtn = wrap.querySelector("[data-play]");
    const svg = wrap.querySelector("svg");

    let nodes = [], edges = [], byId = {}, cats = [];
    let t0 = today(), t1 = today();
    let cursor = Infinity, playing = null, hover = null;
    let view = { x: 0, y: 0, k: 1 }, drag = null;

    function ingest(g, live) {
      const keep = {};
      nodes.forEach((n) => { keep[n.id] = { x: n.x, y: n.y }; });
      const old = byId;
      const now = performance.now();
      nodes = g.nodes.map((n) => ({ ...n, day: dayOf(n.created) ?? today(), phase: (hash(n.id) % 1000) / 160,
        liveBorn: old[n.id] ? old[n.id].liveBorn : (live ? now : 0) }));
      byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
      edges = g.edges.filter((e) => byId[e.from] && byId[e.to]).map((e, i) => ({
        a: byId[e.from], b: byId[e.to], speed: 0.12 + ((hash(e.from + e.to) % 100) / 100) * 0.28, phase: (i * 0.37) % 1 }));
      cats = [...new Set(nodes.map((n) => n.category))].sort();
      layout(nodes, edges, keep);
      // birth order: by day, and within a day one after another, so a replay shows them sprouting in turn
      const perDay = {};
      nodes.forEach((n) => (perDay[n.day] = perDay[n.day] || []).push(n));
      for (const list of Object.values(perDay)) {
        list.sort((a, b) => a.id.localeCompare(b.id));
        list.forEach((n, k) => { n.born = n.day + (k / list.length) * 0.9; });
      }
      t0 = nodes.length ? Math.min(...nodes.map((n) => n.day)) : today();
      t1 = Math.max(today(), ...nodes.map((n) => n.day + 1));
      wrap.querySelector(".brain-empty").hidden = nodes.length > 0;
      wrap.querySelector(".k-legend").innerHTML = cats.map((c) =>
        `<span><i style="background:${colorFor(c, cats)}"></i>${catName(c)} <small>${regionFor(c).name}</small></span>`).join("");
      spark();
      stats();
    }

    // how far into existence a neuron is at the current moment (0 = not yet, 1 = fully grown)
    function grown(n, now) {
      const span = Math.max(1, t1 - t0);
      const tl = cursor === Infinity ? 1 : clamp((cursor - n.born) / Math.max(0.35, span * 0.035), 0, 1);
      const lv = n.liveBorn ? clamp((now - n.liveBorn) / 1400, 0, 1) : 1;
      return Math.min(tl, lv);
    }
    function asOf() { return cursor === Infinity ? t1 : cursor; }
    function stats() {
      const at = asOf();
      const shown = nodes.filter((n) => n.born <= at);
      const ids = new Set(shown.map((n) => n.id));
      const syn = edges.filter((e) => ids.has(e.a.id) && ids.has(e.b.id)).length;
      const from = cursor === Infinity ? today() - 6 : at - 7;   // "now" means today and the 6 days before
      const week = nodes.filter((n) => n.born <= at && n.born >= from).length;
      const regions = new Set(shown.map((n) => regionFor(n.category).name)).size;
      wrap.querySelector(".brain-when").textContent = cursor === Infinity ? "Now" : fmtDay(Math.floor(Math.min(at, t1 - 1)));
      wrap.querySelector(".brain-stats").textContent = `${shown.length} neuron${shown.length === 1 ? "" : "s"} · ${syn} connection${syn === 1 ? "" : "s"} · `
        + `${regions} brain region${regions === 1 ? "" : "s"} active` + (week ? ` · +${week} in the ${cursor === Infinity ? "last 7 days" : "7 days before this point"}` : "");
      const x = ((at - t0) / Math.max(1, t1 - t0)) * 400;
      const mark = svg.querySelector(".mark");
      mark.setAttribute("x1", x); mark.setAttribute("x2", x);
    }
    function spark() {   // cumulative knowledge over time
      const span = Math.max(1, t1 - t0), total = Math.max(1, nodes.length);
      const days = [...nodes].map((n) => n.day).sort((a, b) => a - b);
      let d = "M0 44", count = 0;
      for (const day of days) {
        count++;
        d += ` L${(((day - t0) / span) * 400).toFixed(1)} ${(44 - (count / total) * 40).toFixed(1)}`;
      }
      d += ` L400 ${(44 - (count / total) * 40).toFixed(1)}`;
      svg.querySelector(".line").setAttribute("d", d);
      svg.querySelector(".area").setAttribute("d", d + " L400 44 Z");
    }

    // ---------- drawing ----------
    function frame(now) {
      if (!document.body.contains(cv)) { stopLive(); return; }
      if (!document.hidden) draw(now);
      if (playing) step(now);
      requestAnimationFrame(frame);
    }
    function draw(now) {
      const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, hgt = cv.clientHeight;
      if (!w || !hgt) return;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(hgt * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(hgt * dpr); }
      const light = document.documentElement.dataset.theme === "light";
      const accent = css("--accent"), text = css("--text"), muted = css("--muted");
      const base = Math.min(w / 1.04, hgt / 1.0), S = base * view.k;
      const ox = (w - base) / 2 + view.x, oy = (hgt - base * 0.98) / 2 + view.y;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, hgt);
      ctx.setTransform(dpr * S, 0, 0, dpr * S, dpr * ox, dpr * oy);
      const px = 1 / S;
      const z = clamp(base / 620, 0.5, 1.15);   // neurons shrink with the brain on small screens
      const breathe = reduceMotion ? 0 : Math.sin(now / 2600) * 0.5 + 0.5;

      // brainstem and cerebellum, behind the cerebrum
      ctx.lineJoin = "round"; ctx.lineCap = "round";
      ctx.fillStyle = light ? "rgba(77,88,207,.05)" : "rgba(140,150,255,.05)";
      ctx.strokeStyle = accent; ctx.globalAlpha = 0.45; ctx.lineWidth = 1.4 * px;
      ctx.beginPath();
      ctx.moveTo(0.585, 0.6); ctx.bezierCurveTo(0.6, 0.75, 0.6, 0.86, 0.615, 0.97);
      ctx.lineTo(0.675, 0.97); ctx.bezierCurveTo(0.67, 0.86, 0.675, 0.74, 0.67, 0.62);
      ctx.fill(); ctx.stroke();
      ctx.save();
      ctx.translate(0.765, 0.685); ctx.rotate(-0.12);
      ctx.beginPath(); ctx.ellipse(0, 0, 0.155, 0.088, 0, 0, TAU); ctx.fill(); ctx.stroke();
      ctx.clip();
      ctx.globalAlpha = 0.18;
      for (const i of CEREBELLUM_FOLDS) {
        ctx.beginPath(); ctx.ellipse(0, 0.09, 0.17 - i * 0.004, 0.155 - i * 0.022, 0, Math.PI * 1.08, Math.PI * 1.92); ctx.stroke();
      }
      ctx.restore();

      // the cerebrum with its folds
      ctx.globalAlpha = 1;
      const g = ctx.createRadialGradient(0.45, 0.35, 0.05, 0.5, 0.42, 0.6);
      g.addColorStop(0, light ? `rgba(77,88,207,${0.1 + breathe * 0.03})` : `rgba(140,150,255,${0.13 + breathe * 0.04})`);
      g.addColorStop(1, light ? "rgba(77,88,207,.03)" : "rgba(79,195,180,.04)");
      ctx.fillStyle = css("--surface"); ctx.fill(CEREBRUM);
      ctx.fillStyle = g; ctx.fill(CEREBRUM);
      ctx.globalAlpha = 0.6; ctx.lineWidth = 1.6 * px; ctx.strokeStyle = accent; ctx.stroke(CEREBRUM);
      ctx.save(); ctx.clip(CEREBRUM);
      ctx.globalAlpha = light ? 0.16 : 0.13; ctx.lineWidth = 1.2 * px;
      for (const s of SULCI) { ctx.beginPath(); smooth(ctx, s); ctx.stroke(); }
      ctx.globalAlpha = light ? 0.24 : 0.2; ctx.lineWidth = 1.8 * px;
      for (const f of FISSURES) { ctx.beginPath(); smooth(ctx, f); ctx.stroke(); }
      ctx.restore();

      // region names for the parts of the brain in use (drawn in screen pixels so they stay crisp)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalAlpha = 0.6; ctx.fillStyle = muted; ctx.textAlign = "center";
      ctx.font = `600 ${base < 480 ? 8.5 : 10}px ${css("--font-text")}`;
      const seen = new Set(base < 480 ? cats.map((c) => regionFor(c).name) : []);   // too cramped on a phone: the legend names them
      for (const c of cats) {
        const R = regionFor(c);
        if (seen.has(R.name) || !nodes.some((n) => n.category === c && grown(n, now) > 0)) continue;
        seen.add(R.name);
        ctx.fillText(R.name.toUpperCase(), ox + R.x * S, oy + (R.y - 0.085) * S);
      }
      ctx.setTransform(dpr * S, 0, 0, dpr * S, dpr * ox, dpr * oy);

      // synapses and the signals running along them
      const near = hover ? new Set([hover, ...edges.filter((e) => e.a === hover || e.b === hover).flatMap((e) => [e.a, e.b])]) : null;
      ctx.globalCompositeOperation = light ? "source-over" : "lighter";
      for (const e of edges) {
        const p = Math.min(grown(e.a, now), grown(e.b, now));
        if (p <= 0) continue;
        const on = near && near.has(e.a) && near.has(e.b);
        ctx.globalAlpha = (near && !on ? 0.06 : on ? 0.8 : 0.28) * p;
        ctx.strokeStyle = on ? accent : colorFor(e.a.category, cats);
        ctx.lineWidth = (on ? 1.8 : 1.1) * px;
        ctx.beginPath(); ctx.moveTo(e.a.x, e.a.y);
        if (p < 1) {   // a new connection grows from one neuron to the other
          const steps = 16; for (let i = 1; i <= steps; i++) { const q = onCurve(e, (i / steps) * ease(p)); ctx.lineTo(q[0], q[1]); }
        } else ctx.quadraticCurveTo(e.cx, e.cy, e.b.x, e.b.y);
        ctx.stroke();
        if (!reduceMotion && p >= 1 && (!near || on)) {
          const t = ((now / 1000) * e.speed + e.phase) % 1;
          const [sx, sy] = onCurve(e, t);
          ctx.globalAlpha = 0.9 * Math.sin(t * Math.PI);
          ctx.fillStyle = light ? accent : "#ffffff";
          ctx.beginPath(); ctx.arc(sx, sy, 1.7 * px, 0, TAU); ctx.fill();
        }
      }

      // neurons
      for (const n of nodes) {
        const p = grown(n, now);
        if (p <= 0) continue;
        const col = colorFor(n.category, cats);
        const vital = 0.45 + 0.55 * (n.health / 100);
        const twinkle = reduceMotion ? 1 : 0.82 + 0.18 * Math.sin(now / 650 + n.phase);
        const dim = near && !near.has(n) ? 0.18 : 1;
        const r = (3 + n.health / 22) * z * px * ease(p) * (n === hover ? 1.35 : 1);
        ctx.globalAlpha = 0.22 * vital * twinkle * dim;
        ctx.fillStyle = col;
        ctx.beginPath(); ctx.arc(n.x, n.y, r * 2.7, 0, TAU); ctx.fill();
        ctx.globalAlpha = vital * dim;
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, TAU); ctx.fill();
        ctx.globalAlpha = 0.85 * dim * twinkle;
        ctx.fillStyle = light ? "#ffffff" : "#f4f6ff";
        ctx.beginPath(); ctx.arc(n.x, n.y, r * 0.38, 0, TAU); ctx.fill();
        if (p < 1) {   // birth flash
          ctx.globalAlpha = (1 - p) * 0.9;
          ctx.strokeStyle = col; ctx.lineWidth = 1.5 * px;
          ctx.beginPath(); ctx.arc(n.x, n.y, r + (1 - (1 - p)) * 22 * px, 0, TAU); ctx.stroke();
        }
      }
      ctx.globalCompositeOperation = "source-over";

      // names: the hovered neuron and its neighbours, or every neuron when zoomed in
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalAlpha = 1; ctx.fillStyle = text; ctx.font = `11.5px ${css("--font-text")}`;
      const labelled = near ? [...near] : view.k >= 1.6 ? nodes : [];
      for (const n of labelled) {
        if (grown(n, now) < 1) continue;
        const r = (3 + n.health / 22) * z;
        ctx.fillText(n.title.length > 28 ? n.title.slice(0, 27) + "…" : n.title, ox + n.x * S, oy + n.y * S + r + 14);
      }

      if (hover) tooltip(hover, S, ox, oy, w, light);
    }
    function tooltip(n, S, ox, oy, w, light) {
      const dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const lines = [n.title, `${catName(n.category)} · ${regionFor(n.category).name}`,
        `health ${n.health}% · confidence ${n.confidence}%`, `learned ${n.created || "?"} · verified ${n.last_verified || "?"}`];
      ctx.font = `12px ${css("--font-text")}`;
      const tw = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 20;
      let x = ox + n.x * S + 14, y = oy + n.y * S - 20;
      if (x + tw > w - 6) x = ox + n.x * S - tw - 14;
      ctx.globalAlpha = 0.95; ctx.fillStyle = css("--surface"); ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect(x, y, tw, 80, 8); ctx.fill(); ctx.stroke();
      ctx.globalAlpha = 1; ctx.textAlign = "left";
      lines.forEach((l, i) => {
        ctx.fillStyle = i ? css("--muted") : css("--text");
        ctx.font = `${i ? 400 : 600} 12px ${css("--font-text")}`;
        ctx.fillText(l, x + 10, y + 20 + i * 17);
      });
      ctx.textAlign = "center";
    }

    // ---------- the timeline ----------
    function setCursor(v) {
      cursor = v >= t1 ? Infinity : v;
      slider.value = cursor === Infinity ? 1000 : Math.round(((v - t0) / Math.max(1e-6, t1 - t0)) * 1000);
      stats();
    }
    slider.addEventListener("input", () => {
      playing = null; playBtn.textContent = "▶ Replay growth";
      const v = t0 + (slider.value / 1000) * (t1 - t0);
      setCursor(slider.value >= 1000 ? Infinity : v);
    });
    playBtn.addEventListener("click", () => {
      if (playing) { playing = null; playBtn.textContent = "▶ Replay growth"; return; }
      playing = { start: performance.now(), from: t0 - 0.3, dur: clamp(2500 + nodes.length * 220, 4000, 14000) };
      playBtn.textContent = "❚❚ Pause";
    });
    function step(now) {
      const p = clamp((now - playing.start) / playing.dur, 0, 1);
      setCursor(playing.from + (t1 + 0.2 - playing.from) * p);
      if (p >= 1) { playing = null; playBtn.textContent = "▶ Replay growth"; setCursor(Infinity); }
    }

    // ---------- pointer ----------
    function at(ev) {
      const r = cv.getBoundingClientRect(), w = cv.clientWidth, hgt = cv.clientHeight;
      const base = Math.min(w / 1.04, hgt / 1.0), S = base * view.k;
      const ox = (w - base) / 2 + view.x, oy = (hgt - base * 0.98) / 2 + view.y;
      const x = (ev.clientX - r.left - ox) / S, y = (ev.clientY - r.top - oy) / S, now = performance.now();
      let best = null, bd = (14 / S) ** 2;
      for (const n of nodes) {
        if (grown(n, now) <= 0) continue;
        const d = (n.x - x) ** 2 + (n.y - y) ** 2;
        if (d < bd) { bd = d; best = n; }
      }
      return best;
    }
    cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener("pointermove", (e) => {
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        view.x = drag.vx + dx; view.y = drag.vy + dy; return;
      }
      hover = at(e);
      cv.style.cursor = hover ? "pointer" : "grab";
    });
    cv.addEventListener("pointerleave", () => { hover = null; });
    cv.addEventListener("pointerup", (e) => {
      const moved = drag && drag.moved; drag = null;
      if (!moved) { const n = at(e); if (n) onOpen(n.id); }
    });
    cv.addEventListener("dblclick", () => { view = { x: 0, y: 0, k: 1 }; });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      const w = cv.clientWidth, hgt = cv.clientHeight, base = Math.min(w / 1.04, hgt / 1.0);
      const k = clamp(view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12), 0.6, 5);
      const ox = (w - base) / 2 + view.x, oy = (hgt - base * 0.98) / 2 + view.y;
      view.x += (mx - ox) * (1 - k / view.k); view.y += (my - oy) * (1 - k / view.k); view.k = k;
    }, { passive: false });

    // ---------- live growth while Corvis learns ----------
    let liveTimer = null;
    function stopLive() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }
    if (load) {
      liveTimer = setInterval(async () => {
        if (!document.body.contains(cv)) { stopLive(); return; }
        if (document.hidden) return;
        try {
          const g = await load();
          const ids = (gr) => gr.nodes.map((n) => n.id).sort().join() + "|" + gr.edges.length + "|" + gr.nodes.map((n) => n.health).join();
          if (ids(g) !== ids({ nodes, edges: edges.map(() => 0) })) ingest(g, true);
        } catch (_) { /* try again next time */ }
      }, 8000);
    }

    ingest(graph, false);
    setCursor(Infinity);
    requestAnimationFrame(frame);
  }

  window.CorvisBrainView = { mount, regionFor, inside };
})();
