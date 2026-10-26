/* The knowledge base drawn as a living, holographic brain (Knowledge → Graph).
   The brain is a slowly turning cloud of glowing particles and filaments. Each subject is a cluster
   on it, in the region that suits it (Robotics in the motor cortex, AI in the occipital lobe...),
   growing brighter as Corvis learns more. Click a cluster and it opens up into its knowledge files;
   click a file to read it. A timeline replays the brain filling in from the first thing Corvis
   learned to today, and new knowledge sprouts live while a session runs.
   Used by knowledge.js: CorvisBrainView.mount(box, graph, { catName, onOpen, load }). */
(function () {
  "use strict";

  const TAU = Math.PI * 2;
  const DAY = 864e5;
  const reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const HUES = [228, 172, 32, 280, 350, 200, 120, 55, 300, 10];
  const BASE = [[176, 118, 255], [132, 128, 255], [126, 176, 255]];   // the brain itself: violet at the front, blue behind

  // ---------- helpers ----------
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
  function hsl(h, s, l) {   // -> [r, g, b]
    s /= 100; l /= 100;
    const k = (n) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
    const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
  }
  const mix = (a, b, k) => [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * k));
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // ---------- anatomy (x: front -1 → back 1, y: up, z: towards you) ----------
  const REGIONS = {
    Research: { p: [-0.86, 0.08], name: "Prefrontal cortex" },
    Business: { p: [-0.52, 0.42], name: "Frontal lobe" },
    Projects: { p: [-0.5, -0.02], name: "Frontal lobe" },
    Engineering: { p: [-0.2, 0.62], name: "Premotor cortex" },
    Robotics: { p: [0.06, 0.52], name: "Motor cortex" },
    Programming: { p: [0.42, 0.5], name: "Parietal lobe" },
    Electronics: { p: [0.42, 0.14], name: "Parietal lobe" },
    ArtificialIntelligence: { p: [0.86, 0.12], name: "Occipital lobe" },
    Personal: { p: [-0.12, -0.3], name: "Temporal lobe · memory" },
  };
  const SPARE = [[-0.25, 0.22], [0.15, 0.12], [0.66, 0.4], [-0.68, -0.18], [0.28, -0.16]];
  function regionFor(cat) {
    const r = REGIONS[cat] || { p: SPARE[hash(cat) % SPARE.length], name: "Association cortex" };
    const [x, y] = r.p;
    const z = 0.3 + 0.42 * Math.sqrt(Math.max(0, 1 - x * x - ((y - 0.12) / 0.75) ** 2));   // on the near hemisphere's surface
    return { x, y, z, name: r.name };
  }

  // how deep inside the brain a point is: < 1 inside; which part it belongs to
  function shape(x, y, z) {
    const az = Math.abs(z);
    const ry = y >= 0.12 ? 0.66 : 0.42 + 0.22 * Math.exp(-(((x + 0.12) / 0.42) ** 2));
    const cere = (x / 1.0) ** 2 + ((y - 0.12) / ry) ** 2 + ((az - 0.4) / 0.36) ** 2;   // two hemispheres
    const cbl = ((x - 0.6) / 0.32) ** 2 + ((y + 0.42) / 0.2) ** 2 + (z / 0.52) ** 2;   // cerebellum
    const tilt = x - 0.3 + (y + 0.35) * 0.18;
    const stem = y < -0.28 && y > -0.98 ? (tilt / 0.1) ** 2 + (z / 0.1) ** 2 : 9;
    if (az < 0.05 && y > -0.1) return { v: 9 };                                          // the fissure between hemispheres
    if (cere <= cbl && cere <= stem) return { v: cere, part: "cerebrum" };
    if (cbl <= stem) return { v: cbl, part: "cerebellum" };
    return { v: stem, part: "stem" };
  }
  function folds(x, y, z) {   // ridged noise: the gyri and sulci
    return Math.abs(Math.sin(7.3 * x + 2.1 * z + Math.sin(5.1 * y)) * Math.sin(6.2 * y - 1.7 * x + Math.cos(4.3 * z))
      + 0.45 * Math.sin(12.5 * z - 4.4 * y + 3.1 * x));
  }
  function buildParticles(count) {
    const r = rng(11), pts = [];
    let guard = 0;
    while (pts.length < count && guard++ < count * 60) {
      const x = r() * 2.1 - 1.05, y = r() * 2 - 1, z = r() * 1.6 - 0.8;
      const s = shape(x, y, z);
      if (s.v > 1) continue;
      const shell = s.part === "stem" ? s.v > 0.35 : s.v > 0.74;
      const f = folds(x, y, z);
      const vein = shell && f < 0.2;
      if (!(vein || (shell && r() < 0.6) || r() < 0.05)) continue;
      pts.push({ x, y, z, vein, part: s.part, size: vein ? 1.9 : 1.2 + r() * 0.8, tw: r() * TAU, a: 0 });
    }
    return pts;
  }
  function buildMesh(pts) {   // fine filaments between nearby fold particles: the network look
    const veins = pts.filter((p) => p.vein).slice(0, 1400), lines = [];
    for (const p of veins) {
      let best = [];
      for (const q of veins) {
        if (q === p) continue;
        const d = (p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2;
        if (d < 0.012) { best.push([d, q]); }
      }
      best.sort((a, b) => a[0] - b[0]);
      for (const [, q] of best.slice(0, 2)) if (p.x < q.x || (p.x === q.x && p.y < q.y)) lines.push([p, q]);
    }
    return lines;
  }
  function buildFilaments(pts, n) {   // threads of light reaching out from the brain
    const r = rng(23), shell = pts.filter((p) => p.part === "cerebrum" && p.vein), out = [];
    for (let i = 0; i < n && shell.length; i++) {
      const p = shell[Math.floor(r() * shell.length)];
      const len = Math.hypot(p.x, p.y - 0.1, p.z) || 1;
      const nx = p.x / len, ny = (p.y - 0.1) / len, nz = p.z / len;
      const reach = 0.3 + r() * 0.4, bend = (r() - 0.5) * 0.45;
      out.push({ a: p, c: [p.x + nx * reach * 0.5 + bend * nz, p.y + ny * reach * 0.5 + bend * 0.4, p.z + nz * reach * 0.5 - bend * nx],
        b: [p.x + nx * reach, p.y + ny * reach + (r() - 0.5) * 0.4, p.z + nz * reach], speed: 0.05 + r() * 0.12, phase: r() });
    }
    return out;
  }

  // ---------- the view ----------
  function mount(box, graph, opts) {
    const { catName = (c) => c, onOpen = () => {}, load } = opts;
    box.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "brain-view hub-card";
    wrap.innerHTML = `
      <div class="brain-stage"><canvas aria-label="Corvis's knowledge, drawn as a brain"></canvas>
        <div class="brain-focus" hidden><button type="button" class="brain-back">← Whole brain</button><div><b></b><small></small></div></div>
        <p class="brain-empty" hidden>An empty mind, ready to learn. Start a learning session and watch it light up.</p></div>
      <div class="brain-time">
        <button class="btn ghost small" type="button" data-play>▶ Replay growth</button>
        <input type="range" min="0" max="1000" value="1000" aria-label="Brain as of date">
        <span class="brain-when"></span>
      </div>
      <div class="brain-spark"><svg viewBox="0 0 400 44" preserveAspectRatio="none" aria-hidden="true"><path class="area"/><path class="line"/><line class="mark" y1="0" y2="44"/></svg></div>
      <p class="brain-stats"></p>
      <div class="k-legend"></div>
      <p class="hint">Each glowing cluster is a subject Corvis knows about; click one to open it up into its knowledge files, then click a file to read it. Drag to turn the brain, scroll to zoom, double-click to reset.</p>`;
    box.appendChild(wrap);
    const cv = wrap.querySelector("canvas"), ctx = cv.getContext("2d");
    const glow = document.createElement("canvas"), gctx = glow.getContext("2d");
    const slider = wrap.querySelector("input"), playBtn = wrap.querySelector("[data-play]");
    const svg = wrap.querySelector("svg"), focusBar = wrap.querySelector(".brain-focus");

    const small = (cv.clientWidth || box.clientWidth) < 600;
    const particles = buildParticles(small ? 2400 : 4200);
    const mesh = buildMesh(particles);
    const filaments = buildFilaments(particles, 44);

    let nodes = [], edges = [], byId = {}, cats = [], clusters = {}, catLinks = [];
    let t0 = today(), t1 = today();
    let cursor = Infinity, playing = null, hover = null;
    let cam = { yaw: -0.28, pitch: 0.1, k: 1, userAt: 0 }, drag = null;
    let focus = null;        // {cat, start, closing}
    let litKey = "", litOrder = [];

    const colorOf = (cat) => hsl(HUES[Math.max(0, cats.indexOf(cat)) % HUES.length], 78, 68);

    function ingest(g, live) {
      const old = byId, now = performance.now();
      nodes = g.nodes.map((n) => ({ ...n, day: dayOf(n.created) ?? today(), phase: (hash(n.id) % 1000) / 160,
        liveBorn: old[n.id] ? old[n.id].liveBorn : (live ? now : 0) }));
      byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
      edges = g.edges.filter((e) => byId[e.from] && byId[e.to]).map((e) => ({ a: byId[e.from], b: byId[e.to] }));
      cats = [...new Set(nodes.map((n) => n.category))].sort();
      clusters = {};
      const used = new Set();
      particles.forEach((p) => { p.file = false; });
      for (const c of cats) {
        const R = regionFor(c), members = nodes.filter((n) => n.category === c).sort((a, b) => a.day - b.day || a.id.localeCompare(b.id));
        clusters[c] = { cat: c, ...R, members, color: colorOf(c) };
        clusters[c].light = mix(clusters[c].color, [255, 255, 255], 0.55);
        // each file becomes one of the brain's own particles near its region, so knowledge is part of
        // the brain rather than drawn on top of it
        const near = particles.map((p, i) => [Math.hypot(p.x - R.x, p.y - R.y, (p.z - R.z) * 1.4), i])
          .filter(([, i]) => particles[i].part === "cerebrum" && particles[i].z > 0.1 && !used.has(i))
          .sort((a, b) => a[0] - b[0]);
        members.forEach((n, i) => {
          const pi = near[Math.min(i * 2 + (hash(n.id) % 2), near.length - 1)][1];
          used.add(pi);
          const p = particles[pi];
          n.x = p.x; n.y = p.y; n.z = p.z; n.pi = pi; p.file = true;
        });
      }
      const pairs = {};
      for (const e of edges) {
        if (e.a.category === e.b.category) continue;
        const k = [e.a.category, e.b.category].sort().join("|");
        pairs[k] = pairs[k] || { a: e.a.category, b: e.b.category, n: 0, edges: [] };
        pairs[k].n++; pairs[k].edges.push(e);
      }
      catLinks = Object.values(pairs).map((l, i) => ({ ...l, speed: 0.1 + (hash(l.a + l.b) % 100) / 400, phase: (i * 0.37) % 1 }));
      // birth order: by day, and within a day one after another
      const perDay = {};
      nodes.forEach((n) => (perDay[n.day] = perDay[n.day] || []).push(n));
      for (const list of Object.values(perDay)) {
        list.sort((a, b) => a.id.localeCompare(b.id));
        list.forEach((n, k) => { n.born = n.day + (k / list.length) * 0.9; });
      }
      t0 = nodes.length ? Math.min(...nodes.map((n) => n.day)) : today();
      t1 = Math.max(today(), ...nodes.map((n) => n.day + 1));
      litKey = "";
      wrap.querySelector(".brain-empty").hidden = nodes.length > 0;
      wrap.querySelector(".k-legend").innerHTML = cats.map((c) =>
        `<span><i style="background:${rgba(colorOf(c), 1)}"></i>${esc(catName(c))} <small>${esc(regionFor(c).name)}</small></span>`).join("");
      if (focus && !clusters[focus.cat]) closeFocus();
      spark();
      stats();
    }

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
      const from = cursor === Infinity ? today() - 6 : at - 7;
      const week = nodes.filter((n) => n.born <= at && n.born >= from).length;
      const subjects = new Set(shown.map((n) => n.category)).size;
      wrap.querySelector(".brain-when").textContent = cursor === Infinity ? "Now" : fmtDay(Math.floor(Math.min(at, t1 - 1)));
      wrap.querySelector(".brain-stats").textContent = `${shown.length} knowledge file${shown.length === 1 ? "" : "s"} in ${subjects} cluster${subjects === 1 ? "" : "s"} · `
        + `${syn} connection${syn === 1 ? "" : "s"}` + (week ? ` · +${week} in the ${cursor === Infinity ? "last 7 days" : "7 days before this point"}` : "");
      const x = ((at - t0) / Math.max(1, t1 - t0)) * 400;
      const mark = svg.querySelector(".mark");
      mark.setAttribute("x1", x); mark.setAttribute("x2", x);
    }
    function spark() {
      const span = Math.max(1, t1 - t0), total = Math.max(1, nodes.length);
      const days = nodes.map((n) => n.day).sort((a, b) => a - b);
      let d = "M0 44", count = 0;
      for (const day of days) { count++; d += ` L${(((day - t0) / span) * 400).toFixed(1)} ${(44 - (count / total) * 40).toFixed(1)}`; }
      d += ` L400 ${(44 - (count / total) * 40).toFixed(1)}`;
      svg.querySelector(".line").setAttribute("d", d);
      svg.querySelector(".area").setAttribute("d", d + " L400 44 Z");
    }

    // which particles are lit: the brain fills in outward from the clusters as knowledge grows
    function litParticles(now) {
      const shownCats = cats.filter((c) => clusters[c].members.some((n) => grown(n, now) > 0));
      const key = shownCats.join();
      if (key !== litKey) {
        litKey = key;
        const centres = shownCats.map((c) => clusters[c]);
        litOrder = particles.map((p, i) => {
          let d = 2.5;
          for (const c of centres) d = Math.min(d, Math.hypot(p.x - c.x, p.y - c.y, p.z - c.z));
          p.tint = null;
          const base = BASE[p.x < -0.25 ? 0 : p.x < 0.35 ? 1 : 2];
          for (const c of centres) {
            const dc = Math.hypot(p.x - c.x, p.y - c.y, p.z - c.z);
            if (dc < 0.13) p.tint = mix(base, c.color, 0.6);
            else if (dc < 0.24 && !p.tint) p.tint = mix(base, c.color, 0.32);
          }
          return [d * 0.8 + (hash(i) % 1000) / 1000 * 0.9, i];
        }).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
      }
      const known = nodes.reduce((s, n) => s + grown(n, now), 0);
      const frac = 0.16 + 0.84 * (1 - Math.exp(-known / 38));
      const count = Math.round(frac * particles.length);
      const lit = new Uint8Array(particles.length);
      for (let i = 0; i < count; i++) lit[litOrder[i]] = 1;
      return lit;
    }

    // ---------- camera ----------
    let W = 0, H = 0, S = 1, CX = 0, CY = 0, cy = 1, sy = 0, cp = 1, sp = 0;
    function setCamera(now) {
      if (!reduceMotion && !drag && !hover && !focus && now - cam.userAt > 5000) {   // a slow sway, mostly side-on so clusters stay readable
        cam.yaw += (-0.22 + 0.32 * Math.sin(now / 11000) - cam.yaw) * 0.004;
      }
      cy = Math.cos(cam.yaw); sy = Math.sin(cam.yaw); cp = Math.cos(cam.pitch); sp = Math.sin(cam.pitch);
      W = cv.clientWidth; H = cv.clientHeight;
      S = Math.min(W / 2.5, H / 2.15) * cam.k;
      CX = W / 2; CY = H * 0.47;
    }
    function project(x, y, z) {
      const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
      const y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
      const f = 3.6 / (3.6 - z2);
      return [CX + x1 * f * S, CY - y2 * f * S, z2, f];
    }

    // ---------- drawing ----------
    let lastDraw = 0, onScreen = true;
    if ("IntersectionObserver" in window) {   // no drawing at all while the brain is scrolled out of view
      new IntersectionObserver((es) => { onScreen = es.some((e) => e.isIntersecting); }).observe(cv);
    }
    function frame(now) {
      if (!document.body.contains(cv)) { stopLive(); return; }
      const lively = drag || playing || (focus && now - focus.start < 800);
      if (!document.hidden && onScreen && (lively || now - lastDraw > 32)) { lastDraw = now; draw(now); }   // ~30 fps at rest
      if (playing) step(now);
      requestAnimationFrame(frame);
    }
    function draw(now) {
      const dpr = window.devicePixelRatio || 1;
      setCamera(now);
      if (!W || !H) return;
      if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const fp = focus ? ease(clamp((now - focus.start) / 650, 0, 1)) * (focus.closing ? -1 : 1) + (focus.closing ? 1 : 0) : 0;
      if (focus && focus.closing && fp <= 0.001) { focus = null; focusBar.hidden = true; }
      const dim = 1 - 0.72 * fp;
      const t = now / 1000;

      ctx.globalCompositeOperation = "lighter";
      // the particle cloud
      const lit = litParticles(now);
      const buckets = {};
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.a += ((lit[i] ? 1 : 0) - p.a) * 0.06;
        if (p.file) { [p.sx, p.sy] = project(p.x, p.y, p.z); continue; }   // drawn as a lit neuron below
        if (p.a < 0.02) continue;
        const [x, y, z] = project(p.x, p.y, p.z);
        p.sx = x; p.sy = y;
        const depth = clamp((z + 1) / 2, 0, 1);
        const tw = reduceMotion ? 1 : 0.75 + 0.25 * Math.sin(t * 1.7 + p.tw);
        const alpha = Math.min(1, p.a * dim * tw * (0.35 + 0.65 * depth) * (p.vein ? 1 : 0.75) * (W < 620 ? 0.6 : 1));
        const col = p.tint || BASE[p.x < -0.25 ? 0 : p.x < 0.35 ? 1 : 2];
        const key = col.join() + "|" + Math.round(alpha * 12);
        (buckets[key] = buckets[key] || { col, a: Math.max(1, Math.round(alpha * 12)) / 12, pts: [] }).pts.push([x, y, p.size * (0.7 + depth * 0.6) * (W < 620 ? 0.75 : 1)]);
      }
      // a soft bloom first (drawn small and blurred), then the sharp points and fold filaments on top
      const gw = Math.max(1, Math.round(W / 3)), gh = Math.max(1, Math.round(H / 3));
      if (glow.width !== gw || glow.height !== gh) { glow.width = gw; glow.height = gh; }
      gctx.setTransform(1, 0, 0, 1, 0, 0);
      gctx.clearRect(0, 0, gw, gh);
      gctx.setTransform(1 / 3, 0, 0, 1 / 3, 0, 0);
      gctx.globalCompositeOperation = "lighter";
      for (const b of Object.values(buckets)) {
        gctx.fillStyle = rgba(b.col, Math.min(1, b.a * 0.9));
        gctx.beginPath();
        for (const [x, y, sz] of b.pts) gctx.rect(x - sz * 1.5, y - sz * 1.5, sz * 3, sz * 3);
        gctx.fill();
      }
      ctx.save();
      ctx.filter = `blur(${small ? 6 : 9}px)`;
      ctx.globalAlpha = W < 620 ? 0.5 : 0.85;
      ctx.drawImage(glow, 0, 0, W, H);
      ctx.restore();
      for (const b of Object.values(buckets)) {
        ctx.fillStyle = rgba(b.col, b.a);
        ctx.beginPath();
        for (const [x, y, sz] of b.pts) ctx.rect(x - sz / 2, y - sz / 2, sz, sz);
        ctx.fill();
      }
      ctx.lineWidth = 0.7;
      ctx.strokeStyle = rgba([175, 165, 255], 0.34 * dim);
      ctx.beginPath();
      for (const [p, q] of mesh) {
        if (p.a < 0.3 || q.a < 0.3) continue;
        ctx.moveTo(p.sx, p.sy); ctx.lineTo(q.sx, q.sy);
      }
      ctx.stroke();
      // threads reaching out, more of them as the brain grows
      const known = nodes.filter((n) => grown(n, now) >= 1).length;
      const reach = Math.min(filaments.length, 8 + known);
      for (let i = 0; i < reach; i++) {
        const f = filaments[i];
        if (f.a.a < 0.3) continue;
        const a = project(f.a.x, f.a.y, f.a.z), c = project(...f.c), b = project(...f.b);
        const g = ctx.createLinearGradient(a[0], a[1], b[0], b[1]);
        g.addColorStop(0, rgba([130, 175, 255], 0.38 * dim)); g.addColorStop(1, rgba([120, 170, 255], 0));
        ctx.strokeStyle = g; ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(c[0], c[1], b[0], b[1]); ctx.stroke();
        if (!reduceMotion) {
          const u = (t * f.speed + f.phase) % 1, v = 1 - u;
          const x = v * v * a[0] + 2 * v * u * c[0] + u * u * b[0], y = v * v * a[1] + 2 * v * u * c[1] + u * u * b[1];
          ctx.fillStyle = rgba([190, 220, 255], 0.8 * (1 - u) * dim);
          ctx.beginPath(); ctx.arc(x, y, 1.5, 0, TAU); ctx.fill();
        }
      }

      // clusters and the pathways between them
      const z = Math.min(1.25, Math.max(0.6, S / 230));
      for (const c of Object.values(clusters)) {
        const shown = c.members.filter((n) => grown(n, now) > 0);
        c.shown = shown;
        [c.sx, c.sy, c.sz, c.f] = project(c.x, c.y, c.z);
        c.sr = (14 + 7 * Math.sqrt(shown.length)) * c.f * z * (W < 620 ? 0.7 : 1);
        c.health = shown.length ? Math.round(shown.reduce((s, n) => s + n.health, 0) / shown.length) : 0;
      }
      for (const l of catLinks) {
        const A = clusters[l.a], B = clusters[l.b];
        const on = l.edges.some((e) => grown(e.a, now) >= 1 && grown(e.b, now) >= 1);
        if (!on) continue;
        const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2 + 0.25, mz = Math.max(A.z, B.z) + 0.35;
        const m = project(mx, my, mz);
        const focused = focus && (focus.cat === l.a || focus.cat === l.b);
        const a = focus ? (focused ? 0.35 : 0.02) : 0.06 + Math.min(0.1, l.n * 0.025);
        ctx.strokeStyle = rgba(A.light, a); ctx.lineWidth = Math.min(1.2, 0.5 + l.n * 0.12);
        ctx.beginPath(); ctx.moveTo(A.sx, A.sy); ctx.quadraticCurveTo(m[0], m[1], B.sx, B.sy); ctx.stroke();
        if (!reduceMotion && (!focus || focused)) {
          const u = (t * l.speed + l.phase) % 1, v = 1 - u;
          const x = v * v * A.sx + 2 * v * u * m[0] + u * u * B.sx, y = v * v * A.sy + 2 * v * u * m[1] + u * u * B.sy;
          ctx.fillStyle = rgba(A.light, 0.6);
          ctx.beginPath(); ctx.arc(x, y, 1.3, 0, TAU); ctx.fill();
        }
      }
      for (const c of Object.values(clusters)) {
        if (!c.shown.length) continue;
        const isFocus = focus && focus.cat === c.cat;
        const k = isFocus ? 1 - fp : 1 - 0.8 * fp;
        if (k <= 0.01) continue;
        const pulse = reduceMotion ? 1 : 1 + 0.06 * Math.sin(t * 2 + c.x * 3);
        const vital = 0.5 + 0.5 * (c.health / 100);
        const r = c.sr * pulse * (hover === c ? 1.15 : 1);
        const g = ctx.createRadialGradient(c.sx, c.sy, 0, c.sx, c.sy, r * 1.6);
        g.addColorStop(0, rgba(c.color, 0.1 * vital * k));
        g.addColorStop(1, rgba(c.color, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(c.sx, c.sy, r * 1.6, 0, TAU); ctx.fill();
        for (const n of c.shown) { const q = particles[n.pi]; n.px = q.sx; n.py = q.sy; }
        ctx.lineWidth = 0.7;
        ctx.strokeStyle = rgba(c.light, 0.4 * k);
        ctx.beginPath();
        for (const e of edges) {
          if (e.a.category !== c.cat || e.b.category !== c.cat || grown(e.a, now) < 1 || grown(e.b, now) < 1) continue;
          if (e.a.px === undefined || e.b.px === undefined) continue;
          ctx.moveTo(e.a.px, e.a.py); ctx.lineTo(e.b.px, e.b.py);
        }
        ctx.stroke();
        for (const n of c.shown) {   // the file's own particle, lit up
          if (n.px === undefined) continue;
          const p = grown(n, now), [, , , f] = project(n.x, n.y, n.z);
          const rr = (1.2 + n.health / 70) * f * z * ease(p) * (W < 620 ? 0.85 : 1);
          const glowR = rr * 3.2;
          const h = ctx.createRadialGradient(n.px, n.py, 0, n.px, n.py, glowR);
          h.addColorStop(0, rgba(c.light, 0.35 * k * p)); h.addColorStop(1, rgba(c.light, 0));
          ctx.fillStyle = h; ctx.beginPath(); ctx.arc(n.px, n.py, glowR, 0, TAU); ctx.fill();
          ctx.fillStyle = rgba(c.light, 0.95 * k * p);
          ctx.beginPath(); ctx.arc(n.px, n.py, rr, 0, TAU); ctx.fill();
          if (p < 1) {
            ctx.strokeStyle = rgba(c.light, (1 - p) * 0.7 * k); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.arc(n.px, n.py, 3 + p * 18, 0, TAU); ctx.stroke();
          }
        }
      }
      ctx.globalCompositeOperation = "source-over";
      // cluster names: biggest first; a name that would overlap another moves above its cluster, or waits
      ctx.textAlign = "center";
      const placed = [];
      const free = (r) => !placed.some((q) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h);
      const font = getComputedStyle(document.body).fontFamily, tight = W < 620;
      for (const c of Object.values(clusters).sort((a, b) => (b.shown || []).length - (a.shown || []).length)) {
        if (!c.shown.length || (focus && focus.cat === c.cat && fp > 0.2)) continue;
        const front = clamp((c.sz + 0.6) / 1.2, 0.35, 1);
        const label = tight ? `${catName(c.cat).replace("Artificial Intelligence", "AI")} · ${c.shown.length}` : catName(c.cat);
        ctx.font = `600 ${tight ? 10.5 : 12.5}px ${font}`;
        const lw = ctx.measureText(label).width, lx = clamp(c.sx, lw / 2 + 4, W - lw / 2 - 4);
        const lh = tight ? 13 : 30, below = c.sy + c.sr * (tight ? 0.7 : 1) + (tight ? 12 : 16);
        let ly = null;
        for (const y of [below, c.sy - c.sr * (tight ? 0.7 : 1) - (tight ? 6 : 22)]) {
          const r = { x: lx - lw / 2 - 3, y: y - 11, w: lw + 6, h: lh };
          if (free(r)) { placed.push(r); ly = y; break; }
        }
        if (ly === null) continue;
        ctx.globalAlpha = (1 - 0.75 * fp) * front;
        ctx.fillStyle = "#eef0ff";
        ctx.fillText(label, lx, ly);
        if (!tight) {
          ctx.font = `11px ${font}`;
          ctx.fillStyle = "rgba(200,205,240,.7)";
          ctx.fillText(`${c.shown.length} file${c.shown.length === 1 ? "" : "s"}`, lx, ly + 14);
        }
      }
      ctx.globalAlpha = 1;
      if (focus) drawFocus(now, fp);
      if (hover && !focus) clusterTip(hover);
    }

    // ---------- an opened cluster ----------
    function focusLayout(c) {   // an even spiral that fills the space, so names don't collide
      const list = c.shown, n = list.length, out = new Map();
      const top = 58, rx = W * 0.4, ry = (H - top) * 0.4, cx = W / 2, cyy = top + (H - top) / 2;
      list.forEach((node, i) => {
        if (n === 1) { out.set(node, [cx, cyy]); return; }
        const r = Math.sqrt((i + 0.6) / n), a = i * 2.39996 - Math.PI / 2;
        out.set(node, [cx + Math.cos(a) * r * rx, cyy + Math.sin(a) * r * ry]);
      });
      return out;
    }
    function drawFocus(now, fp) {
      const c = clusters[focus.cat];
      if (!c || !c.shown.length) return;
      const pos = focusLayout(c);
      const tight = W < 620;
      const z = tight ? 0.8 : 1;
      const back = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.min(W, H) * 0.62);
      back.addColorStop(0, `rgba(5,6,16,${0.82 * fp})`); back.addColorStop(0.7, `rgba(5,6,16,${0.55 * fp})`); back.addColorStop(1, "rgba(5,6,16,0)");
      ctx.fillStyle = back; ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      // the core where the cluster sat, now opened
      const core = [W / 2 * fp + c.sx * (1 - fp), (H / 2 + 6) * fp + c.sy * (1 - fp)];
      const g = ctx.createRadialGradient(core[0], core[1], 0, core[0], core[1], 90 * fp + 20);
      g.addColorStop(0, rgba(c.color, 0.12 * fp)); g.addColorStop(1, rgba(c.color, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(core[0], core[1], 90 * fp + 20, 0, TAU); ctx.fill();
      for (const n of c.shown) {   // where each file sits now, part way from the knot to its place
        const [x0, y0] = project(n.x, n.y, n.z);
        const [x1, y1] = pos.get(n);
        n.ex = x0 + (x1 - x0) * fp; n.ey = y0 + (y1 - y0) * fp;
      }
      // threads from the core, and links inside the cluster and out to other clusters
      for (const n of c.shown) {
        ctx.strokeStyle = rgba(c.light, 0.1 * fp); ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.moveTo(core[0], core[1]); ctx.lineTo(n.ex, n.ey); ctx.stroke();
      }
      for (const e of edges) {
        const ina = e.a.category === c.cat && c.shown.includes(e.a), inb = e.b.category === c.cat && c.shown.includes(e.b);
        if (!ina && !inb) continue;
        const near = hover && (hover === e.a || hover === e.b);
        if (ina && inb) {
          ctx.strokeStyle = rgba(c.light, (near ? 0.7 : 0.3) * fp); ctx.lineWidth = near ? 1.4 : 0.8;
          ctx.beginPath(); ctx.moveTo(e.a.ex, e.a.ey); ctx.lineTo(e.b.ex, e.b.ey); ctx.stroke();
        } else {
          const mine = ina ? e.a : e.b, other = clusters[(ina ? e.b : e.a).category];
          if (!other || !other.shown.length) continue;
          ctx.strokeStyle = rgba(other.light, (near ? 0.6 : 0.18) * fp); ctx.lineWidth = near ? 1.2 : 0.8;
          ctx.setLineDash([3, 4]);
          ctx.beginPath(); ctx.moveTo(mine.ex, mine.ey); ctx.lineTo(other.sx, other.sy); ctx.stroke();
          ctx.setLineDash([]);
        }
      }
      // the files themselves
      for (const n of c.shown) {
        const r = (3 + n.health / 25) * z * (hover === n ? 1.3 : 1);
        const vital = 0.45 + 0.55 * (n.health / 100);
        const g2 = ctx.createRadialGradient(n.ex, n.ey, 0, n.ex, n.ey, r * 3.2);
        g2.addColorStop(0, rgba(c.light, 0.3 * vital)); g2.addColorStop(1, rgba(c.light, 0));
        ctx.fillStyle = g2; ctx.beginPath(); ctx.arc(n.ex, n.ey, r * 3.2, 0, TAU); ctx.fill();
        ctx.fillStyle = rgba(c.light, 0.95 * vital); ctx.beginPath(); ctx.arc(n.ex, n.ey, r, 0, TAU); ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
      if (fp > 0.55) {
        ctx.globalAlpha = (fp - 0.55) / 0.45;
        ctx.textAlign = "center";
        const font = getComputedStyle(document.body).fontFamily;
        for (const n of c.shown) {
          const r = (3 + n.health / 25) * z;
          ctx.font = `${hover === n ? 600 : 500} ${tight ? 10.5 : 12.5}px ${font}`;
          ctx.fillStyle = "#f2f3ff";
          const max = W < 420 ? 15 : tight ? 18 : 30;
          const title = n.title.length > max ? n.title.slice(0, max - 1) + "…" : n.title;
          ctx.fillText(title, n.ex, n.ey + r + 14);
          if (tight) continue;   // health shows on hover when space is short
          ctx.font = `${small ? 9.5 : 10.5}px ${font}`;
          ctx.fillStyle = n.health >= 80 ? "rgba(140,230,190,.85)" : n.health >= 60 ? "rgba(240,210,130,.85)" : "rgba(250,150,140,.85)";
          ctx.fillText(`${n.health}% health`, n.ex, n.ey + r + 28);
        }
        ctx.globalAlpha = 1;
      }
      if (hover && hover.title && fp >= 1) fileTip(hover);
    }
    function tipBox(x, y, lines) {
      const font = getComputedStyle(document.body).fontFamily;
      ctx.font = `12px ${font}`;
      const tw = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 22, th = 14 + lines.length * 17;
      if (x + tw > W - 6) x = W - tw - 6;
      if (y + th > H - 6) y = H - th - 6;
      x = Math.max(6, x); y = Math.max(6, y);
      ctx.fillStyle = "rgba(14,16,34,.92)"; ctx.strokeStyle = "rgba(160,170,255,.35)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect(x, y, tw, th, 8); ctx.fill(); ctx.stroke();
      ctx.textAlign = "left";
      lines.forEach((l, i) => {
        ctx.fillStyle = i ? "rgba(200,205,240,.8)" : "#f2f3ff";
        ctx.font = `${i ? 400 : 600} 12px ${font}`;
        ctx.fillText(l, x + 11, y + 20 + i * 17);
      });
      ctx.textAlign = "center";
    }
    function clusterTip(c) {
      tipBox(c.sx + c.sr + 10, c.sy - 30, [catName(c.cat), `${c.name} · ${c.shown.length} file${c.shown.length === 1 ? "" : "s"}`,
        `average health ${c.health}%`, "Click to open"]);
    }
    function fileTip(n) {
      tipBox(n.ex + 16, n.ey - 20, [n.title, `health ${n.health}% · confidence ${n.confidence}%`,
        `learned ${n.created || "?"} · verified ${n.last_verified || "?"}`, "Click to read"]);
    }
    function openFocus(cat) {
      const c = clusters[cat];
      if (!c || !c.shown || !c.shown.length) return;
      focus = { cat, start: performance.now(), closing: false };
      focusBar.hidden = false;
      focusBar.querySelector("b").textContent = catName(cat);
      focusBar.querySelector("small").textContent = `${c.name} · ${c.shown.length} file${c.shown.length === 1 ? "" : "s"} · average health ${c.health}%`;
      hover = null;
    }
    function closeFocus() {
      if (!focus || focus.closing) return;
      focus = { ...focus, start: performance.now(), closing: true };
      hover = null;
    }
    focusBar.querySelector(".brain-back").addEventListener("click", closeFocus);
    const onKey = (e) => { if (e.key === "Escape" && focus && document.body.contains(cv)) closeFocus(); };
    document.addEventListener("keydown", onKey);

    // ---------- the timeline ----------
    function setCursor(v) {
      cursor = v >= t1 ? Infinity : v;
      slider.value = cursor === Infinity ? 1000 : Math.round(((v - t0) / Math.max(1e-6, t1 - t0)) * 1000);
      stats();
    }
    slider.addEventListener("input", () => {
      playing = null; playBtn.textContent = "▶ Replay growth";
      closeFocus();
      setCursor(slider.value >= 1000 ? Infinity : t0 + (slider.value / 1000) * (t1 - t0));
    });
    playBtn.addEventListener("click", () => {
      if (playing) { playing = null; playBtn.textContent = "▶ Replay growth"; return; }
      closeFocus();
      particles.forEach((p) => { p.a = 0; });
      playing = { start: performance.now(), from: t0 - 0.3, dur: clamp(3000 + nodes.length * 200, 5000, 15000) };
      playBtn.textContent = "❚❚ Pause";
    });
    function step(now) {
      const p = clamp((now - playing.start) / playing.dur, 0, 1);
      setCursor(playing.from + (t1 + 0.2 - playing.from) * p);
      if (p >= 1) { playing = null; playBtn.textContent = "▶ Replay growth"; setCursor(Infinity); }
    }

    // ---------- pointer ----------
    function pick(ev) {
      const r = cv.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
      if (focus && !focus.closing) {
        const c = clusters[focus.cat];
        let best = null, bd = (small ? 24 : 20) ** 2;
        for (const n of c.shown || []) {
          if (n.ex === undefined) continue;
          const d = (n.ex - x) ** 2 + (n.ey - y) ** 2;
          if (d < bd) { bd = d; best = n; }
        }
        if (best) return best;
      }
      let best = null, bd = Infinity;
      for (const c of Object.values(clusters)) {
        if (!c.shown || !c.shown.length || c.sx === undefined || (focus && focus.cat === c.cat)) continue;
        const d = (c.sx - x) ** 2 + (c.sy - y) ** 2;
        if (d < Math.max(c.sr * 1.4, 18) ** 2 && d < bd) { bd = d; best = c; }
      }
      return best;
    }
    cv.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY, yaw: cam.yaw, pitch: cam.pitch, moved: false };
      cv.setPointerCapture(e.pointerId);
    });
    cv.addEventListener("pointermove", (e) => {
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
        if (drag.moved && !focus) {
          cam.yaw = drag.yaw + dx * 0.008; cam.pitch = clamp(drag.pitch + dy * 0.006, -0.6, 0.7); cam.userAt = performance.now();
        }
        return;
      }
      hover = pick(e);
      cv.style.cursor = hover ? "pointer" : focus ? "default" : "grab";
    });
    cv.addEventListener("pointerleave", () => { hover = null; });
    cv.addEventListener("pointerup", (e) => {
      const moved = drag && drag.moved; drag = null;
      if (moved) return;
      const hit = pick(e);
      if (!hit) { if (focus) closeFocus(); return; }
      if (hit.members) openFocus(hit.cat);
      else onOpen(hit.id);
    });
    cv.addEventListener("dblclick", () => { cam = { yaw: -0.28, pitch: 0.1, k: 1, userAt: 0 }; });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      cam.k = clamp(cam.k * (e.deltaY < 0 ? 1.1 : 1 / 1.1), 0.7, 2.4);
    }, { passive: false });

    // ---------- live growth while Corvis learns ----------
    let liveTimer = null;
    function stopLive() {
      if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
      document.removeEventListener("keydown", onKey);
    }
    if (load) {
      liveTimer = setInterval(async () => {
        if (!document.body.contains(cv)) { stopLive(); return; }
        if (document.hidden) return;
        try {
          const g = await load();
          const sig = (ns, es) => ns.map((n) => n.id + ":" + n.health).sort().join() + "|" + es;
          if (sig(g.nodes, g.edges.length) !== sig(nodes, edges.length)) ingest(g, true);
        } catch (_) { /* try again next time */ }
      }, 8000);
    }

    cv.brainState = () => ({   // positions on screen, for automated checks
      clusters: Object.values(clusters).map((c) => ({ cat: c.cat, x: c.sx, y: c.sy, files: (c.shown || []).length })),
      focus: focus && !focus.closing ? focus.cat : null,
      files: focus ? (clusters[focus.cat].shown || []).map((n) => ({ id: n.id, x: n.ex, y: n.ey })) : [] });
    ingest(graph, false);
    setCursor(Infinity);
    requestAnimationFrame(frame);
  }

  window.CorvisBrainView = { mount, regionFor, shape, buildParticles };
})();
