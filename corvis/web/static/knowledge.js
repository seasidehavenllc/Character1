/* Knowledge: Corvis's second brain (#/knowledge). The dashboard, library, relationship graph,
   reviews, reports, long-term memory and GitHub sync. Lives inside the hub (hub.js). */
(function () {
  "use strict";

  const A = window.CorvisApp, H = window.CorvisHub;
  if (!A || !H || !H.register) return;
  const { api, toast, md } = A;
  const { h, ago, every, openPanel, hub } = H.util;
  const esc = md.escape;
  const $ = (s, root = document) => root.querySelector(s);
  const TABS = [["overview", "Overview"], ["library", "Library"], ["graph", "Graph"], ["reviews", "Reviews"],
    ["reports", "Reports"], ["memory", "Memory"], ["sync", "Sync"]];
  const STATUS_PILL = { running: "run", queued: "wait", done: "ok", failed: "bad", stopped: "", interrupted: "wait" };

  function healthClass(score) {
    return score >= 95 ? "h-ex" : score >= 80 ? "h-ok" : score >= 60 ? "h-check" : score >= 40 ? "h-aging" : "h-old";
  }
  function healthPill(hl) {
    return `<span class="kpill ${healthClass(hl.score)}" title="${esc(hl.label)}">${hl.score}% · ${esc(hl.label)}</span>`;
  }
  const catName = (c) => String(c).replace(/([a-z])([A-Z])/g, "$1 $2");
  function stripFront(text) { return text.replace(/^---\n[\s\S]*?\n---\n?/, ""); }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  const CAT_HUES = [228, 172, 32, 280, 350, 200, 120, 55, 300, 10];
  function catColor(cat, cats) {
    const i = Math.max(0, cats.indexOf(cat));
    return `hsl(${CAT_HUES[i % CAT_HUES.length]} 62% ${document.documentElement.dataset.theme === "light" ? 42 : 66}%)`;
  }
  async function updateCount() {
    try {
      const pend = await api("/api/brain/pending");
      $("#knowledge-count").textContent = pend.length ? `${pend.length} to review` : "";
    } catch (_) { $("#knowledge-count").textContent = ""; }
  }

  // ---------- the page ----------
  async function page(tab) {
    tab = TABS.some(([k]) => k === tab) ? tab : "overview";
    hub.innerHTML = "";
    const pg = h(`<div class="hub-page knowledge">
      <header class="hub-head"><div><h1>Knowledge</h1>
        <p class="hub-sub">Corvis's second brain: what he has learned, how sure he is, and the memory of your work together. Kept in Git, backed up to GitHub.</p></div></header>
      <nav class="k-tabs" aria-label="Knowledge sections">${TABS.map(([k, l]) =>
        `<a href="#/knowledge/${k}" class="${k === tab ? "on" : ""}" data-tab="${k}">${l}</a>`).join("")}</nav>
      <div class="k-body"><p class="hub-loading">Loading…</p></div></div>`);
    hub.appendChild(pg);
    pg.querySelectorAll(".k-tabs a").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault(); A.navigate(a.getAttribute("href"));
    }));
    const body = $(".k-body", pg);
    await ({ overview, library, graph, reviews, reports, memory, sync })[tab](body);
    updateCount();
  }

  // ---------- overview ----------
  async function overview(box) {
    let data = await api("/api/brain");
    const open = new Set();
    box.innerHTML = "";
    const v = h(`<div class="k-overview">
      <section class="k-health hub-card"></section>
      <section class="k-learn hub-card">
        <h3>Learn something</h3>
        <p class="hint">Corvis searches the web, reads trusted sources (official docs, tutorials, public GitHub), compares them and writes what he learns in his own words. You can also just say <i>Corvis learn "Robotics"</i> in a chat.</p>
        <form class="k-learn-form">
          <input name="topic" maxlength="120" placeholder="Robotics, ROS 2, battery chemistry…" required aria-label="Topic">
          <div class="seg" role="radiogroup" aria-label="Kind of session">
            <button type="button" class="on" data-mode="learn" title="A focused session: a handful of subtopics">Learn</button>
            <button type="button" data-mode="research" title="A long session: many sources, follows related topics">Research</button></div>
          <button class="btn primary">Start</button>
        </form>
        <p class="hint k-mode-hint">About 30 sources, up to half an hour.</p>
      </section>
      <section class="k-cats hub-card"><h3>Health by category</h3><div class="k-bars"></div></section>
      <section class="k-jobs"><div class="card-head"><h2 class="hub-h2">Learning sessions</h2>
        <button class="link-btn" type="button" data-maintain>Run health check now</button></div><ul class="k-job-list"></ul></section>
    </div>`);
    box.appendChild(v);
    let mode = "learn";
    v.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
      mode = b.dataset.mode;
      v.querySelectorAll("[data-mode]").forEach((x) => x.classList.toggle("on", x === b));
      $(".k-mode-hint", v).textContent = mode === "research"
        ? "A long session: up to 300 sources over about 3 hours, following related topics and updating what he already knows."
        : "About 30 sources, up to half an hour.";
    }));
    const form = $(".k-learn-form", v);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const job = await api("/api/brain/jobs", { method: "POST", body: { topic: form.topic.value, mode } });
        form.topic.value = ""; open.add(job.id);
        toast(`${mode === "research" ? "Research" : "Learning"} session started.`);
        load();
      } catch (err) { toast(err.message); }
    });
    $("[data-maintain]", v).addEventListener("click", async () => {
      try {
        const r = await api("/api/brain/maintain", { method: "POST" });
        toast(`Health check done: ${r.rescored} scores updated, ${r.due} file${r.due === 1 ? "" : "s"} due for re-verification${r.job ? " (re-checking now)" : ""}.`, 6000);
        load();
      } catch (err) { toast(err.message); }
    });

    function draw() {
      const d = data.dashboard;
      const ring = 2 * Math.PI * 52, pct = d.total_files ? d.overall_health : 0;
      $(".k-health", v).innerHTML = `
        <div class="k-ring ${healthClass(pct)}"><svg viewBox="0 0 120 120" aria-hidden="true">
          <circle cx="60" cy="60" r="52" class="track"/><circle cx="60" cy="60" r="52" class="val"
            stroke-dasharray="${ring}" stroke-dashoffset="${ring * (1 - pct / 100)}"/></svg>
          <div><b>${d.total_files ? pct + "%" : "–"}</b><small>${esc(d.overall_label)}</small></div></div>
        <div class="k-stats">
          ${[["Files", d.total_files], ["Categories", d.total_categories], ["Sources", d.total_sources],
             ["Healthy", d.healthy_files], ["Need review", d.needs_review], ["High priority", d.high_priority],
             ["Relationships", d.relationships], ["To review", d.pending_reviews]]
          .map(([l, n]) => `<div class="k-stat"><b>${n}</b><small>${l}</small></div>`).join("")}
        </div>`;
      const cats = Object.entries(d.categories);
      $(".k-bars", v).innerHTML = cats.length ? cats.map(([c, x]) => `
        <a class="k-bar" href="#/knowledge/library" data-cat="${esc(c)}"><span>${esc(catName(c))}</span>
          <i class="${healthClass(x.health)}"><em style="width:${x.health}%"></em></i><small>${x.health}% · ${x.files}</small></a>`).join("")
        : `<p class="hub-empty">Nothing learned yet. Start a session and categories fill in here.</p>`;
      v.querySelectorAll(".k-bar").forEach((a) => a.addEventListener("click", (e) => {
        e.preventDefault(); sessionStorage.setItem("k-cat", a.dataset.cat); A.navigate("#/knowledge/library");
      }));
      const list = $(".k-job-list", v);
      list.innerHTML = "";
      if (!data.jobs.length) list.appendChild(h(`<li class="hub-empty">No sessions yet.</li>`));
      for (const j of data.jobs) {
        const s = j.summary || {};
        const li = h(`<li class="k-job hub-card">
          <div class="k-job-top"><span class="pill ${STATUS_PILL[j.status] || ""}">${esc(j.status)}</span>
            <b></b><small class="muted">${j.mode} · ${j.by === "schedule" ? "scheduled" : esc(j.by)} · ${ago(j.started || j.created)}</small>
            ${["running", "queued"].includes(j.status) ? `<button class="btn ghost small" type="button" data-stop>Stop</button>` : ""}
            ${["interrupted", "stopped", "failed"].includes(j.status) && j.mode !== "verify" ? `<button class="btn ghost small" type="button" data-resume title="Start it again; topics already learned or checked today are skipped">Resume</button>` : ""}
            <button class="link-btn" type="button" data-log>${open.has(j.id) ? "Hide log" : "Log"}</button></div>
          <p class="hint">${j.summary ? `${s.new_files} new · ${s.updated_files} updated · ${s.pending} for review · ${s.verified} verified · ${s.sources_reviewed} sources · ${s.minutes} min`
            : esc((j.log[j.log.length - 1] || {}).text || "Waiting to start…")}
            ${j.report ? ` · <a href="#" data-report="${esc(j.report)}">report</a>` : ""}</p>
          ${open.has(j.id) ? `<ol class="k-log">${j.log.slice(-40).map((l) => `<li><time>${new Date(l.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time> ${esc(l.text)}</li>`).join("")}</ol>` : ""}
        </li>`);
        $("b", li).textContent = j.topic;
        $("[data-log]", li).addEventListener("click", () => { open.has(j.id) ? open.delete(j.id) : open.add(j.id); draw(); });
        const stop = $("[data-stop]", li);
        if (stop) stop.addEventListener("click", async () => { await api(`/api/brain/jobs/${j.id}/stop`, { method: "POST" }); load(); });
        const resume = $("[data-resume]", li);
        if (resume) resume.addEventListener("click", async () => {
          try { const nj = await api("/api/brain/jobs", { method: "POST", body: { topic: j.topic, mode: j.mode } }); open.add(nj.id); load(); }
          catch (err) { toast(err.message); }
        });
        const rep = $("[data-report]", li);
        if (rep) rep.addEventListener("click", (e) => { e.preventDefault(); showRaw(j.report, "Learning report"); });
        list.appendChild(li);
      }
      const log = $(".k-log", v);
      if (log) log.scrollTop = log.scrollHeight;
    }
    async function load() { data = await api("/api/brain"); if (document.body.contains(v)) draw(); }
    draw();
    every(4000, () => document.body.contains(v) && (data.active || data.jobs.some((j) => j.status === "queued")) && load().catch(() => {}));
  }

  // ---------- reading files ----------
  async function showFile(id) {
    openPanel(`<p class="hub-loading">Loading…</p>`, "knowledge", id);
    const panel = $("#side-panel");
    try {
      const d = await api(`/api/brain/file?id=${encodeURIComponent(id)}`);
      panel.innerHTML = `<header class="panel-head"><b></b><button class="icon-btn" type="button" data-close aria-label="Close">${A.svg("i-close")}</button></header>
        <div class="panel-body k-doc">
          <div class="k-doc-meta">${healthPill(d.health)} <span class="kpill">confidence ${d.confidence}%</span>
            <span class="kpill">${esc(catName(d.category))}</span></div>
          <p class="hint">Created ${esc(d.created || "?")} · last verified ${esc(d.last_verified || "?")}${d.health.overdue ? " · <b class='warn'>due for re-verification</b>" : ""}</p>
          ${d.pending ? `<p class="k-note">An update is waiting for your review (${esc(d.pending.reason)}). <a href="#/knowledge/reviews">Review it</a></p>` : ""}
          <div class="content k-md"></div>
          ${d.paths.length ? `<h4>Relationship paths</h4><ul class="k-paths">${d.paths.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}
          ${d.archive.length ? `<h4>Earlier versions</h4><ul class="k-arch">${d.archive.map((a) => `<li><a href="#" data-path="${esc(a.path)}">${esc(a.when.replace("T", " ").replace(/-(\d\d)-(\d\d)$/, ":$1"))}</a> — ${esc(a.reason)}</li>`).join("")}</ul>` : ""}
          <p class="hint">${esc(d.path)}</p>
        </div>`;
      $(".panel-head b", panel).textContent = d.title;
      // links between knowledge files are relative (../Electronics/Arduino.md): make them open here
      const linked = d.body.replace(/\[([^\]]+)\]\((?:\.\.\/([A-Za-z0-9]+)\/)?([A-Za-z0-9]+)\.md\)/g,
        (_, label, cat, slug) => `[${label}](https://k.corvis/${cat || d.category}/${slug})`);
      $(".k-md", panel).innerHTML = md.render(linked);
      panel.querySelectorAll(".k-md a[href^='https://k.corvis/']").forEach((a) => {
        const id = a.getAttribute("href").slice("https://k.corvis/".length);
        a.removeAttribute("target"); a.href = "#";
        a.addEventListener("click", (e) => { e.preventDefault(); showFile(id); });
      });
      panel.querySelectorAll("[data-path]").forEach((a) => a.addEventListener("click", (e) => {
        e.preventDefault(); showRaw(a.dataset.path, `${d.title} (archived)`);
      }));
    } catch (err) { panel.innerHTML = `<p class="hub-empty">${esc(err.message)}</p>`; }
  }
  async function showRaw(path, title) {
    openPanel(`<p class="hub-loading">Loading…</p>`, "knowledge-raw", path);
    const panel = $("#side-panel");
    try {
      const d = await api(`/api/brain/raw?path=${encodeURIComponent(path)}`);
      panel.innerHTML = `<header class="panel-head"><b></b><button class="icon-btn" type="button" data-close aria-label="Close">${A.svg("i-close")}</button></header>
        <div class="panel-body k-doc"><div class="content k-md"></div><p class="hint">${esc(path)}</p></div>`;
      $(".panel-head b", panel).textContent = title || path;
      $(".k-md", panel).innerHTML = md.render(stripFront(d.text));
    } catch (err) { panel.innerHTML = `<p class="hub-empty">${esc(err.message)}</p>`; }
  }

  // ---------- library ----------
  async function library(box) {
    const ov = await api("/api/brain");
    box.innerHTML = "";
    const v = h(`<div><div class="k-filter">
      <input class="hub-search" type="search" placeholder="Search knowledge" aria-label="Search knowledge">
      <select aria-label="Category"><option value="">All categories</option>${ov.categories.map((c) => `<option value="${esc(c)}">${esc(catName(c))}</option>`).join("")}</select>
    </div><div class="k-files"></div></div>`);
    box.appendChild(v);
    const q = $("input", v), cat = $("select", v), grid = $(".k-files", v);
    cat.value = sessionStorage.getItem("k-cat") || ""; sessionStorage.removeItem("k-cat");
    let t;
    async function load() {
      const files = await api(`/api/brain/files?q=${encodeURIComponent(q.value)}&category=${encodeURIComponent(cat.value)}`);
      grid.innerHTML = "";
      if (!files.length) {
        grid.appendChild(h(`<p class="hub-empty">${q.value || cat.value ? "Nothing matches." : "The library is empty. Start a learning session from Overview."}</p>`));
      }
      for (const f of files) {
        const card = h(`<button type="button" class="k-file">
          <span class="k-file-top"><b></b><span class="kpill">${esc(catName(f.category))}</span></span>
          <span class="k-sum"></span>
          <span class="k-file-meta">${healthPill(f.health)}<small>${f.confidence}% confident · ${f.sources} source${f.sources === 1 ? "" : "s"} · verified ${esc(f.last_verified || "?")}</small></span></button>`);
        $("b", card).textContent = f.title;
        $(".k-sum", card).textContent = f.summary;
        card.addEventListener("click", () => showFile(f.id));
        grid.appendChild(card);
      }
    }
    q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 250); });
    cat.addEventListener("change", load);
    await load();
  }

  // ---------- graph ----------
  async function graph(box) {
    const g = await api("/api/brain/graph");
    window.CorvisBrainView.mount(box, g, { catName, onOpen: showFile,
      load: () => api("/api/brain/graph") });
  }

  // ---------- reviews ----------
  async function reviews(box) {
    const list = await api("/api/brain/pending");
    box.innerHTML = "";
    box.appendChild(h(`<p class="hint">Updates Corvis found but wasn't sure enough to apply on his own. Approving replaces the current file; the old version is archived with the reason. Updates above the auto-approve confidence (Sync tab) are applied without asking.</p>`));
    if (!list.length) { box.appendChild(h(`<p class="hub-empty">Nothing waiting for review.</p>`)); return; }
    for (const p of list) {
      const card = h(`<div class="k-review hub-card">
        <div class="card-head"><h3></h3><small class="muted">confidence ${p.old_confidence ?? "?"}% → ${p.new_confidence}% · proposed ${ago(p.proposed)}</small></div>
        <p class="k-reason"></p>
        <div class="k-diff"><div><h4>Current</h4><p class="o"></p><ul class="op"></ul></div><div><h4>Proposed</h4><p class="n"></p><ul class="np"></ul></div></div>
        <div class="row-end"><button class="link-btn" type="button" data-open>Open file</button>
          <button class="btn ghost" type="button" data-reject>Reject</button><button class="btn primary" type="button" data-approve>Approve</button></div></div>`);
      $("h3", card).textContent = p.title;
      $(".k-reason", card).textContent = `Why: ${p.reason}`;
      $(".o", card).textContent = p.old_summary; $(".n", card).textContent = p.new_summary;
      $(".op", card).innerHTML = p.old_points.map((x) => `<li>${esc(x)}</li>`).join("");
      $(".np", card).innerHTML = p.new_points.map((x) => `<li>${esc(x)}</li>`).join("");
      $("[data-open]", card).addEventListener("click", () => showFile(p.id));
      $("[data-approve]", card).addEventListener("click", async () => {
        try { await api("/api/brain/pending/approve", { method: "POST", body: { id: p.id } }); toast("Approved; the old version is archived."); reviews(box); updateCount(); }
        catch (err) { toast(err.message); }
      });
      $("[data-reject]", card).addEventListener("click", async () => {
        try { await api("/api/brain/pending/reject", { method: "POST", body: { id: p.id } }); toast("Rejected."); reviews(box); updateCount(); }
        catch (err) { toast(err.message); }
      });
      box.appendChild(card);
    }
  }

  // ---------- reports ----------
  async function reports(box) {
    const list = await api("/api/brain/reports");
    box.innerHTML = "";
    if (!list.length) { box.appendChild(h(`<p class="hub-empty">No reports yet. Each learning session adds to today's report, and the weekly and monthly ones.</p>`)); return; }
    for (const kind of ["Daily", "Weekly", "Monthly"]) {
      const items = list.filter((r) => r.kind === kind);
      if (!items.length) continue;
      box.appendChild(h(`<h2 class="hub-h2">${kind}</h2>`));
      const ul = h(`<div class="k-report-list"></div>`);
      for (const r of items) {
        const b = h(`<button type="button" class="k-report">${A.svg("i-file")}<span></span></button>`);
        $("span", b).textContent = r.name;
        b.addEventListener("click", () => showRaw(r.path, `${kind} report ${r.name}`));
        ul.appendChild(b);
      }
      box.appendChild(ul);
    }
  }

  // ---------- memory ----------
  async function memory(box) {
    const [m, g] = await Promise.all([api("/api/brain/memory"), api("/api/brain/greeting").catch(() => ({ text: "" }))]);
    box.innerHTML = "";
    const v = h(`<div class="k-memory">
      <div class="k-greet hub-card"><p></p><div class="row-end"><button class="link-btn" type="button" data-again>New greeting</button>
        <button class="btn ghost small" type="button" data-brief>Brief me</button></div></div>
      <h2 class="hub-h2">Projects</h2><div class="k-projects"></div>
      <h2 class="hub-h2">Ask about past conversations</h2>
      <form class="k-convo-form"><input class="hub-search" name="q" type="search" placeholder="robotics, the killfeed bug…" aria-label="Search past conversations">
        <select name="since" aria-label="When"><option value="0">Any time</option><option value="7">Last week</option><option value="31">Last month</option><option value="365">Last year</option></select></form>
      <ul class="k-convos thread-list"></ul>
      <h2 class="hub-h2">Session summaries</h2><div class="k-sessions"></div></div>`);
    box.appendChild(v);
    $(".k-greet p", v).textContent = g.text || "Greetings appear once there's something to remember.";
    $("[data-again]", v).addEventListener("click", async () => {
      $(".k-greet p", v).textContent = "…";
      const r = await api("/api/brain/greeting?force=1").catch(() => ({ text: "" }));
      $(".k-greet p", v).textContent = r.text;
    });
    $("[data-brief]", v).addEventListener("click", () => briefMe());
    const pj = $(".k-projects", v);
    if (!m.projects.length) pj.appendChild(h(`<p class="hub-empty">No project memory yet. Corvis keeps it as you talk about your projects, or tells him: "remember the DayZ killfeed project".</p>`));
    for (const p of m.projects) {
      const c = h(`<button type="button" class="proj-card k-proj"><div class="proj-top"><b></b><span class="pill"></span></div>
        <p class="proj-desc"></p><small></small></button>`);
      $("b", c).textContent = p.name;
      $(".pill", c).textContent = p.status || "active";
      $(".proj-desc", c).textContent = (p.goals || [])[0] || (p.notes || [])[0] || "No goals recorded yet.";
      $("small", c).textContent = `${(p.open_tasks || []).length} open · ${(p.completed_tasks || []).length} done · updated ${p.updated}`;
      c.addEventListener("click", () => showRaw(p.path, p.name));
      pj.appendChild(c);
    }
    const cf = $(".k-convo-form", v), cl = $(".k-convos", v);
    function drawConvos(items) {
      cl.innerHTML = "";
      if (!items.length) cl.appendChild(h(`<li class="hub-empty">No remembered conversations${cf.q.value ? " match" : " yet"}.</li>`));
      for (const c of items) {
        const li = h(`<li><a href="#/c/${esc(c.conversation)}"><b></b><span class="muted"></span><small></small></a></li>`);
        $("b", li).textContent = c.title;
        $("span", li).textContent = c.summary;
        $("small", li).textContent = `${c.date} · ${c.topic}${(c.open_tasks || []).length ? ` · ${c.open_tasks.length} open task${c.open_tasks.length === 1 ? "" : "s"}` : ""}`;
        $("a", li).addEventListener("click", (e) => { e.preventDefault(); A.navigate(`#/c/${c.conversation}`); });
        cl.appendChild(li);
      }
    }
    let t;
    const search = async () => drawConvos(await api(`/api/brain/conversations?q=${encodeURIComponent(cf.q.value)}&since_days=${cf.since.value}`));
    cf.q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(search, 250); });
    cf.since.addEventListener("change", search);
    cf.addEventListener("submit", (e) => { e.preventDefault(); search(); });
    drawConvos(m.conversations.slice(0, 12));
    const ss = $(".k-sessions", v);
    if (!m.sessions.length) ss.appendChild(h(`<p class="hub-empty">Summaries are written a minute or two after each conversation, and on shutdown.</p>`));
    for (const s of m.sessions) {
      const b = h(`<button type="button" class="k-session hub-card"><b></b><span></span></button>`);
      $("b", b).textContent = new Date(s.date + "T12:00").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });
      $("span", b).textContent = s.topics.map((x) => x.split(":")[0]).join(" · ") || "—";
      b.addEventListener("click", () => showRaw(`Memory/SessionSummaries/${s.date}.md`, `Session ${s.date}`));
      ss.appendChild(b);
    }
  }

  // ---------- sync ----------
  async function sync(box) {
    const s = await api("/api/brain/sync");
    const when = (ts) => ts ? ago(ts) : "never";
    box.innerHTML = "";
    const v = h(`<div class="k-sync">
      <form class="hub-card k-sync-form">
        <h3>GitHub backup</h3>
        <p class="hint">Every change is a Git commit in <code></code>. To back it up, create an empty <b>private</b> repository on GitHub (e.g. corvis-brain, without a README) and a fine-grained token with <i>Contents: read and write</i> on that repository only. The token is kept in Corvis's data folder, never in config.yaml or Git, and is never shown again.</p>
        <label>Repository address<input name="remote" placeholder="https://github.com/you/corvis-brain.git" autocomplete="off"></label>
        <label>Access token<input name="token" type="password" autocomplete="new-password"></label>
        <label class="check"><input type="checkbox" name="auto_push"> Push automatically after changes</label>
        <label>Auto-approve updates at confidence<input name="auto" type="number" min="0" max="100" step="1"></label>
        <p class="hint">Updates Corvis is at least this sure about (and not less sure than before) apply on their own; others wait in Reviews. 0 means always ask.</p>
        <div class="row-end"><span class="hint k-sync-status"></span><button class="btn ghost" type="button" data-pull>Pull</button>
          <button class="btn ghost" type="button" data-push>Push now</button><button class="btn primary">Save</button></div>
      </form>
      <h2 class="hub-h2">Recent commits</h2><ul class="k-commits"></ul></div>`);
    box.appendChild(v);
    const f = $("form", v);
    function fill(s) {
      $("code", v).textContent = s.path;
      f.remote.value = s.remote || "";
      f.token.value = "";
      f.token.placeholder = s.has_token ? "Saved (type to replace, or clear with a single space)" : "github_pat_…";
      f.auto_push.checked = !!s.auto_push;
      f.auto.value = s.auto_approve_confidence;
      $(".k-sync-status", v).innerHTML = `${s.commits} commits · last push ${when(s.last_push)} · last pull ${when(s.last_pull)}`
        + (s.error ? `<br><span class="warn"></span>` : "");
      if (s.error) $(".k-sync-status .warn", v).textContent = s.error;
      $(".k-commits", v).innerHTML = (s.recent || []).map((c) => `<li><code>${esc(c.slice(0, 7))}</code> ${esc(c.slice(8))}</li>`).join("")
        || `<li class="hub-empty">No commits yet.</li>`;
    }
    fill(s);
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const bodyData = { remote: f.remote.value.trim(), auto_push: f.auto_push.checked, auto_approve_confidence: Number(f.auto.value) };
      if (f.token.value) bodyData.token = f.token.value === " " ? "" : f.token.value;
      try { fill(await api("/api/brain/sync", { method: "POST", body: bodyData })); toast("Saved."); }
      catch (err) { toast(err.message, 7000); }
    });
    for (const [sel, url, label] of [["[data-push]", "/api/brain/sync/push", "Pushing…"], ["[data-pull]", "/api/brain/sync/pull", "Pulling…"]]) {
      $(sel, v).addEventListener("click", async () => {
        toast(label);
        try { const r = await api(url, { method: "POST" }); toast(r.message); fill(r); }
        catch (err) { toast(err.message, 8000); fill(await api("/api/brain/sync")); }
      });
    }
  }

  // ---------- the welcome screen: greet from memory ----------
  let greetingText = null;
  async function greet() {
    const p = document.querySelector(".welcome:not(.k-greeted) .job");
    const welcome = p && p.closest(".welcome");
    const lead = welcome && welcome.querySelector(".welcome-mark");
    if (!p || !lead || A.state.conv || A.state.draft.mode === "self") return;
    welcome.classList.add("k-greeted");
    if (greetingText === null) {
      try { greetingText = (await api("/api/brain/greeting")).text || ""; } catch (_) { greetingText = ""; }
    }
    if (!greetingText || !document.body.contains(p)) return;
    const h2 = welcome.querySelector("h2");
    const salute = /^(good (morning|afternoon|evening)|hello|hi|hey|welcome back)\b[^.!?]{0,30}[.!?]\s+/i;
    p.textContent = h2 && salute.test(h2.textContent + " ") ? greetingText.replace(salute, "") : greetingText;
    p.classList.add("k-greeting");
    const sug = welcome.querySelector(".suggestions");
    if (sug && !sug.querySelector(".k-brief")) {
      const b = h(`<button type="button" class="suggestion k-brief">Brief me: where did we leave off?</button>`);
      b.addEventListener("click", () => briefMe());
      sug.prepend(b);
    }
  }
  function briefMe() {
    if (A.state.conv || location.hash.startsWith("#/knowledge")) A.navigate("#/");
    const input = A.el.input;
    input.value = "Brief me: what have you done while I was away, where did we leave off, and what's next on our projects?";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  }
  new MutationObserver(() => greet()).observe(A.el.thread, { childList: true });
  greet();

  H.register("knowledge", "Knowledge", page);
  updateCount();
  setInterval(() => { if (!document.hidden) updateCount(); }, 60000);
})();
