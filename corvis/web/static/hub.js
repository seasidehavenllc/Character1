/* Projects, Code, Artifacts and Scheduled: the Claude-style sections of the Corvis app.
   Pages live at #/projects, #/code, #/artifacts and #/scheduled. app.js hands over routing,
   the chat header and artifact cards through window.CorvisHub. */
(function () {
  "use strict";

  const A = window.CorvisApp;
  const { api, toast, md } = A;
  const esc = md.escape;
  const $ = (s, root = document) => root.querySelector(s);
  const hub = $("#hub"), panel = $("#side-panel"), app = $("#app");
  const NAMES = { projects: "Projects", code: "Code", artifacts: "Artifacts", scheduled: "Scheduled" };
  const TYPE_LABEL = { html: "Web page", markdown: "Document", code: "Code", svg: "Drawing" };
  let timers = [];
  let projectNames = {};
  const extraPages = {};   // sections added by other scripts (knowledge.js) through CorvisHub.register

  // ---------- helpers ----------
  function h(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  function ago(ts) {
    const s = Date.now() / 1000 - ts;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
    return new Date(ts * 1000).toLocaleDateString();
  }
  function until(ts) {
    const s = ts - Date.now() / 1000;
    if (s <= 60) return "any moment";
    if (s < 3600) return `in ${Math.round(s / 60)} min`;
    if (s < 86400) return `in ${Math.round(s / 3600)} h`;
    return new Date(ts * 1000).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  function every(ms, fn) { const t = setInterval(() => { if (!document.hidden) fn(); }, ms); timers.push(t); }
  function stopTimers() { timers.forEach(clearInterval); timers = []; }
  async function upload(file) {
    const res = await fetch(`/api/uploads?name=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { "X-Corvis": "1", "Content-Type": file.type || "application/octet-stream" }, body: file });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
    return data;
  }
  async function startChat(convId, text) {
    await api(`/api/conversations/${convId}/messages`, { method: "POST", body: { text } });
    A.navigate(`#/c/${convId}`);
  }
  function autosize(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 260) + "px"; }
  async function loadProjectNames() {
    try {
      const d = await api("/api/projects");
      projectNames = Object.fromEntries(d.projects.map((p) => [p.id, p.name]));
      return d.projects;
    } catch (_) { return []; }
  }

  // ---------- routing ----------
  function setMode(on, section) {
    app.classList.toggle("hub-mode", on);
    hub.hidden = !on;
    document.querySelectorAll(".hub-link").forEach((a) => a.classList.toggle("active", on && a.dataset.hub === section));
    if (on) {
      A.el.title.textContent = NAMES[section];
      document.title = `${NAMES[section]} | Corvis`;
      document.querySelectorAll(".hub-chip").forEach((n) => n.remove());
    }
  }
  function route(hash) {
    stopTimers();
    if (panel.dataset.at !== hash) closePanel();   // the panel belongs to the page it was opened on
    const m = hash.match(/^#\/([a-z]+)(?:\/([\w-]+))?\/?$/);
    if (!m || !NAMES[m[1]]) { setMode(false); return false; }
    setMode(true, m[1]);
    hub.innerHTML = `<div class="hub-page"><p class="hub-loading">Loading…</p></div>`;
    hub.scrollTop = 0;
    if (A.isPhone()) A.showSidebar(false);
    const pages = { projects: m[2] ? projectPage : projectsPage, code: codePage, artifacts: m[2] ? artifactPage : artifactsPage,
      scheduled: scheduledPage, ...extraPages };
    pages[m[1]](m[2]).catch((err) => {
      hub.innerHTML = `<div class="hub-page"><p class="hub-empty">${esc(err.message)}</p></div>`;
    });
    return true;
  }
  document.querySelectorAll(".hub-link").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault(); A.navigate(a.getAttribute("href"));
  }));

  // ==========================================================================
  // Projects
  // ==========================================================================
  async function projectsPage() {
    const list = await loadProjectNames();
    hub.innerHTML = "";
    const page = h(`<div class="hub-page">
      <header class="hub-head"><div><h1>Projects</h1><p class="hub-sub">Group chats with shared instructions, knowledge files and memory.</p></div>
        <button class="btn primary" type="button" data-new>New project</button></header>
      <form class="hub-card new-project" hidden>
        <label>Name<input name="name" maxlength="80" placeholder="Rover v2" required></label>
        <label>What are you working on?<textarea name="description" rows="2" maxlength="1000" placeholder="An autonomous rover that maps my house"></textarea></label>
        <div class="row-end"><button class="btn ghost" type="button" data-cancel>Cancel</button><button class="btn primary">Create project</button></div>
      </form>
      <input class="hub-search" type="search" placeholder="Search projects" aria-label="Search projects">
      <div class="proj-grid"></div></div>`);
    hub.appendChild(page);
    const form = $(".new-project", page), grid = $(".proj-grid", page);
    $("[data-new]", page).addEventListener("click", () => { form.hidden = false; form.name.focus(); });
    $("[data-cancel]", page).addEventListener("click", () => { form.hidden = true; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const p = await api("/api/projects", { method: "POST", body: { name: form.name.value, description: form.description.value } });
        A.navigate(`#/projects/${p.id}`);
      } catch (err) { toast(err.message); }
    });
    function draw(filter = "") {
      grid.innerHTML = "";
      const shown = list.filter((p) => (p.name + " " + p.description).toLowerCase().includes(filter.toLowerCase()));
      if (!shown.length) {
        grid.appendChild(h(`<p class="hub-empty">${list.length ? "No projects match." : "No projects yet. Make one to keep related chats, files and instructions together."}</p>`));
      }
      for (const p of shown) {
        const card = h(`<a class="proj-card" href="#/projects/${p.id}">
          <div class="proj-top"><b></b>${p.starred ? `<span class="star on">${A.svg("i-star")}</span>` : ""}</div>
          <p class="proj-desc"></p>
          <small>${p.chat_count} chat${p.chat_count === 1 ? "" : "s"} · ${p.files.length} file${p.files.length === 1 ? "" : "s"} · updated ${ago(p.last_active)}</small></a>`);
        $("b", card).textContent = p.name;
        $(".proj-desc", card).textContent = p.description || "No description";
        card.addEventListener("click", (e) => { e.preventDefault(); A.navigate(card.getAttribute("href")); });
        grid.appendChild(card);
      }
    }
    $(".hub-search", page).addEventListener("input", (e) => draw(e.target.value));
    draw();
  }

  async function projectPage(pid) {
    let p = await api(`/api/projects/${pid}`);
    projectNames[p.id] = p.name;
    hub.innerHTML = "";
    const page = h(`<div class="hub-page project-page">
      <a class="hub-back" href="#/projects">‹ All projects</a>
      <div class="project-cols">
        <div class="project-main">
          <header class="project-title">
            <input class="title-input" maxlength="80" aria-label="Project name">
            <button class="icon-btn star" type="button" title="Star project" aria-label="Star project">${A.svg("i-star")}</button>
            <button class="icon-btn" type="button" data-delete title="Delete project" aria-label="Delete project">${A.svg("i-trash")}</button>
          </header>
          <textarea class="desc-input" rows="1" maxlength="1000" placeholder="Add a description"></textarea>
          <form class="project-composer">
            <textarea rows="2" placeholder="Start a chat in this project" aria-label="Message Corvis in this project"></textarea>
            <div class="row-end"><span class="hint">Chats here use the project's instructions, files and memory.</span>
              <button class="btn primary" type="submit">Start chat</button></div>
          </form>
          <h2 class="hub-h2">Chats</h2>
          <ul class="thread-list"></ul>
          <section class="proj-artifacts" hidden><h2 class="hub-h2">Artifacts</h2><div class="art-grid small"></div></section>
        </div>
        <aside class="project-side">
          <section class="hub-card">
            <div class="card-head"><h3>Instructions</h3><button class="link-btn" type="button" data-edit-instr>Edit</button></div>
            <p class="instr-text"></p>
            <form class="instr-form" hidden>
              <textarea rows="8" maxlength="20000" placeholder="How should Corvis work in this project? e.g. 'Use Python 3.12 and type hints. Explain wiring step by step.'"></textarea>
              <div class="row-end"><button class="btn ghost" type="button" data-cancel>Cancel</button><button class="btn primary">Save</button></div>
            </form>
          </section>
          <section class="hub-card">
            <div class="card-head"><h3>Files</h3>
              <span><button class="link-btn" type="button" data-add-text>Add text</button> ·
              <label class="link-btn">Upload<input type="file" multiple hidden data-upload></label></span></div>
            <div class="capacity"><i></i></div><p class="hint cap-note"></p>
            <form class="text-form" hidden>
              <input maxlength="60" placeholder="Title" required>
              <textarea rows="5" placeholder="Paste notes, specs or code" required></textarea>
              <div class="row-end"><button class="btn ghost" type="button" data-cancel>Cancel</button><button class="btn primary">Add</button></div>
            </form>
            <ul class="file-list"></ul>
          </section>
          <section class="hub-card">
            <div class="card-head"><h3>Memory</h3></div>
            <p class="hint">What Corvis learned in this project's chats. Every chat here sees it.</p>
            <ul class="note-list"></ul>
            <form class="note-form"><input maxlength="500" placeholder="Add something to remember"></form>
          </section>
          <section class="hub-card">
            <div class="card-head"><h3>Folder</h3></div>
            <p class="hint">Where Corvis works on files for this project's chats.</p>
            <form class="folder-form"><input spellcheck="false" placeholder="Default folder"><button class="btn ghost">Save</button></form>
          </section>
        </aside>
      </div></div>`);
    hub.appendChild(page);
    const title = $(".title-input", page), desc = $(".desc-input", page);

    async function save(patch) {
      try { p = { ...p, ...(await api(`/api/projects/${pid}`, { method: "PATCH", body: patch })) }; draw(); }
      catch (err) { toast(err.message); }
    }
    function draw() {
      title.value = p.name; desc.value = p.description || ""; autosize(desc);
      $(".star", page).classList.toggle("on", !!p.starred);
      $(".instr-text", page).textContent = p.instructions || "None yet. Tell Corvis how to work in this project.";
      $(".instr-text", page).classList.toggle("muted", !p.instructions);
      const k = p.knowledge;
      $(".capacity i", page).style.width = `${Math.min(100, k.percent)}%`;
      $(".capacity", page).classList.toggle("over", !k.in_full);
      $(".cap-note", page).textContent = !p.files.length ? "Add documents, code, PDFs or notes for Corvis to use."
        : k.in_full ? `${k.percent}% of what Corvis reads in full before every answer.`
        : "Too big to read all at once, so Corvis searches the files when he needs them.";
      const fl = $(".file-list", page); fl.innerHTML = "";
      for (const f of p.files) {
        const li = h(`<li><button class="file-name" type="button"></button><small>${Math.max(1, Math.round(f.chars / 1000))}k chars</small>
          <button class="icon-btn" type="button" aria-label="Remove">${A.svg("i-close")}</button></li>`);
        $(".file-name", li).textContent = f.name;
        $(".file-name", li).addEventListener("click", () => showFile(f));
        li.lastElementChild.addEventListener("click", async () => {
          if (!confirm(`Remove ${f.name} from the project?`)) return;
          p = { ...p, ...(await api(`/api/projects/${pid}/files/${f.id}`, { method: "DELETE" })) }; draw();
        });
        fl.appendChild(li);
      }
      const nl = $(".note-list", page); nl.innerHTML = "";
      if (!p.notes.length) nl.appendChild(h(`<li class="hint">Nothing yet.</li>`));
      for (const n of p.notes) {
        const li = h(`<li><span></span><button class="icon-btn" type="button" aria-label="Forget">${A.svg("i-close")}</button></li>`);
        $("span", li).textContent = n.text;
        li.lastElementChild.addEventListener("click", async () => {
          p = { ...p, ...(await api(`/api/projects/${pid}/notes/${n.id}`, { method: "DELETE" })) }; draw();
        });
        nl.appendChild(li);
      }
      $(".folder-form input", page).value = p.workspace || "";
      $(".folder-form input", page).placeholder = A.state.info ? A.state.info.default_workspace : "Default folder";
      const tl = $(".thread-list", page); tl.innerHTML = "";
      if (!p.chats.length) tl.appendChild(h(`<li class="hub-empty">No chats yet. Start one above.</li>`));
      for (const c of p.chats) {
        const li = h(`<li><a href="#/c/${c.id}"><b></b><small>${c.running ? "<i class=\"running-dot\"></i> working · " : ""}${c.messages} messages · ${ago(c.updated)}</small></a></li>`);
        $("b", li).textContent = c.title;
        li.firstElementChild.addEventListener("click", (e) => { e.preventDefault(); A.navigate(`#/c/${c.id}`); });
        tl.appendChild(li);
      }
      $(".proj-artifacts", page).hidden = !(p.artifacts && p.artifacts.length);
      artGrid($(".proj-artifacts .art-grid", page), p.artifacts || []);
    }
    async function showFile(f) {
      try {
        const d = await api(`/api/projects/${pid}/files/${f.id}`);
        openPanel(`<header class="panel-head"><b></b><button class="icon-btn" type="button" data-close aria-label="Close">${A.svg("i-close")}</button></header>
          <pre class="panel-text"></pre>`);
        $(".panel-head b", panel).textContent = d.name;
        $(".panel-text", panel).textContent = d.text;
      } catch (err) { toast(err.message); }
    }
    title.addEventListener("change", () => save({ name: title.value }));
    desc.addEventListener("input", () => autosize(desc));
    desc.addEventListener("change", () => save({ description: desc.value }));
    $(".star", page).addEventListener("click", () => save({ starred: !p.starred }));
    $("[data-delete]", page).addEventListener("click", async () => {
      if (!confirm(`Delete the project "${p.name}" and its ${p.chats.length} chat(s)? This can't be undone.`)) return;
      try { await api(`/api/projects/${pid}`, { method: "DELETE" }); A.refreshList(); A.navigate("#/projects"); }
      catch (err) { toast(err.message); }
    });
    const instr = $(".instr-form", page);
    $("[data-edit-instr]", page).addEventListener("click", () => { instr.hidden = false; instr.firstElementChild.value = p.instructions || ""; instr.firstElementChild.focus(); });
    $("[data-cancel]", instr).addEventListener("click", () => { instr.hidden = true; });
    instr.addEventListener("submit", async (e) => { e.preventDefault(); await save({ instructions: instr.firstElementChild.value }); instr.hidden = true; });
    const tf = $(".text-form", page);
    $("[data-add-text]", page).addEventListener("click", () => { tf.hidden = false; tf.firstElementChild.focus(); });
    $("[data-cancel]", tf).addEventListener("click", () => { tf.hidden = true; });
    tf.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        p = { ...p, ...(await api(`/api/projects/${pid}/files`, { method: "POST", body: { name: tf.elements[0].value, text: tf.elements[1].value } })) };
        tf.reset(); tf.hidden = true; draw();
      } catch (err) { toast(err.message); }
    });
    $("[data-upload]", page).addEventListener("change", async (e) => {
      for (const file of e.target.files) {
        try {
          const meta = await upload(file);
          p = { ...p, ...(await api(`/api/projects/${pid}/files`, { method: "POST", body: { attachment: meta.id } })) };
          draw();
        } catch (err) { toast(`${file.name}: ${err.message}`, 7000); }
      }
      e.target.value = "";
    });
    $(".note-form", page).addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = e.target.firstElementChild;
      try { p = { ...p, ...(await api(`/api/projects/${pid}/notes`, { method: "POST", body: { text: input.value } })) }; input.value = ""; draw(); }
      catch (err) { toast(err.message); }
    });
    $(".folder-form", page).addEventListener("submit", async (e) => {
      e.preventDefault();
      await save({ workspace: e.target.firstElementChild.value.trim() || null });
      toast("Saved. New chats in this project work in that folder.");
    });
    const composer = $(".project-composer", page), box = composer.querySelector("textarea");
    box.addEventListener("input", () => autosize(box));
    box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !A.isPhone()) { e.preventDefault(); composer.requestSubmit(); } });
    composer.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = box.value.trim();
      if (!text) return box.focus();
      try {
        const conv = await api(`/api/projects/${pid}/chats`, { method: "POST", body: {} });
        await startChat(conv.id, text);
        A.refreshList();
      } catch (err) { toast(err.message); }
    });
    draw();
    every(8000, async () => {
      if (!document.body.contains(page)) return;
      try { const fresh = await api(`/api/projects/${pid}`); if (JSON.stringify(fresh.chats) !== JSON.stringify(p.chats) || fresh.notes.length !== p.notes.length || (fresh.artifacts || []).length !== (p.artifacts || []).length) { p = fresh; draw(); } }
      catch (_) { /* offline for a moment */ }
    });
  }

  // chat header: which project a chat is in (and moving it), code changes
  async function header(conv) {
    document.querySelectorAll(".hub-chip").forEach((n) => n.remove());
    if (!conv || conv.mode === "self") return;
    const bar = $(".topbar"), anchor = $("#voice-open");
    if (conv.kind === "code") {
      const chip = h(`<button class="hub-chip changes" type="button" title="See what Corvis changed">${A.svg("i-branch")}<span>Changes</span></button>`);
      chip.addEventListener("click", () => openChanges(conv));
      bar.insertBefore(chip, anchor);
      refreshChangeChip(conv, chip);
    }
    if (!projectNames[conv.project] && conv.project) await loadProjectNames();
    if (!A.state.conv || A.state.conv.id !== conv.id) return;
    const chip = h(`<button class="hub-chip project" type="button">${A.svg("i-projects")}<span></span></button>`);
    $("span", chip).textContent = conv.project ? (projectNames[conv.project] || "Project") : "Add to project";
    chip.title = conv.project ? "Open the project (or move this chat)" : "Put this chat in a project";
    chip.addEventListener("click", (e) => projectMenu(e, conv, chip));
    bar.insertBefore(chip, $(".hub-chip.changes") || anchor);
  }
  async function projectMenu(e, conv, chip) {
    e.stopPropagation();
    document.querySelectorAll(".hub-menu").forEach((n) => n.remove());
    const list = await loadProjectNames();
    const menu = h(`<div class="hub-menu" role="menu"></div>`);
    const item = (label, fn, cls = "") => { const b = h(`<button type="button" role="menuitem" class="${cls}"></button>`); b.textContent = label; b.addEventListener("click", () => { menu.remove(); fn(); }); menu.appendChild(b); };
    if (conv.project) item(`Open ${projectNames[conv.project] || "project"}`, () => A.navigate(`#/projects/${conv.project}`), "strong");
    for (const p of list) if (p.id !== conv.project) item(`Move to ${p.name}`, () => move(conv, p.id));
    if (conv.project) item("Remove from project", () => move(conv, null));
    item("New project…", async () => {
      const name = prompt("Name for the new project:");
      if (!name) return;
      try { const p = await api("/api/projects", { method: "POST", body: { name } }); await move(conv, p.id); }
      catch (err) { toast(err.message); }
    });
    const r = chip.getBoundingClientRect();
    menu.style.top = `${r.bottom + 6}px`; menu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - 260))}px`;
    document.body.appendChild(menu);
    setTimeout(() => document.addEventListener("click", () => menu.remove(), { once: true }));
  }
  async function move(conv, pid) {
    try {
      const updated = await api(`/api/conversations/${conv.id}/project`, { method: "POST", body: { project: pid } });
      if (A.state.conv && A.state.conv.id === conv.id) { A.state.conv.project = updated.project; header(A.state.conv); }
      toast(pid ? `Moved to ${projectNames[pid] || "the project"}.` : "Removed from the project.");
      A.refreshList();
    } catch (err) { toast(err.message); }
  }

  function decorateChat(a, c) {
    if (c.kind === "code") a.insertBefore(h(`<span class="chat-kind" title="Code session">${A.svg("i-code")}</span>`), a.lastElementChild);
    else if (c.project) a.insertBefore(h(`<span class="chat-kind" title="In a project">${A.svg("i-projects")}</span>`), a.lastElementChild);
  }

  // ==========================================================================
  // Code
  // ==========================================================================
  async function codePage() {
    hub.innerHTML = "";
    const page = h(`<div class="hub-page">
      <header class="hub-head"><div><h1>Code</h1><p class="hub-sub">Sessions where Corvis works in a repo: he reads, edits, runs and tests code, and every change is tracked.</p></div></header>
      <form class="hub-card code-new">
        <textarea rows="3" placeholder="Describe a coding task, e.g. 'Add a /health endpoint and a test for it'" aria-label="Coding task" required></textarea>
        <div class="code-new-row">
          <label class="folder-pick">${A.svg("i-folder")}<input list="code-folders" spellcheck="false" placeholder="Repo folder" aria-label="Repo folder"></label>
          <datalist id="code-folders"></datalist>
          <label class="check"><input type="checkbox" checked> Work on a new branch</label>
          <button class="btn primary" type="submit">Start session</button>
        </div>
      </form>
      <h2 class="hub-h2">Sessions</h2>
      <ul class="session-list"></ul></div>`);
    hub.appendChild(page);
    const form = $(".code-new", page), folder = $(".folder-pick input", page);
    const folders = [...new Set([A.state.info && A.state.info.default_workspace, ...A.state.convs.filter((c) => c.mode !== "self").map((c) => c.workspace)].filter(Boolean))];
    $("#code-folders").innerHTML = folders.map((f) => `<option value="${esc(f)}"></option>`).join("");
    folder.value = folders[1] || folders[0] || "";
    const box = form.querySelector("textarea");
    box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !A.isPhone()) { e.preventDefault(); form.requestSubmit(); } });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = box.value.trim();
      if (!text) return;
      try {
        const conv = await api("/api/code/sessions", { method: "POST", body: { folder: folder.value.trim(), prompt: text, branch: form.querySelector("[type=checkbox]").checked } });
        if (conv.code && conv.code.note) toast(conv.code.note, 7000);
        await startChat(conv.id, text);
        A.refreshList();
      } catch (err) { toast(err.message, 7000); }
    });
    async function draw() {
      const d = await api("/api/code/sessions");
      const ul = $(".session-list", page); ul.innerHTML = "";
      if (!d.sessions.length) ul.appendChild(h(`<li class="hub-empty">No sessions yet. Describe a task above to start one.</li>`));
      for (const s of d.sessions) {
        const code = s.code || {}, st = s.stat || {};
        const status = s.waiting ? ["wait", "Needs your OK"] : s.running ? ["run", "Working"] : ["idle", "Idle"];
        const li = h(`<li><a href="#/c/${s.id}">
          <div class="sess-top"><b></b><span class="pill ${status[0]}">${status[1]}</span></div>
          <div class="sess-meta">${A.svg("i-folder")}<span class="repo"></span>${code.branch ? `${A.svg("i-branch")}<span class="branch"></span>` : ""}
            ${code.git ? `<span class="diffstat"><i class="add">+${st.added}</i> <i class="del">−${st.removed}</i> · ${st.files} file${st.files === 1 ? "" : "s"}</span>` : `<span class="hint">not tracked</span>`}</div>
          <p class="sess-last"></p><small>${ago(s.updated)}</small></a></li>`);
        $("b", li).textContent = s.title;
        $(".repo", li).textContent = code.repo || A.shortPath(s.workspace);
        if (code.branch) $(".branch", li).textContent = code.branch;
        $(".sess-last", li).textContent = s.last || "";
        li.firstElementChild.addEventListener("click", (e) => { e.preventDefault(); A.navigate(`#/c/${s.id}`); });
        ul.appendChild(li);
      }
    }
    await draw();
    every(5000, () => document.body.contains(page) && draw().catch(() => {}));
  }

  async function refreshChangeChip(conv, chip) {
    try {
      const d = await api(`/api/code/sessions/${conv.id}/diff`);
      if (!document.body.contains(chip)) return;
      $("span", chip).innerHTML = d.git ? `Changes <i class="add">+${d.added}</i> <i class="del">−${d.removed}</i>` : "Changes";
      if (panel.dataset.kind === "changes" && panel.dataset.id === conv.id) drawChanges(conv, d);
    } catch (_) { /* offline */ }
  }
  setInterval(() => {   // keep the Changes count fresh while Corvis works in a code session
    const chip = $(".hub-chip.changes");
    if (chip && A.state.conv && A.state.conv.kind === "code" && (A.state.running || panel.dataset.kind === "changes") && !document.hidden) {
      refreshChangeChip(A.state.conv, chip);
    }
  }, 4000);

  async function openChanges(conv) {
    openPanel(`<p class="hub-loading">Loading changes…</p>`, "changes", conv.id);
    try { drawChanges(conv, await api(`/api/code/sessions/${conv.id}/diff`)); }
    catch (err) { toast(err.message); }
  }
  function drawChanges(conv, d) {
    const openFiles = new Set([...panel.querySelectorAll("details[open]")].map((n) => n.dataset.path));
    panel.innerHTML = "";
    const code = conv.code || {};
    const head = h(`<header class="panel-head"><div><b>Changes</b><small class="panel-sub"></small></div>
      <button class="icon-btn" type="button" data-close aria-label="Close">${A.svg("i-close")}</button></header>`);
    $(".panel-sub", head).textContent = d.git ? `${code.repo || ""}${d.branch ? " · " + d.branch : ""} · +${d.added} −${d.removed} in ${d.files.length} file${d.files.length === 1 ? "" : "s"}` : "";
    panel.appendChild(head);
    const bodyEl = h(`<div class="panel-body"></div>`);
    if (!d.git) bodyEl.appendChild(h(`<p class="hub-empty"></p>`)).textContent = d.note || "Not a Git repository.";
    else if (!d.files.length) bodyEl.appendChild(h(`<p class="hub-empty">No changes yet.</p>`));
    for (const f of d.files) {
      const det = h(`<details class="diff-file" data-path="${esc(f.path)}"><summary><span class="st ${f.status}">${f.status[0].toUpperCase()}</span><code></code>
        <span class="diffstat"><i class="add">+${f.added}</i> <i class="del">−${f.removed}</i></span></summary><div class="diff"></div></details>`);
      $("code", det).textContent = f.path;
      det.open = openFiles.has(f.path) || d.files.length <= 3;
      const box = $(".diff", det);
      if (f.binary) box.appendChild(h(`<p class="hint">Binary file</p>`));
      for (const line of (f.patch || "").split("\n")) {
        if (/^(diff --git|index |--- |\+\+\+ |new file|similarity|rename )/.test(line) && !line.startsWith("new file\n")) continue;
        const cls = line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
        const row = document.createElement("div");
        row.className = `ln ${cls}`; row.textContent = line || " ";
        box.appendChild(row);
      }
      bodyEl.appendChild(det);
    }
    panel.appendChild(bodyEl);
    if (d.git && d.files.length) {
      const foot = h(`<form class="panel-foot"><input placeholder="Commit message" maxlength="300" aria-label="Commit message"><button class="btn primary">Commit</button></form>`);
      foot.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const r = await api(`/api/code/sessions/${conv.id}/commit`, { method: "POST", body: { message: foot.firstElementChild.value } });
          toast(r.result); openChanges(conv);
        } catch (err) { toast(err.message, 7000); }
      });
      panel.appendChild(foot);
    }
  }

  // ==========================================================================
  // Artifacts
  // ==========================================================================
  function artGrid(box, items) {
    box.innerHTML = "";
    for (const a of items) {
      const card = h(`<button type="button" class="art-card"><div class="art-thumb ${a.type}"></div>
        <div class="art-info"><b></b><small>${TYPE_LABEL[a.type]}${a.language ? " · " + esc(a.language) : ""} · ${a.versions > 1 ? `v${a.versions} · ` : ""}${ago(a.updated)}</small></div></button>`);
      $("b", card).textContent = a.title;
      const thumb = $(".art-thumb", card);
      if (a.type === "html" || a.type === "svg") {
        thumb.appendChild(h(`<iframe loading="lazy" tabindex="-1" aria-hidden="true" sandbox="allow-scripts" src="/artifact-view/${a.id}"></iframe>`));
      } else {
        const pre = document.createElement("pre"); pre.textContent = a.preview; thumb.appendChild(pre);
      }
      card.addEventListener("click", () => openArtifact(a.id));
      box.appendChild(card);
    }
  }
  async function artifactsPage() {
    const d = await api("/api/artifacts");
    hub.innerHTML = "";
    const page = h(`<div class="hub-page">
      <header class="hub-head"><div><h1>Artifacts</h1><p class="hub-sub">Web pages, apps, documents, code and drawings Corvis made for you. Ask for one in any chat.</p></div></header>
      <div class="hub-filters"><input class="hub-search" type="search" placeholder="Search artifacts" aria-label="Search artifacts">
        <div class="seg" role="tablist"><button class="on" data-t="">All</button><button data-t="html">Web pages</button><button data-t="markdown">Documents</button><button data-t="code">Code</button><button data-t="svg">Drawings</button></div></div>
      <div class="art-grid"></div></div>`);
    hub.appendChild(page);
    let type = "", q = "";
    const draw = () => {
      const items = d.artifacts.filter((a) => (!type || a.type === type) && a.title.toLowerCase().includes(q.toLowerCase()));
      artGrid($(".art-grid", page), items);
      if (!items.length) $(".art-grid", page).appendChild(h(`<p class="hub-empty">${d.artifacts.length ? "Nothing matches." : "No artifacts yet. Try asking Corvis: “Make me a web page that…”"}</p>`));
    };
    $(".seg", page).addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      type = b.dataset.t; $(".seg", page).querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); draw();
    });
    $(".hub-search", page).addEventListener("input", (e) => { q = e.target.value; draw(); });
    draw();
  }
  async function artifactPage(aid) {
    hub.innerHTML = `<div class="hub-page wide"><a class="hub-back" href="#/artifacts">‹ All artifacts</a><div class="artifact-full"></div></div>`;
    $(".hub-back", hub).addEventListener("click", (e) => { e.preventDefault(); A.navigate("#/artifacts"); });
    await renderArtifact($(".artifact-full", hub), aid, { full: true });
  }

  // the viewer, used by the side panel and the full page
  async function renderArtifact(box, aid, opts = {}) {
    let a;
    try { a = await api(`/api/artifacts/${aid}`); }
    catch (err) { box.innerHTML = `<p class="hub-empty">${esc(err.message)}</p>`; return; }
    let v = opts.version || a.versions.length, mode = (a.type === "html" || a.type === "svg") ? "preview" : "doc";
    box.innerHTML = "";
    box.dataset.id = a.id;
    const head = h(`<header class="panel-head art-head">
      <div class="art-title"><b></b><small></small></div>
      <div class="art-tools">
        <select aria-label="Version"></select>
        ${a.type === "html" || a.type === "svg" ? `<div class="seg small"><button data-m="preview">Preview</button><button data-m="code">Code</button></div>` : ""}
        <button class="icon-btn" type="button" data-copy title="Copy" aria-label="Copy">${A.svg("i-copy")}</button>
        <a class="icon-btn" data-dl title="Download" aria-label="Download">${A.svg("i-download")}</a>
        ${opts.full ? `<button class="icon-btn" type="button" data-del title="Delete" aria-label="Delete">${A.svg("i-trash")}</button>`
                    : `<a class="icon-btn" href="#/artifacts/${a.id}" data-full title="Open full page" aria-label="Open full page">${A.svg("i-artifacts")}</a>
                       <button class="icon-btn" type="button" data-close aria-label="Close">${A.svg("i-close")}</button>`}
      </div></header>`);
    $(".art-title b", head).textContent = a.title;
    $(".art-title small", head).textContent = `${TYPE_LABEL[a.type]}${a.language ? " · " + a.language : ""}` + (a.conversation_title ? ` · from “${a.conversation_title}”` : "");
    const sel = $("select", head);
    sel.innerHTML = a.versions.map((x, i) => `<option value="${i + 1}">v${i + 1} · ${esc(x.note || "")}</option>`).join("");
    box.appendChild(head);
    const view = h(`<div class="art-view"></div>`);
    box.appendChild(view);
    if (opts.full && a.conversation_id) {
      const link = h(`<p class="hint art-from"><a href="#/c/${a.conversation_id}">Open the chat it came from</a> · ask Corvis there to change it.</p>`);
      link.firstElementChild.addEventListener("click", (e) => { e.preventDefault(); A.navigate(`#/c/${a.conversation_id}`); });
      box.appendChild(link);
    }
    function draw() {
      sel.value = String(v);
      head.querySelectorAll("[data-m]").forEach((b) => b.classList.toggle("on", b.dataset.m === mode));
      $("[data-dl]", head).href = `/api/artifacts/${a.id}/download?v=${v}`;
      const content = a.versions[v - 1].content;
      view.innerHTML = "";
      if (mode === "preview") {
        // A sandboxed frame with its own (opaque) origin: the page can run scripts but can't
        // reach Corvis, your files or the network.
        view.appendChild(h(`<iframe class="art-frame" title="Artifact preview" sandbox="allow-scripts allow-forms allow-modals allow-popups allow-pointer-lock" src="/artifact-view/${a.id}?v=${v}"></iframe>`));
      } else if (a.type === "markdown") {
        view.appendChild(h(`<div class="art-doc content">${md.render(content)}</div>`));
      } else {
        const pre = h(`<pre class="art-code"><code></code></pre>`);
        $("code", pre).textContent = content;
        view.appendChild(pre);
      }
    }
    sel.addEventListener("change", () => { v = Number(sel.value); draw(); });
    head.querySelectorAll("[data-m]").forEach((b) => b.addEventListener("click", () => { mode = b.dataset.m; draw(); }));
    $("[data-copy]", head).addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(a.versions[v - 1].content); toast("Copied."); } catch (_) { toast("Couldn't copy here."); }
    });
    const full = $("[data-full]", head);
    if (full) full.addEventListener("click", (e) => { e.preventDefault(); closePanel(); A.navigate(`#/artifacts/${a.id}`); });
    const del = $("[data-del]", head);
    if (del) del.addEventListener("click", async () => {
      if (!confirm(`Delete "${a.title}" and all its versions?`)) return;
      await api(`/api/artifacts/${a.id}`, { method: "DELETE" }); A.navigate("#/artifacts");
    });
    draw();
  }
  function openArtifact(aid, version) {
    openPanel("", "artifact", aid);
    renderArtifact(panel, aid, { version });
  }

  // cards in a reply, one per artifact Corvis made or changed
  async function cards(bodyEl, ids, justMade) {
    if (!bodyEl) return;
    let row = bodyEl.querySelector(":scope > .artifact-cards");
    if (!row) {
      row = h(`<div class="artifact-cards"></div>`);
      const content = bodyEl.querySelector(":scope > .content");
      bodyEl.insertBefore(row, content || null);
    }
    for (const id of ids) {
      let card = row.querySelector(`[data-id="${id}"]`);
      if (!card) {
        card = h(`<button type="button" class="artifact-card" data-id="${id}"><span class="ic">${A.svg("i-artifacts")}</span><span class="t"><b>Artifact</b><small>Click to open</small></span></button>`);
        card.addEventListener("click", () => openArtifact(id));
        row.appendChild(card);
      }
      api(`/api/artifacts/${id}`).then((a) => {
        $("b", card).textContent = a.title;
        $("small", card).textContent = `${TYPE_LABEL[a.type]} · ${a.versions.length > 1 ? `version ${a.versions.length}` : "click to open"}`;
      }).catch(() => { $("small", card).textContent = "Deleted"; card.disabled = true; });
    }
    if (justMade && !A.isPhone()) openArtifact(justMade);   // like Claude: it opens as it's made
  }

  // ---------- the side panel ----------
  function openPanel(html, kind = "", id = "") {
    panel.innerHTML = html;
    panel.dataset.kind = kind; panel.dataset.id = id; panel.dataset.at = location.hash;
    panel.hidden = false;
    app.classList.add("panel-open");
  }
  function closePanel() {
    panel.hidden = true; panel.innerHTML = "";
    panel.dataset.kind = ""; panel.dataset.id = ""; panel.dataset.at = "";
    app.classList.remove("panel-open");
  }
  panel.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) closePanel(); });

  // ==========================================================================
  // Scheduled
  // ==========================================================================
  async function scheduledPage() {
    hub.innerHTML = "";
    const page = h(`<div class="hub-page">
      <header class="hub-head"><div><h1>Scheduled</h1><p class="hub-sub">Tasks Corvis (or a bot) runs on a schedule, even while you're away. Results land in a chat.</p></div>
        <button class="btn primary" type="button" data-new>New task</button></header>
      <div class="sched-form-slot"></div>
      <p class="hint tz"></p>
      <ul class="task-list"></ul></div>`);
    hub.appendChild(page);
    let data;
    const open = new Set();
    async function load() { data = await api("/api/scheduled"); draw(); updateCount(data.tasks); }
    function draw() {
      $(".tz", page).textContent = `Times are in ${data.tz}.`;
      const ul = $(".task-list", page); ul.innerHTML = "";
      if (!data.tasks.length) ul.appendChild(h(`<li class="hub-empty">No scheduled tasks yet. Try “Every weekday at 8:00, summarise what's new in my repo”.</li>`));
      for (const t of data.tasks) {
        const last = t.runs[0];
        const li = h(`<li class="task ${t.enabled ? "" : "off"}">
          <div class="task-row">
            <label class="switch" title="${t.enabled ? "On" : "Off"}"><input type="checkbox" ${t.enabled ? "checked" : ""} aria-label="On or off"><i></i></label>
            <button class="task-main" type="button"><b></b><small></small></button>
            <span class="task-last">${last ? `<span class="pill ${last.status === "done" ? "ok" : last.status === "running" || last.status === "started" ? "run" : "bad"}">${esc(last.status)}</span>` : ""}</span>
          </div>
          <div class="task-detail" ${open.has(t.id) ? "" : "hidden"}></div></li>`);
        $("b", li).textContent = t.name;
        $("small", li).textContent = `${t.when} · ${t.bot_name}` + (t.enabled ? ` · next ${until(t.next_run)}` : t.schedule.every === "once" && t.last_run ? " · done" : " · paused");
        $(".switch input", li).addEventListener("change", async (e) => {
          try { await api(`/api/scheduled/${t.id}`, { method: "PATCH", body: { enabled: e.target.checked } }); }
          catch (err) { toast(err.message, 7000); }
          load();
        });
        $(".task-main", li).addEventListener("click", () => {
          open.has(t.id) ? open.delete(t.id) : open.add(t.id);
          const d = $(".task-detail", li); d.hidden = !open.has(t.id); if (!d.hidden) detail(d, t);
        });
        if (open.has(t.id)) detail($(".task-detail", li), t);
        ul.appendChild(li);
      }
    }
    function detail(box, t) {
      box.innerHTML = "";
      const top = h(`<div class="task-actions"><p class="task-prompt"></p><div>
        <button class="btn ghost" type="button" data-run>Run now</button>
        <button class="btn ghost" type="button" data-edit>Edit</button>
        <button class="btn ghost danger" type="button" data-del>Delete</button></div></div>`);
      $(".task-prompt", top).textContent = t.prompt;
      $("[data-run]", top).addEventListener("click", async () => {
        try { const r = await api(`/api/routines/${t.id}/run`, { method: "POST" }); toast(`Run ${r.status}.`); load(); }
        catch (err) { toast(err.message); }
      });
      $("[data-edit]", top).addEventListener("click", () => form(t));
      $("[data-del]", top).addEventListener("click", async () => {
        if (!confirm(`Delete the scheduled task "${t.name}"? Its chats stay.`)) return;
        await api(`/api/routines/${t.id}`, { method: "DELETE" }); open.delete(t.id); load();
      });
      box.appendChild(top);
      box.appendChild(h(`<h4>Runs</h4>`));
      const runs = h(`<ul class="run-list"></ul>`);
      if (!t.runs.length) runs.appendChild(h(`<li class="hint">No runs yet${t.enabled ? `. First one ${until(t.next_run)}.` : "."}</li>`));
      for (const r of t.runs) {
        const li = h(`<li><span class="pill ${r.status === "done" ? "ok" : r.status === "running" || r.status === "started" ? "run" : "bad"}"></span>
          <span class="when">${new Date(r.ts * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
          <span class="sum"></span>${r.conversation_id && r.status !== "chat deleted" ? `<a href="#/c/${r.conversation_id}">Open</a>` : ""}</li>`);
        $(".pill", li).textContent = r.status;
        $(".sum", li).textContent = r.summary || "";
        const a = $("a", li); if (a) a.addEventListener("click", (e) => { e.preventDefault(); A.navigate(a.getAttribute("href")); });
        runs.appendChild(li);
      }
      box.appendChild(runs);
    }
    function form(t) {
      const slot = $(".sched-form-slot", page);
      const s = t ? t.schedule : { every: "day", at: "09:00" };
      const today = new Date(Date.now() + 3600e3);
      const f = h(`<form class="hub-card sched-form">
        <h3>${t ? "Edit task" : "New scheduled task"}</h3>
        <label>Name<input name="name" maxlength="60" required placeholder="Morning repo summary"></label>
        <label>What should happen?<textarea name="prompt" rows="4" maxlength="4000" required placeholder="Check my repo for new commits and open issues, and summarise them in 5 bullets."></textarea></label>
        <div class="sched-grid">
          <label>Who<select name="bot"></select></label>
          <label>How often<select name="every">
            <option value="once">Once</option><option value="hours">Every few hours</option><option value="day">Every day</option>
            <option value="weekday">Weekdays</option><option value="week">Every week</option></select></label>
          <label data-f="date">Date<input name="date" type="date"></label>
          <label data-f="day">Day<select name="day"><option value="mon">Monday</option><option value="tue">Tuesday</option><option value="wed">Wednesday</option><option value="thu">Thursday</option><option value="fri">Friday</option><option value="sat">Saturday</option><option value="sun">Sunday</option></select></label>
          <label data-f="at">Time<input name="at" type="time"></label>
          <label data-f="hours">Every (hours)<input name="hours" type="number" min="1" max="168"></label>
        </div>
        <label class="check"><input name="fresh" type="checkbox"> Start a new chat for each run (otherwise every run continues one chat)</label>
        <div class="row-end"><button class="btn ghost" type="button" data-cancel>Cancel</button><button class="btn primary">${t ? "Save" : "Create task"}</button></div>
      </form>`);
      f.bot.innerHTML = A.bots().map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
      f.name.value = t ? t.name : ""; f.prompt.value = t ? t.prompt : ""; f.bot.value = t ? t.bot : "corvis";
      f.every.value = s.every; f.at.value = s.at || "09:00"; f.day.value = s.day || "mon"; f.hours.value = s.hours || 4;
      f.date.value = s.date || today.toISOString().slice(0, 10); f.fresh.checked = !!(t && t.fresh);
      const sync = () => {
        const e = f.every.value;
        f.querySelector("[data-f=date]").hidden = e !== "once";
        f.querySelector("[data-f=day]").hidden = e !== "week";
        f.querySelector("[data-f=at]").hidden = e === "hours";
        f.querySelector("[data-f=hours]").hidden = e !== "hours";
      };
      f.every.addEventListener("change", sync); sync();
      $("[data-cancel]", f).addEventListener("click", () => { slot.innerHTML = ""; });
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        const ev = f.every.value;
        const schedule = ev === "hours" ? { every: ev, hours: Number(f.hours.value) } : { every: ev, at: f.at.value, day: f.day.value, date: f.date.value };
        const bodyData = { name: f.name.value, prompt: f.prompt.value, bot: f.bot.value, schedule, fresh: f.fresh.checked, tz: Intl.DateTimeFormat().resolvedOptions().timeZone };
        try {
          if (t) await api(`/api/scheduled/${t.id}`, { method: "PATCH", body: { ...bodyData, enabled: true } });
          else await api("/api/scheduled", { method: "POST", body: bodyData });
          slot.innerHTML = ""; load();
          toast(t ? "Saved." : "Scheduled.");
        } catch (err) { toast(err.message, 7000); }
      });
      slot.innerHTML = ""; slot.appendChild(f); f.name.focus();
    }
    $("[data-new]", page).addEventListener("click", () => form(null));
    await load();
    every(10000, () => document.body.contains(page) && !$(".sched-form", page) && load().catch(() => {}));
  }
  function updateCount(tasks) {
    const on = tasks.filter((t) => t.enabled).length;
    $("#scheduled-count").textContent = on ? `${on} on` : "";
  }
  api("/api/scheduled").then((d) => updateCount(d.tasks)).catch(() => {});

  function register(name, label, page) { NAMES[name] = label; extraPages[name] = page; }

  window.CorvisHub = { route, header, cards, decorateChat, openArtifact, register,
    util: { h, ago, every, openPanel, closePanel, startChat, hub } };
})();
