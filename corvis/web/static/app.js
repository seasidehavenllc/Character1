/* Corvis chat app. Talks to the local Corvis server; no internet needed. */
(function () {
  "use strict";

  const md = window.CorvisMarkdown;
  const $ = (sel) => document.querySelector(sel);
  const el = {
    app: $("#app"), sidebar: $("#sidebar"), chatList: $("#chat-list"), newChat: $("#new-chat"),
    modelStatus: $("#model-status"), restart: $("#restart"), scrim: $("#scrim"),
    sidebarOpen: $("#sidebar-open"), sidebarClose: $("#sidebar-close"),
    title: $("#chat-title"), folderChip: $("#folder-chip"), folderLabel: $("#folder-label"),
    thread: $("#thread"), composer: $("#composer"), input: $("#input"), send: $("#send"),
    note: $("#composer-note"), dialog: $("#folder-dialog"), folderForm: $("#folder-form"),
    folderField: $("#folder-field"), folderInput: $("#folder-input"), folderHint: $("#folder-hint"),
    recent: $("#recent-folders"), folderOk: $("#folder-ok"), folderCancel: $("#folder-cancel"),
    toast: $("#toast"),
    memoryOpen: $("#memory-open"), memoryDialog: $("#memory-dialog"), memoryClose: $("#memory-close"),
    facts: $("#facts"), factForm: $("#fact-form"), factInput: $("#fact-input"),
    signOut: $("#sign-out"),
    filesOpen: $("#files-open"), filesDialog: $("#files-dialog"), filesClose: $("#files-close"),
    filesBack: $("#files-back"), filesCrumbs: $("#files-crumbs"), fileList: $("#file-list"),
    filePreview: $("#file-preview"), filesUse: $("#files-use"), filesNote: $("#files-note"),
    filesFoot: $("#files-foot"), folderBrowse: $("#folder-browse"),
    mic: $("#mic"), voiceOpen: $("#voice-open"), voiceDialog: $("#voice-dialog"),
    voiceClose: $("#voice-close"), speakToggle: $("#speak-toggle"), voiceSelect: $("#voice-select"),
    voiceRate: $("#voice-rate"), voiceTest: $("#voice-test"), voiceAutosend: $("#voice-autosend"),
    voiceNote: $("#voice-note"),
    tray: $("#tray"), attach: $("#attach"), fileInput: $("#file-input"), dropHint: $("#drop-hint"),
    botList: $("#bot-list"), botAdd: $("#bot-add"), botDialog: $("#bot-dialog"), botForm: $("#bot-form"),
    botTitle: $("#bot-title"), botName: $("#bot-name"), botJob: $("#bot-job"), botAbilities: $("#bot-abilities"),
    botColors: $("#bot-colors"), botDelete: $("#bot-delete"), botCancel: $("#bot-cancel"), botSave: $("#bot-save"),
    mentions: $("#mentions"),
    routinesOpen: $("#routines-open"), routinesCount: $("#routines-count"), routinesDialog: $("#routines-dialog"),
    routines: $("#routines"), routinesTz: $("#routines-tz"), routinesClose: $("#routines-close"),
    routineNew: $("#routine-new"), routineForm: $("#routine-form"),
    computerOpen: $("#computer-open"), computerDialog: $("#computer-dialog"), computerClose: $("#computer-close"),
    cpTab: $("#cp-tab"), cpGo: $("#cp-go"), cpUrl: $("#cp-url"), cpBack: $("#cp-back"), cpImg: $("#cp-img"),
    cpEmpty: $("#cp-empty"), cpType: $("#cp-type"), cpText: $("#cp-text"),
  };

  const state = {
    info: null,
    convs: [],
    conv: null,                                   // the open chat, or null for a new one
    draft: { mode: "project", workspace: null, bot: "corvis" },  // settings for a chat not yet started
    running: false,
    stream: null,                                 // AbortController for the live event stream
    live: null,                                   // the reply being built right now
    createFolder: false,
    loading: false,                               // true while a chat is being opened
    pending: [],                                  // files attached to the next message
    warnedNoVision: false,
  };
  const MAX_FILES = 10;

  const TOOL_LABELS = {
    read_file: "Read", write_file: "Wrote", edit_file: "Edited", delete_file: "Deleted",
    list_dir: "Looked through", find_files: "Searched for files", grep: "Searched for",
    run_command: "Ran", git_status: "Checked Git status", git_diff: "Reviewed changes",
    git_log: "Read Git history", git_commit: "Committed", update_plan: "Updated the plan",
    current_model: "Checked which model is running",
    search_chats: "Searched earlier chats for", read_chat: "Opened an earlier chat",
    remember: "Remembered", forget: "Forgot",
    web_search: "Searched the web for", fetch_page: "Read",
    look_at_image: "Looked at", read_attachment: "Read attachment", save_attachment: "Saved attachment",
    browser_open: "Opened", browser_read: "Read the page", browser_click: "Clicked", browser_type: "Typed into",
    browser_press: "Pressed", browser_scroll: "Scrolled", create_routine: "Set up a routine",
    list_routines: "Checked routines", delete_routine: "Deleted a routine",
    list_blueprints: "Checked blueprints", open_blueprints: "Opened blueprints", show_blueprint: "Read blueprint",
    create_blueprint: "Designed blueprint", edit_blueprint: "Edited blueprint", delete_blueprint: "Deleted blueprint",
    test_blueprint: "Tested blueprint",
  };
  const DETAIL_ARG = {
    read_file: "path", write_file: "path", edit_file: "path", delete_file: "path",
    list_dir: "path", find_files: "pattern", grep: "pattern", run_command: "command",
    git_commit: "message", git_diff: "path",
    search_chats: "query", read_chat: "chat_id", remember: "fact", forget: "memory_id",
    web_search: "query", fetch_page: "url",
    look_at_image: "attachment", read_attachment: "attachment", save_attachment: "path",
    browser_open: "url", browser_press: "key_name", browser_scroll: "direction", create_routine: "name",
    open_blueprints: "blueprint", show_blueprint: "blueprint", create_blueprint: "name", edit_blueprint: "blueprint",
    delete_blueprint: "blueprint", test_blueprint: "situation",
  };
  // "Corvis, open blueprints" goes straight to the hologram workshop without asking the model.
  const OPEN_BLUEPRINTS = /^(?:hey\s+)?(?:corvis[,!.]?\s+)?(?:please\s+)?(?:open|show|launch|bring up|pull up)\s+(?:(?:the|my)\s+)?blue\s?prints?(?:\s+(?:page|workshop|library))?(?:\s+please)?[.!]?$/i;

  // ---------- helpers ----------
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const isPhone = () => window.matchMedia("(max-width: 820px)").matches;
  const svg = (id, cls = "") => `<svg class="${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;

  // ---------- bots ----------
  const LEAD = "corvis";
  function bots() { return (state.info && state.info.bots) || [{ id: LEAD, name: "Corvis", lead: true, color: "#6f8cff" }]; }
  function botById(id) { return bots().find((b) => b.id === (id || LEAD)) || null; }
  function avatar(bot, cls = "") {
    const span = document.createElement("span");
    span.className = `bot-av ${cls}` + (!bot || bot.lead ? " lead" : "");
    span.setAttribute("aria-hidden", "true");
    if (!bot || bot.lead) span.innerHTML = `<svg><use href="#mark"/></svg>`;
    else {
      span.style.setProperty("--c", bot.color || "#6f8cff");
      span.textContent = (bot.name.trim()[0] || "?").toUpperCase();
    }
    return span;
  }
  function chatBot() { return botById(state.conv ? state.conv.bot : state.draft.bot) || botById(LEAD); }

  async function api(path, opts = {}) {
    const headers = { "X-Corvis": "1" };
    if (opts.body) headers["Content-Type"] = "application/json";
    const res = await fetch(path, {
      method: opts.method || "GET", headers, signal: opts.signal,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (res.status === 401 && data.login) {  // signed out (or session expired) on this device
      location.replace("/login");
      throw new Error("Sign in first.");
    }
    if (!res.ok) throw new Error(data.error || `Corvis answered with an error (${res.status}).`);
    return data;
  }

  let toastTimer;
  function toast(text, ms = 4500) {
    el.toast.textContent = text;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.toast.hidden = true), ms);
  }

  function shortPath(p) {
    if (!p) return "Choose folder";
    const parts = p.split(/[\\/]/).filter(Boolean);
    return parts.length <= 2 ? p : "…" + (p.includes("\\") ? "\\" : "/") + parts.slice(-2).join(p.includes("\\") ? "\\" : "/");
  }

  function greeting() {
    const h = new Date().getHours();
    return h < 5 ? "Working late." : h < 12 ? "Good morning." : h < 18 ? "Good afternoon." : "Good evening.";
  }

  function scrollToEnd(force) {
    const t = el.thread;
    const near = t.scrollHeight - t.scrollTop - t.clientHeight < 160;
    if (force || near) t.scrollTop = t.scrollHeight;
  }

  // ---------- model status ----------
  async function loadInfo() {
    try {
      state.info = await api("/api/info");
    } catch (_) {
      setModelStatus("offline", "Corvis isn't responding");
      return;
    }
    el.memoryOpen.hidden = state.info.memory === false;
    el.computerOpen.hidden = !state.info.computer;
    renderBots();
    el.signOut.hidden = !state.info.remote;
    renderPcStatus();
    if (state.info.notice) toast(state.info.notice, 15000);
    el.filesOpen.hidden = !state.info.pc_access;
    setupMic();
    el.folderBrowse.hidden = !state.info.pc_access;
    const m = state.info.model;
    if (!m.online) setModelStatus("offline", "Model offline");
    else if (m.installed === false) setModelStatus("offline", `${m.model} not installed`);
    else setModelStatus("online", m.model);
    if (!state.conv && !state.draft.workspace) {
      state.draft.workspace = state.info.default_workspace;
      renderHeader();
    }
  }

  function renderPcStatus() {
    const pcBtn = document.getElementById("pc-status");
    const nodes = (state.info && state.info.nodes) || [];
    pcBtn.hidden = !nodes.length;
    if (!nodes.length) return;
    const live = nodes.filter((n) => n.online);
    const recent = [...nodes].sort((a, b) => (b.last_seen || 0) - (a.last_seen || 0))[0];
    pcBtn.className = "pc-status " + (live.length ? "online" : "offline");
    pcBtn.querySelector(".pc-label").textContent = live.length
      ? `${live[0].name}: connected` : `${recent.name}: offline`;
    pcBtn.onclick = () => toast(live.length
      ? "Corvis can use your PC's files, apps and games right now."
      : "Your PC isn't connected. Turn it on and start Corvis Node (Start_Corvis_Node.bat). Everything else still works.", 7000);
  }

  function setModelStatus(kind, label) {
    el.modelStatus.className = `model-status ${kind}`;
    el.modelStatus.querySelector(".model-label").textContent = label;
  }

  el.modelStatus.addEventListener("click", () => {
    const i = state.info;
    if (!i) return toast("Corvis's server isn't responding. Check the Corvis window is still open.");
    const m = i.model;
    if (m.cloud) {
      if (!m.online) toast(`Corvis can't reach his cloud brain at ${m.server}. It's usually brief; this updates by itself.`, 7000);
      else if (m.installed === false) toast(`The model "${m.model}" isn't offered there any more. Pick another by running the hub installer again.`, 8000);
      else toast(`Corvis ${i.version} is thinking with ${m.model}, in the cloud.`);
    } else if (!m.online) toast(`Corvis can't reach the model server at ${m.server}. Start Ollama; this updates by itself.`, 7000);
    else if (m.installed === false) toast(`The model "${m.model}" isn't downloaded. In a terminal, run: ollama pull ${m.model}`, 8000);
    else toast(`Corvis ${i.version} is thinking with ${m.model}, running on your PC.`);
  });

  // ---------- sidebar ----------
  async function refreshList() {
    try {
      state.convs = (await api("/api/conversations")).conversations;
    } catch (_) { return; }
    renderList();
  }

  function groupName(ts) {
    const d = new Date(ts * 1000), now = new Date();
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 86400000);
    return diff <= 0 ? "Today" : diff === 1 ? "Yesterday" : diff < 7 ? "Previous 7 days" : "Older";
  }

  function renderList() {
    el.chatList.innerHTML = "";
    if (!state.convs.length) {
      el.chatList.innerHTML = `<p class="chat-empty">Your chats will show up here.</p>`;
      return;
    }
    const groups = new Map();
    for (const c of state.convs) {
      const g = groupName(c.updated);
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(c);
    }
    for (const [name, convs] of groups) {
      const section = document.createElement("section");
      section.className = "chat-group";
      section.innerHTML = `<h2>${name}</h2>`;
      for (const c of convs) {
        const item = document.createElement("div");
        item.className = "chat-item" + (state.conv && state.conv.id === c.id ? " active" : "") + (c.unread ? " unread" : "");
        const a = document.createElement("a");
        a.href = `#/c/${c.id}`;
        a.title = c.mode === "self" ? "Improving Corvis" : c.workspace;
        if (c.running) a.insertAdjacentHTML("beforeend", `<i class="running-dot" title="Working"></i>`);
        if (c.mode === "self") a.insertAdjacentHTML("beforeend", `<span class="self-tag">${svg("i-feather")}</span>`);
        else if (c.bot && c.bot !== LEAD && botById(c.bot)) a.appendChild(avatar(botById(c.bot)));
        const label = document.createElement("span");
        label.textContent = c.title;
        a.appendChild(label);
        if (c.unread) a.insertAdjacentHTML("beforeend", `<i class="unread-dot" title="New results"></i>`);
        const del = document.createElement("button");
        del.type = "button";
        del.className = "icon-btn delete";
        del.setAttribute("aria-label", `Delete "${c.title}"`);
        del.innerHTML = svg("i-trash");
        del.addEventListener("click", (e) => deleteChat(e, c, del));
        del.addEventListener("blur", () => resetDelete(del));
        item.append(a, del);
        section.appendChild(item);
      }
      el.chatList.appendChild(section);
    }
  }

  function resetDelete(btn) {
    btn.classList.remove("confirm");
    btn.innerHTML = svg("i-trash");
  }

  async function deleteChat(e, conv, btn) {
    e.preventDefault();
    if (!btn.classList.contains("confirm")) {
      btn.classList.add("confirm");
      btn.textContent = "Delete";
      return;
    }
    try {
      await api(`/api/conversations/${conv.id}`, { method: "DELETE" });
    } catch (err) { return toast(err.message); }
    if (state.conv && state.conv.id === conv.id) navigate("#/");
    refreshList();
  }

  function showSidebar(show) {
    if (isPhone()) {
      el.app.classList.toggle("sidebar-shown", show);
      el.scrim.hidden = !show;
    } else {
      el.app.classList.toggle("sidebar-hidden", !show);
    }
  }
  el.sidebarOpen.addEventListener("click", () => showSidebar(true));
  el.sidebarClose.addEventListener("click", () => showSidebar(false));
  el.scrim.addEventListener("click", () => showSidebar(false));
  // Switch chats right away (waiting for the browser's hashchange lets a fast
  // message land in the previous chat).
  function navigate(hash) {
    if (location.hash !== hash) history.pushState(null, "", hash);
    route();
  }
  el.newChat.addEventListener("click", () => {
    navigate("#/");
    if (isPhone()) showSidebar(false);
  });
  el.chatList.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    navigate(a.getAttribute("href"));
    if (isPhone()) showSidebar(false);
  });

  // ---------- header & composer ----------
  function current() {
    return state.conv ? { mode: state.conv.mode, workspace: state.conv.workspace }
                      : state.draft;
  }

  function renderHeader() {
    const c = current();
    el.title.textContent = state.conv ? state.conv.title : "New chat";
    const cb = chatBot();
    if (cb && !cb.lead) {
      el.title.prepend(avatar(cb, "tiny"), " ");
      el.input.placeholder = `Message ${cb.name}`;
    } else {
      el.input.placeholder = isPhone() ? "Ask Corvis anything" : "Ask Corvis to build, fix or explain something";
    }
    document.title = state.conv ? `${state.conv.title} | Corvis` : "Corvis";
    if (c.mode === "self") {
      el.folderLabel.textContent = "Corvis himself";
      el.folderChip.title = "Changes to Corvis go on a tested branch you approve";
      el.folderChip.classList.add("self");
      el.note.textContent = "Each request is made on its own branch, tested, and merged only if you approve.";
    } else {
      el.folderLabel.textContent = shortPath(c.workspace);
      el.folderChip.title = c.workspace || "";
      el.folderChip.classList.remove("self");
      el.note.textContent = c.workspace
        ? "Corvis can only change files in this folder. Anything risky asks you first."
        : "";
    }
    el.folderChip.querySelector("svg use").setAttribute("href", c.mode === "self" ? "#i-feather" : "#i-folder");
  }

  function updateSend() {
    if (state.running) {
      el.send.disabled = false;
      el.send.classList.add("stop");
      el.send.setAttribute("aria-label", "Stop");
      el.send.innerHTML = svg("i-stop");
    } else {
      const uploading = state.pending.some((p) => p.status === "uploading");
      const ready = state.pending.some((p) => p.status === "done");
      el.send.disabled = uploading || (!el.input.value.trim() && !ready);
      el.send.classList.remove("stop");
      el.send.setAttribute("aria-label", "Send");
      el.send.innerHTML = svg("i-send");
    }
  }

  function autosize() {
    el.input.style.height = "auto";
    el.input.style.height = el.input.scrollHeight + "px";
  }

  el.input.addEventListener("input", () => { autosize(); updateSend(); });
  el.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (!state.running) send();
    }
  });
  el.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    state.running ? stop() : send();
  });

  // rename
  el.title.addEventListener("click", () => {
    if (!state.conv) return;
    const input = document.createElement("input");
    input.value = state.conv.title;
    input.setAttribute("aria-label", "Chat name");
    el.title.replaceWith(input);
    input.focus();
    input.select();
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      input.replaceWith(el.title);
      const title = input.value.trim();
      if (save && title && title !== state.conv.title) {
        try {
          state.conv = { ...state.conv, ...(await api(`/api/conversations/${state.conv.id}`, { method: "PATCH", body: { title } })) };
          renderHeader();
          refreshList();
        } catch (err) { toast(err.message); }
      }
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") finish(true);
      if (e.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
  });

  // ---------- thread rendering ----------
  function renderWelcome() {
    const c = current();
    const ideas = c.mode === "self"
      ? ["Add a tool that runs Blender Python scripts in the background",
         "Make your replies shorter and more casual",
         "Add a tool that opens and closes apps on this PC"]
      : ["Explain how this project is organized",
         "Find and fix any failing tests",
         "Add a README that explains how to run this project"];
    const bot = chatBot();
    const others = bots().length > 1 && c.mode !== "self" && !state.conv;
    const job = bot && !bot.lead ? (bot.job || "").split("\n")[0] : "";
    el.thread.innerHTML = `
      <div class="welcome">
        <svg class="welcome-mark" aria-hidden="true"><use href="#mark"/></svg>
        <h2>${bot && !bot.lead ? md.escape(bot.name) : greeting()}</h2>
        <p class="job">${job ? md.escape(job) : c.mode === "self" ? "What should I improve about myself?" : "What are we building?"}</p>
        ${others ? `<div class="talk-to" role="radiogroup" aria-label="Talk to"></div>` : ""}
        ${bot && !bot.lead ? "" : `<div class="suggestions">${ideas.map((t) => `<button type="button" class="suggestion">${md.escape(t)}</button>`).join("")}</div>`}
      </div>`;
    if (bot && !bot.lead) {
      const mark = el.thread.querySelector(".welcome-mark");
      const av = avatar(bot, "big");
      av.style.width = av.style.height = "54px";
      av.style.fontSize = "24px";
      av.style.marginBottom = "18px";
      mark.replaceWith(av);
    }
    const row = el.thread.querySelector(".talk-to");
    if (row) {
      for (const b of bots()) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = b.id === (state.draft.bot || LEAD) ? "on" : "";
        btn.style.setProperty("--c", b.color || "");
        btn.append(avatar(b, "tiny"), b.name);
        btn.setAttribute("role", "radio");
        btn.setAttribute("aria-checked", String(btn.className === "on"));
        btn.addEventListener("click", () => { state.draft.bot = b.id; renderHeader(); renderWelcome(); renderBots(); el.input.focus(); });
        row.appendChild(btn);
      }
    }
    el.thread.querySelectorAll(".suggestion").forEach((b) =>
      b.addEventListener("click", () => {
        el.input.value = b.textContent;
        autosize(); updateSend(); el.input.focus();
      }));
  }

  function fileUrl(a) {
    return `/files/${a.id}/${encodeURIComponent(a.name)}`;
  }

  function humanSize(n) {
    return n < 1024 ? `${n} bytes` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
  }

  function userMessage(text, attachments, m) {
    const div = document.createElement("div");
    div.className = "msg user";
    if (m && (m.routine || (m.to && botById(m.to)))) {
      const to = document.createElement("div");
      to.className = "to";
      if (m.routine) { to.innerHTML = svg("i-clock"); to.append(`Routine: ${m.routine}`); }
      else to.append("To ", avatar(botById(m.to), "tiny"), botById(m.to).name);
      div.appendChild(to);
    }
    if (attachments && attachments.length) {
      const row = document.createElement("div");
      row.className = "sent-files";
      for (const a of attachments) {
        const link = document.createElement("a");
        link.href = fileUrl(a);
        link.target = "_blank";
        link.rel = "noopener";
        if (a.kind === "image") {
          link.className = "photo";
          link.title = a.name;
          const img = document.createElement("img");
          img.src = fileUrl(a);
          img.alt = a.name;
          img.loading = "lazy";
          link.appendChild(img);
        } else {
          link.className = "file";
          link.innerHTML = `${svg("i-file")}<span></span><small></small>`;
          link.querySelector("span").textContent = a.name;
          link.querySelector("small").textContent = humanSize(a.size);
        }
        row.appendChild(link);
      }
      div.appendChild(row);
    }
    if (text) {
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;
      div.appendChild(bubble);
    }
    return div;
  }

  function corvisShell(working, botId) {
    const div = document.createElement("div");
    div.className = "msg corvis" + (working ? " working" : "");
    div.innerHTML = `<div class="who"><svg class="avatar" aria-hidden="true"><use href="#mark"/></svg>` +
      `<span class="who-name"></span></div><div class="body"></div>`;
    div.querySelector(".who-name").textContent = (state.info && state.info.name) || "Corvis";
    setAuthor(div, botId);
    return div;
  }

  function setAuthor(div, botId) {
    const bot = botById(botId);
    if (!bot || bot.lead) return;
    div.classList.add("bot");
    div.querySelector(".who .avatar, .who .bot-av").replaceWith(avatar(bot));
    div.querySelector(".who-name").textContent = bot.name;
  }

  function newTrace(open) {
    const d = document.createElement("details");
    d.className = "trace";
    d.open = open;
    d.innerHTML = `<summary></summary><ol class="steps"></ol>`;
    return d;
  }

  function stepCount(trace) {
    return trace.querySelectorAll(".step:not(.thinking)").length;
  }

  function setTraceSummary(trace, working) {
    const n = stepCount(trace);
    trace.querySelector("summary").textContent = working
      ? (n ? `Working, ${n} step${n === 1 ? "" : "s"} so far` : "Working")
      : `Worked through ${n} step${n === 1 ? "" : "s"}`;
  }

  // Applies one event (live or saved) to a trace. Returns nothing; mutates the DOM.
  function applyStep(trace, ev, ctx) {
    const list = trace.querySelector(".steps");
    const li = document.createElement("li");
    const by = ev.bot && ev.kind !== "handoff" && ev.kind !== "handoff_done" && ev.kind !== "memory" && ev.kind !== "start"
      ? botById(ev.bot) : null;
    const mark = (node) => { if (by && !by.lead && node) { const s = avatar(by, "tiny by"); s.title = by.name; node.prepend(s); } };
    switch (ev.kind) {
      case "handoff": {
        const bot = botById(ev.bot) || { name: ev.bot_name, color: ev.color };
        li.className = "step handoff";
        li.dataset.handoff = ev.bot;
        const chip = document.createElement("span");
        chip.className = "handoff-chip";
        chip.style.setProperty("--c", bot.color || "");
        chip.append(avatar(bot, "tiny"));
        chip.insertAdjacentHTML("beforeend", `<span class="dots"><i></i><i></i><i></i></span><span class="lbl"></span>`);
        chip.querySelector(".lbl").textContent = `Looping in ${bot.name}`;
        li.innerHTML = `<div class="step-line"></div>`;
        li.firstChild.appendChild(chip);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "step-result expandable";
        btn.dataset.expand = "1";
        btn.textContent = ev.text.split("\n")[0];
        btn._full = ev.text;
        li.appendChild(btn);
        list.appendChild(li);
        break;
      }
      case "handoff_done": {
        const open = [...list.querySelectorAll(`.step.handoff[data-handoff="${CSS.escape(ev.bot || "")}"]`)].pop();
        if (open) { open.classList.add("done"); open.querySelector(".lbl").textContent = `Looped in ${ev.bot_name}`; }
        const bot = botById(ev.bot) || { name: ev.bot_name, color: ev.color };
        li.className = "step";
        li.innerHTML = `<div class="step-line"><span class="step-label"></span></div>`;
        li.querySelector(".step-label").textContent = `${bot.name} replied`;
        li.querySelector(".step-line").prepend(avatar(bot, "tiny by"));
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "step-result expandable";
        btn.dataset.expand = "1";
        btn.textContent = (ev.text || "").trim().split("\n")[0];
        btn._full = ev.text;
        li.appendChild(btn);
        list.appendChild(li);
        break;
      }
      case "memory": {
        const bot = ev.bot ? botById(ev.bot) || { name: ev.bot_name, color: "" } : null;
        li.className = "step memory";
        li.innerHTML = `<div class="step-line"><span class="memory-chip">Updated memory for <span class="tag"></span></span></div>`;
        const tag = li.querySelector(".tag");
        if (bot) { tag.style.setProperty("--c", bot.color || ""); tag.append(avatar(bot, "tiny"), bot.name); }
        else tag.textContent = "everyone";
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "step-result";
        btn.textContent = ev.text;
        li.appendChild(btn);
        list.appendChild(li);
        break;
      }
      case "thinking": {
        li.className = "step thinking";
        li.textContent = ev.text.length > 400 ? ev.text.slice(0, 400) + "…" : ev.text;
        mark(li);
        list.appendChild(li);
        break;
      }
      case "tool": {
        const name = ev.text.split(" ", 1)[0];
        const rest = ev.text.slice(name.length + 1);
        const key = DETAIL_ARG[name];
        let detail = "";
        if (key) {
          const m = rest.match(new RegExp(`(?:^|, )${key}=(.*?)(?=, \\w+=|$)`));
          detail = m ? m[1] : "";
        }
        if (name === "list_dir" && !detail) detail = "the project";
        if (name === "open_blueprints" && ctx.live && Date.now() / 1000 - (ev.ts || 0) < 20) {
          const target = detail.trim();
          setTimeout(() => { location.href = "/blueprints" + (target ? `?id=${encodeURIComponent(target)}` : ""); }, 600);
        }
        li.className = "step";
        li.dataset.tool = name;
        li.innerHTML = `<div class="step-line"><span class="step-label"></span><span class="step-detail"></span></div>`;
        li.querySelector(".step-label").textContent = TOOL_LABELS[name] || name.replace(/_/g, " ");
        li.querySelector(".step-detail").textContent = detail;
        if (name === "ask_bot" || name === "remember") { ctx.lastStep = null; break; }  // shown as a hand-off / memory line
        mark(li.querySelector(".step-line"));
        list.appendChild(li);
        ctx.lastStep = li;
        break;
      }
      case "result": {
        const step = ctx.lastStep;
        if (!step) break;
        const text = ev.text || "";
        const first = (text.trim().split("\n")[0] || "(no output)").slice(0, 200);
        if (/^(ERROR|Command not run|TIMEOUT|The owner declined)/.test(text) || /^exit code [1-9]/.test(text)) {
          step.classList.add("err");
        }
        if (step.dataset.tool === "update_plan" && text.startsWith("Plan:")) {
          const ul = document.createElement("ul");
          ul.className = "plan";
          for (const line of text.split("\n").slice(1)) {
            const m = line.match(/^\[(.)\]\s*(.*)$/);
            if (!m) continue;
            const status = m[1] === "x" ? "done" : m[1] === ">" ? "in_progress" : "pending";
            const item = document.createElement("li");
            item.className = status;
            item.innerHTML = `<span class="box">${status === "done" ? "✓" : status === "in_progress" ? "›" : "○"}</span><span></span>`;
            item.lastChild.textContent = m[2];
            ul.appendChild(item);
          }
          step.appendChild(ul);
        } else {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "step-result";
          btn.textContent = first;
          if (text.trim().includes("\n") || text.length > first.length) {
            btn.classList.add("expandable");
            btn.title = "Show full output";
            btn.dataset.expand = "1";
            btn._full = text;
          }
          step.appendChild(btn);
        }
        ctx.lastStep = null;
        break;
      }
      case "approval": {
        li.className = "step";
        li.innerHTML = `<div class="approval" data-approval="${md.escape(ev.id || "")}">
            <p></p><pre></pre>
            <div class="row">
              <button type="button" class="btn primary" data-allow="1">Allow</button>
              <button type="button" class="btn danger" data-allow="0">Deny</button>
            </div></div>`;
        li.querySelector("pre").textContent = ev.text.replace(/^Allow /, "");
        li.querySelector("p").textContent = `${ev.bot_name || (state.info && state.info.name) || "Corvis"} wants your OK`;
        list.appendChild(li);
        if (ctx.live) ctx.live.waiting = true;
        break;
      }
      case "approval_result": {
        const card = trace.querySelector(`[data-approval="${CSS.escape(ev.id || "")}"]`);
        if (card) settleApproval(card, ev.text);
        if (ctx.live) ctx.live.waiting = false;
        break;
      }
      case "recall": {
        const [titles, ...rest] = ev.text.split("\n");
        li.className = "step recall";
        li.innerHTML = `<div class="step-line"><span class="step-label">Remembered earlier chats</span></div>`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "step-result expandable";
        btn.title = "Show what Corvis recalled";
        btn.dataset.expand = "1";
        btn.textContent = titles;
        btn._full = rest.filter((l) => !l.startsWith("[Recalled")).join("\n").trim();
        li.appendChild(btn);
        list.appendChild(li);
        break;
      }
      case "report": {
        li.className = "step";
        li.innerHTML = `<div class="step-line"><span class="step-label">Self-edit report</span></div>`;
        const pre = document.createElement("pre");
        pre.className = "step-output report";
        pre.textContent = ev.text;
        li.appendChild(pre);
        list.appendChild(li);
        break;
      }
      case "error": {
        li.className = "step err";
        li.innerHTML = `<div class="step-line"><span class="step-label"></span></div>`;
        li.querySelector(".step-label").textContent = ev.text;
        list.appendChild(li);
        break;
      }
      default:
        break;
    }
  }

  function settleApproval(card, verdict) {
    card.classList.add("settled");
    card.querySelector("p").textContent = verdict === "allowed" ? "You allowed this" : "Not run";
    const row = card.querySelector(".row");
    row.innerHTML = `<span class="verdict ${verdict}">${verdict === "allowed" ? "Allowed" : "Denied"}</span>`;
  }

  function corvisMessage(m) {
    const div = corvisShell(false, m.bot);
    const body = div.querySelector(".body");
    const events = m.events || [];
    if (events.length) {
      const trace = newTrace(false);
      const ctx = {};
      for (const ev of events) applyStep(trace, ev, ctx);
      // Approvals in saved chats are already settled.
      trace.querySelectorAll(".approval:not(.settled)").forEach((c) => settleApproval(c, "denied"));
      if (stepCount(trace) || trace.querySelector(".thinking")) {
        setTraceSummary(trace, false);
        body.appendChild(trace);
      }
    }
    const content = document.createElement("div");
    content.className = "content";
    content.innerHTML = md.render(m.text || "");
    body.appendChild(content);
    if (m.status === "error" || m.status === "stopped") {
      const p = document.createElement("p");
      p.className = "msg-status" + (m.status === "error" ? " error" : "");
      p.textContent = m.status === "error" ? "Corvis hit a problem. Details are in the steps above." : "You stopped this reply.";
      body.appendChild(p);
    }
    if (/^Merged\./m.test(m.text || "")) {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `<button type="button" class="btn primary" data-restart>Restart Corvis to use the update</button>`;
      body.appendChild(actions);
    }
    return div;
  }

  function renderThread() {
    el.thread.innerHTML = "";
    const msgs = state.conv ? state.conv.messages : [];
    if (!msgs.length && !state.running) return renderWelcome();
    for (const m of msgs) el.thread.appendChild(m.role === "user" ? userMessage(m.text, m.attachments, m) : corvisMessage(m));
    scrollToEnd(true);
  }

  // thread-level clicks: copy code, expand outputs, approvals, restart
  el.thread.addEventListener("click", async (e) => {
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      const code = copy.closest(".code").querySelector("code").textContent;
      try { await navigator.clipboard.writeText(code); copy.textContent = "Copied"; }
      catch (_) { copy.textContent = "Select and copy"; }
      setTimeout(() => (copy.textContent = "Copy"), 1600);
      return;
    }
    const expand = e.target.closest("[data-expand]");
    if (expand) {
      const next = expand.nextElementSibling;
      if (next && next.classList.contains("step-output")) { next.remove(); return; }
      const pre = document.createElement("pre");
      pre.className = "step-output";
      pre.textContent = expand._full;
      expand.after(pre);
      return;
    }
    const decide = e.target.closest("[data-allow]");
    if (decide) {
      const card = decide.closest("[data-approval]");
      card.querySelectorAll("button").forEach((b) => (b.disabled = true));
      try {
        await api(`/api/approvals/${card.dataset.approval}`, { method: "POST", body: { allow: decide.dataset.allow === "1" } });
      } catch (err) {
        toast(err.message);
        card.querySelectorAll("button").forEach((b) => (b.disabled = false));
      }
      return;
    }
    if (e.target.closest("[data-restart]")) restartCorvis();
  });

  // ---------- live replies ----------
  function startLive(botId) {
    const div = corvisShell(true, botId);
    const body = div.querySelector(".body");
    const trace = newTrace(true);
    const working = document.createElement("div");
    working.className = "working-row";
    working.innerHTML = `<span class="pulse" aria-hidden="true"></span><span class="working-text">Thinking</span>`;
    const content = document.createElement("div");
    content.className = "content";
    body.append(trace, working, content);
    setTraceSummary(trace, true);
    el.thread.appendChild(div);
    state.live = { div, trace, working, content, ctx: {}, waiting: false };
    state.live.ctx.live = state.live;
    scrollToEnd(true);
  }

  function applyLive(ev) {
    const live = state.live;
    if (!live) return;
    if (ev.kind === "start") {
      if (ev.bot && !live.div.classList.contains("bot")) setAuthor(live.div, ev.bot);
      return;
    }
    if (ev.kind === "done" || ev.kind === "stopped") {
      live.content.innerHTML = md.render(ev.text || "");
    } else {
      applyStep(live.trace, ev, live.ctx);
    }
    setTraceSummary(live.trace, true);
    live.working.querySelector(".working-text").textContent =
      live.waiting ? "Waiting for your OK" : ev.kind === "handoff" ? `Looping in ${ev.bot_name}` : ev.kind === "tool" ? "Working" : "Thinking";
    scrollToEnd(false);
  }

  // Follows a reply live. Phones (iPhone especially) can freeze a connection without closing it
  // when the screen sleeps, you switch apps or the network changes. The server sends a keep-alive
  // every 15 s, so silence means the line is dead: reconnect and pick up where we left off.
  const STALL_MS = 30000;
  async function follow(convId, after) {
    if (state.stream) state.stream.abort();
    const ctrl = new AbortController();
    state.stream = ctrl;
    let seq = after;
    while (!ctrl.signal.aborted) {
      const req = new AbortController();
      const cancel = () => req.abort();
      ctrl.signal.addEventListener("abort", cancel, { once: true });
      let heard = Date.now();
      const dog = setInterval(() => { if (Date.now() - heard > (window.CORVIS_STALL_MS || STALL_MS)) req.abort(); }, 2000);
      // Backstop: something between the browser and Corvis (antivirus web shields, proxies) can
      // hold live events back while the line still looks alive. Ask directly now and then.
      const check = setInterval(async () => {
        try {
          const s = await api(`/api/conversations/${convId}/status`);
          if (!s.running || s.events > seq + 2) req.abort();  // finished, or we've fallen behind
        } catch (_) { /* restarting */ }
      }, window.CORVIS_CHECK_MS || 6000);
      state.reconnect = cancel;  // coming back to the page reconnects at once
      try {
        const res = await fetch(`/api/conversations/${convId}/events?after=${seq}`,
          { headers: { "X-Corvis": "1" }, signal: req.signal, cache: "no-store" });
        if (res.status === 401) { location.replace("/login"); return; }
        if (!res.ok) throw new Error(String(res.status));
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          heard = Date.now();
          buf += decoder.decode(value, { stream: true });
          let cut;
          while ((cut = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, cut);
            buf = buf.slice(cut + 2);
            const line = chunk.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            const ev = JSON.parse(line.slice(6));
            if (typeof ev.seq === "number") seq = ev.seq + 1;
            if (ev.kind === "end") return finishLive(convId);
            applyLive(ev);
          }
        }
      } catch (_) {
        /* dropped, frozen or reconnecting: handled below */
      } finally {
        clearInterval(dog);
        clearInterval(check);
        ctrl.signal.removeEventListener("abort", cancel);
      }
      if (ctrl.signal.aborted) return;
      // Safety net: if the reply finished while we were cut off, show it now.
      try {
        const c = await api(`/api/conversations/${convId}`);
        if (!c.running) { if (!ctrl.signal.aborted) finishLive(convId); return; }
      } catch (_) { /* Corvis restarting: keep trying */ }
      await sleep(1000);
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.stream && state.reconnect) state.reconnect();
  });
  window.addEventListener("pageshow", (e) => { if (e.persisted && state.reconnect) state.reconnect(); });
  window.addEventListener("online", () => { if (state.reconnect) state.reconnect(); });

  async function finishLive(convId) {
    state.running = false;
    state.live = null;
    state.stream = null;
    updateSend();
    if (state.conv && state.conv.id === convId) {
      try { state.conv = await api(`/api/conversations/${convId}`); } catch (_) { /* deleted */ }
      renderHeader();
      renderThread();
      const last = state.conv.messages[state.conv.messages.length - 1];
      if (state.speakNext === convId && last && last.role === "assistant") speak(last.text);
    }
    if (state.speakNext === convId) state.speakNext = null;
    refreshList();
  }

  // ---------- sending ----------
  async function send() {
    const text = el.input.value.trim();
    if (OPEN_BLUEPRINTS.test(text) && !state.pending.length) {
      el.input.value = "";
      location.href = "/blueprints";
      return;
    }
    const ready = state.pending.filter((p) => p.status === "done");
    if ((!text && !ready.length) || state.running || state.loading) return;
    if (state.pending.some((p) => p.status === "uploading")) return toast("Still uploading. One moment.");
    const c = current();
    if (!state.conv) {
      try {
        state.conv = await api("/api/conversations", { method: "POST", body: { mode: c.mode, workspace: c.workspace, bot: state.draft.bot || LEAD } });
      } catch (err) {
        toast(err.message, 7000);
        return openFolderDialog();
      }
      history.replaceState(null, "", `#/c/${state.conv.id}`);
    }
    if (!state.conv.messages.length) el.thread.innerHTML = "";
    const attachments = ready.map((p) => p.meta);
    const sentPending = state.pending;
    const toBot = mentionedBot(text);
    el.thread.appendChild(userMessage(text, attachments, toBot && toBot.id !== (state.conv.bot || LEAD) ? { to: toBot.id } : null));
    hideMentions();
    el.input.value = "";
    state.pending = [];
    renderTray();
    autosize();
    state.running = true;
    updateSend();
    try {
      await api(`/api/conversations/${state.conv.id}/messages`,
        { method: "POST", body: { text, attachments: attachments.map((a) => a.id) } });
    } catch (err) {
      state.running = false;
      updateSend();
      el.thread.lastElementChild.remove();
      el.input.value = text;
      state.pending = sentPending;
      renderTray();
      autosize(); updateSend();
      return toast(err.message, 6000);
    }
    if (!state.conv.messages.length) {
      const line = (text || "Sent " + attachments.map((a) => a.name).join(", ")).split(/\s+/).join(" ");
      state.conv.title = line.length <= 48 ? line : line.slice(0, 47).trimEnd() + "…";
    }
    state.conv.messages.push({ role: "user", text, attachments, to: toBot ? toBot.id : undefined });
    state.speakNext = state.conv.id;
    renderHeader();
    startLive(toBot ? toBot.id : state.conv.bot);
    follow(state.conv.id, 0);
    refreshList();
  }

  async function stop() {
    if (!state.conv) return;
    if (state.live) state.live.working.querySelector(".working-text").textContent = "Stopping after this step";
    try { await api(`/api/conversations/${state.conv.id}/stop`, { method: "POST" }); }
    catch (err) { toast(err.message); }
  }

  // ---------- routing ----------
  async function route() {
    const m = location.hash.match(/^#\/c\/([\w-]+)$/);
    if (state.stream) state.stream.abort();
    state.stream = null;
    state.live = null;
    state.running = false;
    if (!m) {
      state.conv = null;
      state.draft = { mode: "project", workspace: state.info ? state.info.default_workspace : null, bot: state.draft.bot || LEAD };
      renderHeader();
      renderWelcome();
      updateSend();
      renderList();
      el.input.focus();
      return;
    }
    state.conv = null;
    state.loading = true;
    let conv;
    try {
      conv = await api(`/api/conversations/${m[1]}`);
    } catch (_) {
      state.loading = false;
      toast("That chat no longer exists.");
      return navigate("#/");
    } finally {
      state.loading = false;
    }
    if (location.hash !== `#/c/${conv.id}`) return; // you switched again while it loaded
    state.conv = conv;
    renderHeader();
    renderList();
    state.running = !!state.conv.running;
    renderThread();
    updateSend();
    renderBots();
    if (conv.unread === undefined) refreshList();  // it was just marked read
    if (state.running) {
      startLive(state.conv.bot);
      follow(state.conv.id, 0); // replays everything so far, then keeps following
    }
  }
  window.addEventListener("hashchange", route);

  // ---------- folder dialog ----------
  function openFolderDialog() {
    if (state.conv && state.conv.messages.length) {
      return toast(state.conv.mode === "self"
        ? "This chat is for improving Corvis. Start a new chat to work on a project."
        : `This chat works in ${state.conv.workspace}. Start a new chat to work somewhere else.`, 6000);
    }
    const c = current();
    el.folderForm.mode.value = c.mode;
    el.folderInput.value = c.mode === "project" ? (c.workspace || "") : "";
    setHint("Paste the folder's path. In File Explorer: right-click the folder, then \"Copy as path\".");
    state.createFolder = false;
    el.folderOk.textContent = "Use this folder";
    const recent = (state.info && state.info.recent_workspaces) || [];
    el.recent.innerHTML = "";
    for (const p of recent) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = p;
      b.title = p;
      b.addEventListener("click", () => {
        el.folderInput.value = p;
        el.folderForm.mode.value = "project";
        syncDialog();
      });
      el.recent.appendChild(b);
    }
    syncDialog();
    el.dialog.showModal();
    if (c.mode === "project") el.folderInput.focus();
  }

  function setHint(text, kind = "") {
    el.folderHint.textContent = text;
    el.folderHint.className = "hint" + (kind ? " " + kind : "");
  }

  function syncDialog() {
    const self = el.folderForm.mode.value === "self";
    el.folderField.style.opacity = self ? ".45" : "1";
    el.folderInput.disabled = self;
    el.folderOk.textContent = self ? "Improve Corvis" : (state.createFolder ? "Create folder" : "Use this folder");
  }

  el.folderChip.addEventListener("click", openFolderDialog);
  el.folderForm.addEventListener("change", syncDialog);
  el.folderInput.addEventListener("input", () => { state.createFolder = false; syncDialog(); });
  el.folderCancel.addEventListener("click", () => el.dialog.close());

  el.folderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const mode = el.folderForm.mode.value;
    let workspace = null;
    if (mode === "project") {
      let res;
      try {
        res = await api("/api/folders/check", { method: "POST", body: { path: el.folderInput.value, create: state.createFolder } });
      } catch (err) { return setHint(err.message, "error"); }
      if (res.is_corvis) return setHint("That's Corvis's own folder. Choose \"Corvis himself\" below instead.", "error");
      if (res.is_file) return setHint("That's a file. Choose the folder that contains it.", "error");
      if (!res.exists) {
        state.createFolder = true;
        syncDialog();
        return setHint(`${res.path} doesn't exist yet. Press "Create folder" to make it.`, "error");
      }
      workspace = res.path;
    }
    if (state.conv && !state.conv.messages.length) {
      // An empty chat: just start fresh with the new settings.
      history.replaceState(null, "", "#/");
      state.conv = null;
    }
    state.draft = { mode, workspace };
    el.dialog.close();
    renderHeader();
    renderWelcome();
    el.input.focus();
  });

  // ---------- attachments ----------
  function renderTray() {
    el.tray.innerHTML = "";
    el.tray.hidden = !state.pending.length;
    for (const p of state.pending) {
      const chip = document.createElement("div");
      chip.className = `chip ${p.preview ? "image" : ""} ${p.status}`;
      chip.title = p.status === "failed" ? `${p.name}: ${p.error}` : p.name;
      if (p.preview) {
        const img = document.createElement("img");
        img.src = p.preview;
        img.alt = p.name;
        chip.appendChild(img);
      } else {
        chip.innerHTML = `${svg("i-file")}<span class="meta"><b></b><small></small></span>`;
        chip.querySelector("b").textContent = p.name;
        chip.querySelector("small").textContent = p.status === "failed" ? "Upload failed" : humanSize(p.size);
      }
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "remove";
      rm.setAttribute("aria-label", `Remove ${p.name}`);
      rm.innerHTML = svg("i-x");
      rm.addEventListener("click", () => {
        state.pending = state.pending.filter((x) => x !== p);
        if (p.preview) URL.revokeObjectURL(p.preview);
        renderTray();
        el.input.focus();
      });
      chip.appendChild(rm);
      el.tray.appendChild(chip);
    }
    updateSend();
  }

  async function upload(p) {
    try {
      const res = await fetch(`/api/uploads?name=${encodeURIComponent(p.name)}`, {
        method: "POST",
        headers: { "X-Corvis": "1", "Content-Type": p.file.type || "application/octet-stream" },
        body: p.file,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Upload failed (${res.status}).`);
      p.meta = data;
      p.status = "done";
      if (data.kind === "image" && state.info && !state.info.vision && !state.warnedNoVision) {
        state.warnedNoVision = true;
        toast("Corvis can't see photos yet. Add a vision model under vision: in config.yaml " +
              "(for example qwen2.5vl:7b). Files work fine.", 9000);
      }
    } catch (err) {
      p.status = "failed";
      p.error = err.message;
      toast(`${p.name}: ${err.message}`, 6000);
    }
    if (state.pending.includes(p)) renderTray();
  }

  function addFiles(list) {
    const files = Array.from(list || []);
    if (!files.length) return;
    const room = MAX_FILES - state.pending.length;
    if (files.length > room) toast(`You can attach up to ${MAX_FILES} files per message.`);
    const limitMb = (state.info && state.info.max_upload_mb) || 25;
    for (const file of files.slice(0, Math.max(0, room))) {
      if (file.size > limitMb * 1048576) { toast(`${file.name} is over ${limitMb} MB.`); continue; }
      let name = file.name || "file";
      if (/^image\.(png|jpe?g|gif|webp)$/i.test(name)) {  // pasted screenshots all arrive as "image.png"
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
        name = `screenshot-${stamp}.${name.split(".").pop()}`;
      }
      const isPhoto = /^image\/(png|jpe?g|gif|webp|bmp)$/.test(file.type);
      const p = { file, name, size: file.size, status: "uploading", preview: isPhoto ? URL.createObjectURL(file) : null };
      state.pending.push(p);
      upload(p);
    }
    renderTray();
    el.input.focus();
  }

  el.attach.addEventListener("click", () => el.fileInput.click());
  el.fileInput.addEventListener("change", () => { addFiles(el.fileInput.files); el.fileInput.value = ""; });
  el.input.addEventListener("paste", (e) => {
    const files = e.clipboardData && e.clipboardData.files;
    if (files && files.length) { e.preventDefault(); addFiles(files); }
  });
  let dragDepth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  window.addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; el.dropHint.hidden = false; } });
  window.addEventListener("dragleave", (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; el.dropHint.hidden = true; } });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    el.dropHint.hidden = true;
    addFiles(e.dataTransfer.files);
  });

  // ---------- files browser ----------
  const files = { mode: "browse", listing: null };
  const storage = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* private mode */ } },
  };

  function fmtDate(ts) {
    return ts ? new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
  }

  function iconFor(entry) {
    if (entry.is_dir) return entry.path === entry.name || /^[A-Z]:\\?$/i.test(entry.name) ? "i-drive" : "i-folder";
    return /\.(png|jpe?g|gif|webp|bmp)$/i.test(entry.name) ? "i-image" : "i-file";
  }

  async function openFiles(mode, startPath) {
    files.mode = mode;
    el.filesUse.textContent = mode === "pick" ? "Use this folder" : "Work in this folder";
    el.filesDialog.showModal();
    const start = startPath || storage.get("corvis.files.last") || "";
    await loadFolder(start, true);
  }

  async function loadFolder(path, fallbackToRoot) {
    closePreview();
    el.fileList.innerHTML = `<li class="empty">Loading…</li>`;
    let listing;
    try {
      listing = await api(`/api/pc/list?path=${encodeURIComponent(path || "")}`);
    } catch (err) {
      if (fallbackToRoot && path) return loadFolder("", false);
      el.fileList.innerHTML = "";
      const li = document.createElement("li");
      li.className = "problem";
      li.textContent = err.message;
      el.fileList.appendChild(li);
      return;
    }
    files.listing = listing;
    if (listing.path) storage.set("corvis.files.last", listing.path);
    renderCrumbs(listing);
    el.fileList.innerHTML = "";
    if (listing.parent !== null && listing.path) {
      el.fileList.appendChild(fileRow({ name: "..", path: listing.parent, is_dir: true, up: true }));
    }
    for (const entry of listing.entries) el.fileList.appendChild(fileRow(entry));
    if (!listing.entries.length) el.fileList.insertAdjacentHTML("beforeend", `<li class="empty">This folder is empty.</li>`);
    el.filesFoot.hidden = !listing.path;
    el.filesNote.textContent = listing.is_corvis ? "This is Corvis's own folder: he'll work on himself here, safely." : "";
    el.fileList.scrollTop = 0;
  }

  function renderCrumbs(listing) {
    el.filesCrumbs.innerHTML = "";
    const all = [{ name: "This PC", path: "" }, ...(listing.crumbs || [])];
    all.forEach((c, i) => {
      if (i) el.filesCrumbs.insertAdjacentHTML("beforeend", `<span class="sep" aria-hidden="true">›</span>`);
      const b = document.createElement("button");
      b.type = "button";
      const parts = c.name.split(/[\\/]/).filter(Boolean);
      b.textContent = c.name.length > 24 && parts.length > 1 ? "…" + parts[parts.length - 1] : c.name;
      b.title = c.path || "All drives";
      b.addEventListener("click", () => loadFolder(c.path));
      el.filesCrumbs.appendChild(b);
    });
    el.filesCrumbs.scrollLeft = el.filesCrumbs.scrollWidth;  // keep the current folder in view
  }

  function fileRow(entry) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = entry.is_dir ? "is-dir" : "";
    b.innerHTML = `${svg(entry.up ? "i-back" : iconFor(entry))}<span class="fname"></span><span class="fmeta"></span>`;
    b.querySelector(".fname").textContent = entry.up ? "Up one folder" : entry.name;
    b.querySelector(".fmeta").textContent = entry.is_dir ? "" : `${humanSize(entry.size || 0)} · ${fmtDate(entry.modified)}`;
    b.addEventListener("click", () => {
      if (entry.is_dir) return loadFolder(entry.path);
      el.fileList.querySelectorAll("button.active").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      preview(entry.path);
    });
    li.appendChild(b);
    return li;
  }

  async function preview(path) {
    const box = el.filePreview;
    box.hidden = false;
    box.parentElement.classList.add("previewing");
    el.filesBack.hidden = false;
    box.innerHTML = `<div class="preview-body"><p>Loading…</p></div>`;
    let info;
    try { info = await api(`/api/pc/preview?path=${encodeURIComponent(path)}`); }
    catch (err) { box.querySelector("p").textContent = err.message; return; }
    const raw = `/pcfile?path=${encodeURIComponent(info.path)}`;
    box.innerHTML = `
      <div class="preview-head"><b></b><small></small>
        <div class="preview-actions">
          <button type="button" class="btn primary" data-ask>Ask Corvis about this</button>
          <a class="btn" href="${raw}&download=1" download>Download</a>
        </div>
      </div>
      <div class="preview-body"></div>`;
    box.querySelector("b").textContent = info.name;
    box.querySelector("small").textContent = `${humanSize(info.size)} · ${fmtDate(info.modified)}`;
    const bodyEl = box.querySelector(".preview-body");
    if (info.kind === "image") {
      const img = document.createElement("img");
      img.src = raw;
      img.alt = info.name;
      bodyEl.appendChild(img);
    } else if (info.kind === "text") {
      const pre = document.createElement("pre");
      pre.textContent = info.text;
      bodyEl.appendChild(pre);
    } else {
      const p = document.createElement("p");
      p.textContent = info.note || "No preview for this kind of file. Download it, or ask Corvis about it.";
      bodyEl.appendChild(p);
    }
    box.querySelector("[data-ask]").addEventListener("click", () => {
      el.filesDialog.close();
      el.input.value = `Take a look at "${info.path}": ${el.input.value}`.trimEnd() + " ";
      autosize(); updateSend(); el.input.focus();
    });
  }

  function closePreview() {
    el.filePreview.hidden = true;
    el.filePreview.innerHTML = "";
    el.filePreview.parentElement.classList.remove("previewing");
    el.filesBack.hidden = true;
  }

  el.filesOpen.addEventListener("click", () => { openFiles("browse"); if (isPhone()) showSidebar(false); });
  el.folderBrowse.addEventListener("click", () => openFiles("pick", el.folderInput.value.trim()));
  el.filesClose.addEventListener("click", () => el.filesDialog.close());
  el.filesBack.addEventListener("click", closePreview);
  el.filesUse.addEventListener("click", () => {
    const listing = files.listing;
    if (!listing || !listing.path) return;
    el.filesDialog.close();
    if (files.mode === "pick") {
      el.folderForm.mode.value = listing.is_corvis ? "self" : "project";
      el.folderInput.value = listing.is_corvis ? "" : listing.path;
      state.createFolder = false;
      syncDialog();
      return;
    }
    navigate("#/");  // a fresh chat working in this folder
    state.draft = listing.is_corvis ? { mode: "self", workspace: null } : { mode: "project", workspace: listing.path };
    renderHeader();
    renderWelcome();
    el.input.focus();
  });

  // ---------- voice: spoken replies ----------
  const voice = {
    speak: storage.get("corvis.voice.speak") === "1",
    name: storage.get("corvis.voice.name") || "",
    rate: parseFloat(storage.get("corvis.voice.rate") || "1") || 1,
    autosend: storage.get("corvis.voice.autosend") !== "0",
    unlocked: false,
  };
  const synth = window.speechSynthesis;
  const MALE = /\b(ryan|george|thomas|daniel|arthur|oliver|brian|alfie|elliot|noah|guy|james|william|harry|fred|alex|david|mark|richard|christopher|eric|roger|aaron|reed|rishi|liam)\b/i;

  function rankVoice(v) {
    let s = 0;
    if (/^en[-_]GB/i.test(v.lang)) s += 40;
    else if (/^en/i.test(v.lang)) s += 10;
    if (MALE.test(v.name)) s += 30;
    if (/natural|neural|online|premium|enhanced/i.test(v.name)) s += 20;
    return s;
  }

  function englishVoices() {
    if (!synth) return [];
    return synth.getVoices().filter((v) => /^en/i.test(v.lang)).sort((a, b) => rankVoice(b) - rankVoice(a));
  }

  function chosenVoice() {
    const voices = englishVoices();
    return voices.find((v) => v.name === voice.name) || voices[0] || null;
  }

  function fillVoices() {
    const voices = englishVoices();
    el.voiceSelect.innerHTML = "";
    if (!voices.length) {
      el.voiceSelect.innerHTML = `<option>No voices found on this device</option>`;
      return;
    }
    const pick = chosenVoice();
    for (const v of voices) {
      const o = document.createElement("option");
      o.value = v.name;
      o.textContent = `${v.name} (${v.lang})`;
      o.selected = pick && v.name === pick.name;
      el.voiceSelect.appendChild(o);
    }
  }
  if (synth) synth.addEventListener("voiceschanged", fillVoices);

  function speakable(md) {
    return md
      .replace(/```[\s\S]*?(```|$)/g, " I've put the code on screen. ")
      .replace(/^\s*\|.*\|\s*$/gm, "")                 // tables are for reading, not hearing
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")          // links: keep the words
      .replace(/https?:\/\/\S+/g, "the link on screen")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/[*_#>~]+/g, "")
      .replace(/^\s*[-+]\s+/gm, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 1800);
  }

  function speak(text, force) {
    if (!synth || (!voice.speak && !force)) return;
    synth.cancel();
    const clean = speakable(text || "");
    if (!clean) return;
    // Long utterances get cut off in some browsers, so speak sentence by sentence.
    const parts = clean.match(/[^.!?]+[.!?]*\s*/g) || [clean];
    let chunk = "";
    const v = chosenVoice();
    const say = (t) => {
      const u = new SpeechSynthesisUtterance(t);
      try { if (v) { u.voice = v; u.lang = v.lang; } } catch (_) { /* fall back to the default voice */ }
      u.rate = voice.rate;
      synth.speak(u);
    };
    for (const p of parts) {
      if ((chunk + p).length > 220 && chunk) { say(chunk); chunk = ""; }
      chunk += p;
    }
    if (chunk.trim()) say(chunk);
  }

  function unlockSpeech() {
    // iPhones only allow speech that starts from a tap; a silent first word unlocks it.
    if (!synth || voice.unlocked || !voice.speak) return;
    voice.unlocked = true;
    const u = new SpeechSynthesisUtterance(" ");
    u.volume = 0;
    synth.speak(u);
  }
  el.send.addEventListener("click", unlockSpeech);
  el.input.addEventListener("keydown", (e) => { if (e.key === "Enter") unlockSpeech(); });

  function renderVoiceButton() {
    el.voiceOpen.classList.toggle("on", voice.speak);
    el.voiceOpen.querySelector("use").setAttribute("href", voice.speak ? "#i-speaker" : "#i-speaker-off");
    el.voiceOpen.hidden = !synth && !(state.info && state.info.voice && state.info.voice.speech_to_text !== "off");
  }

  el.voiceOpen.addEventListener("click", () => {
    el.speakToggle.checked = voice.speak;
    el.voiceRate.value = voice.rate;
    el.voiceAutosend.checked = voice.autosend;
    fillVoices();
    const stt = state.info && state.info.voice ? state.info.voice.speech_to_text : "off";
    el.voiceNote.textContent =
      stt === "local" ? "The mic turns your speech into text privately on your PC." :
      stt === "browser" ? "The mic uses your browser's speech recognition (Chrome sends audio to Google, Safari to Apple). For private voice input on your PC, double-click Install_Voice.bat." :
      "The mic is turned off in config.yaml.";
    if (!synth) el.voiceNote.textContent += " This browser can't speak replies.";
    el.voiceDialog.showModal();
  });
  el.speakToggle.addEventListener("change", () => {
    voice.speak = el.speakToggle.checked;
    storage.set("corvis.voice.speak", voice.speak ? "1" : "0");
    if (!voice.speak && synth) synth.cancel();
    if (voice.speak) unlockSpeech();
    renderVoiceButton();
  });
  el.voiceSelect.addEventListener("change", () => {
    voice.name = el.voiceSelect.value;
    storage.set("corvis.voice.name", voice.name);
  });
  el.voiceRate.addEventListener("input", () => {
    voice.rate = parseFloat(el.voiceRate.value) || 1;
    storage.set("corvis.voice.rate", String(voice.rate));
  });
  el.voiceAutosend.addEventListener("change", () => {
    voice.autosend = el.voiceAutosend.checked;
    storage.set("corvis.voice.autosend", voice.autosend ? "1" : "0");
  });
  el.voiceTest.addEventListener("click", () =>
    speak("Good evening. Corvis here. Everything is running smoothly, and I'm ready when you are.", true));
  el.voiceClose.addEventListener("click", () => el.voiceDialog.close());

  // ---------- voice: the mic ----------
  const mic = { mode: "off", recorder: null, stream: null, chunks: [], rec: null, timer: null, placeholder: "" };
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  function setupMic() {
    const stt = state.info && state.info.voice ? state.info.voice.speech_to_text : "off";
    mic.mode = stt === "local" ? "local" : stt === "browser" && Recognition ? "browser" : "off";
    el.mic.hidden = mic.mode === "off";
    renderVoiceButton();
  }

  function micState(kind) {
    el.mic.classList.toggle("recording", kind === "recording");
    el.mic.classList.toggle("busy", kind === "busy");
    el.mic.setAttribute("aria-label", kind === "recording" ? "Stop and send" : "Talk to Corvis");
    if (kind === "recording") {
      mic.placeholder = mic.placeholder || el.input.placeholder;
      el.input.placeholder = "Listening… tap the mic again when you're done";
    } else if (kind === "busy") {
      el.input.placeholder = "Turning your words into text…";
    } else if (mic.placeholder) {
      el.input.placeholder = mic.placeholder;
      mic.placeholder = "";
    }
  }

  function heard(text) {
    micState("idle");
    text = (text || "").trim();
    if (!text) return toast("I didn't catch that. Try again a little closer to the mic.");
    el.input.value = (el.input.value.trim() ? el.input.value.trim() + " " : "") + text;
    autosize(); updateSend();
    if (voice.autosend && !state.running) send(); else el.input.focus();
  }

  async function startLocal() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return toast(window.isSecureContext ? "This browser can't record audio." :
        "The mic needs a secure (https) connection. Set up phone access with Setup_Phone_Access.bat.", 8000);
    }
    try {
      mic.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (_) {
      return toast("Corvis needs permission to use the microphone. Allow it in your browser settings.", 7000);
    }
    const type = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"]
      .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    mic.chunks = [];
    mic.recorder = new MediaRecorder(mic.stream, type ? { mimeType: type } : undefined);
    mic.recorder.ondataavailable = (e) => { if (e.data.size) mic.chunks.push(e.data); };
    mic.recorder.onstop = async () => {
      clearTimeout(mic.timer);
      mic.stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(mic.chunks, { type: mic.recorder.mimeType || "audio/webm" });
      micState("busy");
      try {
        const res = await fetch("/api/transcribe", {
          method: "POST", headers: { "X-Corvis": "1", "Content-Type": blob.type }, body: blob,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "Couldn't turn that into text.");
        heard(data.text);
      } catch (err) {
        micState("idle");
        toast(err.message, 8000);
      }
    };
    mic.recorder.start();
    micState("recording");
    mic.timer = setTimeout(() => mic.recorder && mic.recorder.state === "recording" && mic.recorder.stop(), 120000);
  }

  function startBrowser() {
    const rec = new Recognition();
    mic.rec = rec;
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";
    const before = el.input.value;
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      el.input.value = (before ? before + " " : "") + finalText + interim;
      autosize();
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed") toast("Corvis needs permission to use the microphone.", 7000);
    };
    rec.onend = () => {
      mic.rec = null;
      el.input.value = before;
      heard(finalText);
    };
    rec.start();
    micState("recording");
  }

  el.mic.addEventListener("click", () => {
    if (synth) synth.cancel();  // stop talking when you start
    unlockSpeech();
    if (mic.recorder && mic.recorder.state === "recording") return mic.recorder.stop();
    if (mic.rec) return mic.rec.stop();
    if (mic.mode === "local") startLocal();
    else if (mic.mode === "browser") startBrowser();
  });

  // ---------- memory panel ----------
  async function loadFacts() {
    let facts = [];
    try { facts = (await api("/api/memory")).facts; } catch (err) { return toast(err.message); }
    el.facts.innerHTML = "";
    if (!facts.length) {
      el.facts.innerHTML = `<li class="empty">Nothing yet. Tell Corvis about yourself and your projects, or add something below.</li>`;
      return;
    }
    for (const f of facts) {
      const li = document.createElement("li");
      const span = document.createElement("span");
      span.textContent = f.text;
      if (f.bot) {
        const b = botById(f.bot) || { name: f.bot_name || "a bot", color: "#888" };
        const tag = document.createElement("small");
        tag.className = "fact-bot";
        tag.append(avatar(b, "tiny"), `${b.name} learned this`);
        span.appendChild(tag);
      }
      const del = document.createElement("button");
      del.type = "button";
      del.className = "icon-btn";
      del.setAttribute("aria-label", `Forget: ${f.text}`);
      del.title = "Forget this";
      del.innerHTML = svg("i-trash");
      del.addEventListener("click", async () => {
        try { await api(`/api/memory/${encodeURIComponent(f.id)}`, { method: "DELETE" }); }
        catch (err) { toast(err.message); }
        loadFacts();
      });
      li.append(span, del);
      el.facts.appendChild(li);
    }
  }

  el.memoryOpen.addEventListener("click", async () => {
    await loadFacts();
    el.memoryDialog.showModal();
    el.factInput.focus();
  });
  el.memoryClose.addEventListener("click", () => el.memoryDialog.close());
  el.factForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = el.factInput.value.trim();
    if (!text) return;
    try {
      await api("/api/memory", { method: "POST", body: { text } });
      el.factInput.value = "";
      loadFacts();
    } catch (err) { toast(err.message); }
  });

  // ---------- restart ----------
  async function restartCorvis() {
    try {
      await api("/api/restart", { method: "POST" });
    } catch (err) { return toast(err.message, 6000); }
    toast("Restarting Corvis…", 20000);
    await sleep(1500);
    for (let i = 0; i < 60; i++) {
      try { await api("/api/info"); location.reload(); return; } catch (_) { await sleep(1000); }
    }
    toast("Corvis didn't come back. Check the Corvis window for errors.", 10000);
  }
  el.restart.addEventListener("click", restartCorvis);

  el.signOut.addEventListener("click", async () => {
    try { await api("/api/logout", { method: "POST" }); } catch (_) { /* already signed out */ }
    location.replace("/login");
  });

  // ---------- bots: sidebar list & editor ----------
  function renderBots() {
    el.botList.innerHTML = "";
    const active = state.conv ? null : state.draft.bot || LEAD;
    for (const b of bots()) {
      const li = document.createElement("li");
      li.className = "bot-row";
      const go = document.createElement("button");
      go.type = "button";
      go.title = b.lead ? `New chat with ${b.name}` : (b.job || "").slice(0, 200) || `New chat with ${b.name}`;
      go.append(avatar(b));
      const name = document.createElement("span");
      name.className = "bot-name";
      name.textContent = b.name;
      go.append(name);
      if (active === b.id && !state.conv) go.setAttribute("aria-current", "true");
      go.addEventListener("click", () => {
        state.draft.bot = b.id;
        navigate("#/");
        renderWelcome();
        if (isPhone()) showSidebar(false);
      });
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "icon-btn edit";
      edit.innerHTML = svg("i-edit");
      edit.title = b.lead ? `${b.name}'s job` : `Edit ${b.name}`;
      edit.setAttribute("aria-label", edit.title);
      edit.addEventListener("click", () => openBotEditor(b));
      li.append(go, edit);
      el.botList.appendChild(li);
    }
  }

  const SWATCHES = ["#4fb3a9", "#e8a33d", "#7c6cf0", "#e5534b", "#3d8be8", "#c35bd6", "#58a55c", "#d9774a"];
  let editing = null;
  function openBotEditor(bot) {
    editing = bot || null;
    const isLead = !!(bot && bot.lead);
    el.botTitle.textContent = !bot ? "New bot" : isLead ? `${bot.name}'s job` : `Edit ${bot.name}`;
    el.botName.value = bot ? bot.name : "";
    el.botName.disabled = isLead;
    el.botName.title = isLead ? "Change the lead's name in config.yaml (name:)" : "";
    el.botJob.value = bot ? bot.job || "" : "";
    el.botJob.placeholder = isLead ? "Optional: anything you want Corvis to always keep in mind about his role."
      : "Find new leads in our CRM every morning and draft friendly follow-ups. Never send anything without my OK. Keep notes on who approves deals.";
    el.botSave.textContent = bot ? "Save" : "Create bot";
    el.botDelete.hidden = !bot || isLead;
    el.botDelete.textContent = "Delete bot";
    el.botDelete.classList.remove("confirm");
    const abilities = (state.info && state.info.abilities) || {};
    const have = new Set(bot ? bot.abilities : ["web", "computer"]);
    el.botAbilities.innerHTML = "<legend>What it can use</legend>";
    for (const [key, label] of Object.entries(abilities)) {
      const lab = document.createElement("label");
      lab.innerHTML = `<input type="checkbox" value="${key}"><span></span>`;
      lab.querySelector("span").textContent = label;
      const box = lab.querySelector("input");
      box.checked = isLead || have.has(key);
      box.disabled = isLead;
      el.botAbilities.appendChild(lab);
    }
    if (isLead) el.botAbilities.insertAdjacentHTML("beforeend", `<p class="hint">The lead can use everything.</p>`);
    const used = new Set(bots().map((b) => b.color));
    const pick = bot ? bot.color : SWATCHES.find((c) => !used.has(c)) || SWATCHES[0];
    el.botColors.innerHTML = "";
    el.botColors.closest("fieldset").hidden = isLead;
    for (const c of SWATCHES) {
      const b = document.createElement("button");
      b.type = "button";
      b.style.setProperty("--c", c);
      b.className = c === pick ? "on" : "";
      b.setAttribute("aria-label", `Color ${c}`);
      b.addEventListener("click", () => { el.botColors.querySelectorAll("button").forEach((x) => (x.className = "")); b.className = "on"; });
      el.botColors.appendChild(b);
    }
    el.botDialog.showModal();
    (isLead ? el.botJob : el.botName).focus();
  }
  el.botAdd.addEventListener("click", () => openBotEditor(null));
  el.botCancel.addEventListener("click", () => el.botDialog.close());
  el.botForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const color = (el.botColors.querySelector("button.on") || {}).style;
    const body = {
      name: el.botName.value.trim(), job: el.botJob.value.trim(),
      abilities: [...el.botAbilities.querySelectorAll("input:checked")].map((x) => x.value),
      color: color ? color.getPropertyValue("--c").trim() : undefined,
    };
    try {
      const saved = editing ? await api(`/api/bots/${editing.id}`, { method: "PATCH", body })
                            : await api("/api/bots", { method: "POST", body });
      el.botDialog.close();
      await loadInfo();
      if (!editing) { state.draft.bot = saved.id; navigate("#/"); toast(`${saved.name} is ready. Say hi, or mention @${saved.name} in any chat.`); }
      else { renderHeader(); if (state.conv) renderThread(); else renderWelcome(); }
    } catch (err) { toast(err.message, 6000); }
  });
  el.botDelete.addEventListener("click", async () => {
    if (!el.botDelete.classList.contains("confirm")) {
      el.botDelete.classList.add("confirm");
      el.botDelete.textContent = "Delete it and its routines?";
      return;
    }
    try { await api(`/api/bots/${editing.id}`, { method: "DELETE" }); } catch (err) { return toast(err.message); }
    el.botDialog.close();
    if (state.draft.bot === editing.id) state.draft.bot = LEAD;
    await loadInfo();
    navigate("#/");
  });

  // ---------- @mentions ----------
  function mentionedBot(text) {
    const low = (text || "").toLowerCase();
    let best = null;
    for (const b of bots()) {
      const tag = "@" + b.name.toLowerCase();
      const i = low.indexOf(tag);
      if (i < 0 || (i > 0 && /[a-z0-9]/i.test(low[i - 1]))) continue;
      const after = low[i + tag.length];
      if (after && /[a-z0-9]/i.test(after)) continue;
      if (!best || b.name.length > best.name.length) best = b;
    }
    return best;
  }
  let mentionPick = 0;
  function hideMentions() { el.mentions.hidden = true; el.mentions.innerHTML = ""; }
  function mentionQuery() {
    const pos = el.input.selectionStart;
    const before = el.input.value.slice(0, pos);
    const m = before.match(/(?:^|\s)@([\w ]{0,30})$/);
    return m ? { q: m[1].toLowerCase(), start: pos - m[1].length - 1, end: pos } : null;
  }
  function showMentions() {
    const mq = mentionQuery();
    const list = mq && bots().length > 1 ? bots().filter((b) => b.name.toLowerCase().startsWith(mq.q.trimStart())) : [];
    if (!list.length) return hideMentions();
    mentionPick = Math.min(mentionPick, list.length - 1);
    el.mentions.innerHTML = "";
    list.forEach((b, i) => {
      const li = document.createElement("li");
      li.className = i === mentionPick ? "on" : "";
      li.setAttribute("role", "option");
      li.append(avatar(b, "tiny"), b.name);
      li.addEventListener("mousedown", (e) => { e.preventDefault(); insertMention(b); });
      el.mentions.appendChild(li);
    });
    el.mentions._list = list;
    el.mentions.hidden = false;
  }
  function insertMention(b) {
    const mq = mentionQuery();
    if (!mq) return hideMentions();
    const v = el.input.value;
    el.input.value = v.slice(0, mq.start) + "@" + b.name + " " + v.slice(mq.end);
    const caret = mq.start + b.name.length + 2;
    el.input.setSelectionRange(caret, caret);
    hideMentions();
    autosize(); updateSend(); el.input.focus();
  }
  el.input.addEventListener("input", () => { mentionPick = 0; showMentions(); });
  el.input.addEventListener("keydown", (e) => {
    if (el.mentions.hidden) return;
    const list = el.mentions._list || [];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      mentionPick = (mentionPick + (e.key === "ArrowDown" ? 1 : list.length - 1)) % list.length;
      showMentions();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      e.stopImmediatePropagation();
      insertMention(list[mentionPick]);
    } else if (e.key === "Escape") hideMentions();
  }, true);
  el.input.addEventListener("blur", () => setTimeout(hideMentions, 150));

  // ---------- routines ----------
  function fmtWhen(ts) {
    if (!ts) return "never";
    const d = new Date(ts * 1000);
    return d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
  }
  async function loadRoutines() {
    let data;
    try { data = await api("/api/routines"); } catch (err) { return toast(err.message); }
    el.routinesTz.textContent = data.tz;
    el.routinesCount.textContent = data.routines.length ? `${data.routines.filter((r) => r.enabled).length} on` : "";
    el.routines.innerHTML = "";
    if (!data.routines.length) {
      el.routines.innerHTML = `<li class="empty">No routines yet. Add one below, or just tell a bot: "every weekday at 8, check my inbox for new leads".</li>`;
    }
    for (const r of data.routines) {
      const li = document.createElement("li");
      li.className = r.enabled ? "" : "off";
      const bot = botById(r.bot);
      li.append(avatar(bot || { name: "?", color: "#888" }));
      const info = document.createElement("div");
      info.className = "info";
      info.innerHTML = `<b></b><small></small><small></small>`;
      info.children[0].textContent = r.name;
      info.children[1].textContent = `${r.when} · ${bot ? bot.name : "deleted bot"} · next ${r.enabled ? fmtWhen(r.next_run) : "paused"}`;
      info.children[2].textContent = r.prompt;
      info.title = r.prompt;
      const acts = document.createElement("div");
      acts.className = "acts";
      const tog = document.createElement("label");
      tog.className = "toggle";
      tog.title = r.enabled ? "On" : "Paused";
      tog.innerHTML = `<input type="checkbox" aria-label="Routine on">`;
      tog.firstChild.checked = r.enabled;
      tog.firstChild.addEventListener("change", async (e) => {
        try { await api(`/api/routines/${r.id}`, { method: "PATCH", body: { enabled: e.target.checked } }); } catch (err) { toast(err.message); }
        loadRoutines();
      });
      const run = document.createElement("button");
      run.type = "button"; run.className = "icon-btn"; run.innerHTML = svg("i-play");
      run.title = "Run now"; run.setAttribute("aria-label", `Run ${r.name} now`);
      run.addEventListener("click", async () => {
        try {
          const out = await api(`/api/routines/${r.id}/run`, { method: "POST" });
          el.routinesDialog.close();
          if (out.conversation_id) navigate(`#/c/${out.conversation_id}`);
          refreshList();
        } catch (err) { toast(err.message); }
      });
      const del = document.createElement("button");
      del.type = "button"; del.className = "icon-btn"; del.innerHTML = svg("i-trash");
      del.title = "Delete"; del.setAttribute("aria-label", `Delete ${r.name}`);
      del.addEventListener("click", async () => {
        if (!del.classList.contains("confirm")) { del.classList.add("confirm"); del.textContent = "Delete?"; return; }
        try { await api(`/api/routines/${r.id}`, { method: "DELETE" }); } catch (err) { toast(err.message); }
        loadRoutines();
      });
      del.addEventListener("blur", () => { del.classList.remove("confirm"); del.innerHTML = svg("i-trash"); });
      acts.append(tog, run, del);
      li.append(info, acts);
      el.routines.appendChild(li);
    }
  }
  function syncEvery() {
    const every = $("#rt-every").value;
    $("#rt-day-field").hidden = every !== "week";
    $("#rt-at-field").hidden = every === "hours";
    $("#rt-hours-field").hidden = every !== "hours";
  }
  $("#rt-every").addEventListener("change", syncEvery);
  el.routinesOpen.addEventListener("click", async () => {
    const sel = $("#rt-bot");
    sel.innerHTML = "";
    for (const b of bots()) sel.add(new Option(b.name, b.id, false, b.id === (state.conv ? state.conv.bot : state.draft.bot)));
    syncEvery();
    await loadRoutines();
    el.routinesDialog.showModal();
    if (isPhone()) showSidebar(false);
  });
  el.routinesClose.addEventListener("click", () => el.routinesDialog.close());
  el.routineForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const every = $("#rt-every").value;
    const body = {
      name: $("#rt-name").value.trim(), bot: $("#rt-bot").value, prompt: $("#rt-prompt").value.trim(),
      schedule: { every, at: $("#rt-at").value || "08:00", day: $("#rt-day").value, hours: Number($("#rt-hours").value) },
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    try { await api("/api/routines", { method: "POST", body }); }
    catch (err) { return toast(err.message, 6000); }
    el.routineForm.reset();
    el.routineNew.open = false;
    syncEvery();
    loadRoutines();
  });

  // ---------- the bots' computer (live view) ----------
  let cpTimer = null, cpBusy = false;
  async function cpStatus() {
    try {
      const s = await api("/api/computer");
      const cur = el.cpTab.value;
      el.cpTab.innerHTML = "";
      el.cpTab.add(new Option("Your tab", "owner"));
      for (const t of s.tabs.filter((t) => t.key !== "owner")) {
        const b = botById(t.key);
        el.cpTab.add(new Option(`${b ? b.name : t.key}: ${t.title || t.url}`.slice(0, 60), t.key));
      }
      el.cpTab.value = [...el.cpTab.options].some((o) => o.value === cur) ? cur : "owner";
      const tab = s.tabs.find((t) => t.key === el.cpTab.value);
      if (tab && document.activeElement !== el.cpUrl) el.cpUrl.value = tab.url === "about:blank" ? "" : tab.url;
      return s;
    } catch (_) { return null; }
  }
  async function cpAct(body) {
    try { await api("/api/computer", { method: "POST", body: { tab: el.cpTab.value || "owner", ...body } }); }
    catch (err) { toast(err.message, 6000); }
    cpRefresh();
    cpStatus();
  }
  // The screenshot request needs the X-Corvis header, so fetch it as a blob instead of <img src>.
  function cpRefresh() {
    if (cpBusy || !el.computerDialog.open) return;
    cpBusy = true;
    fetch(`/api/computer/screen?tab=${encodeURIComponent(el.cpTab.value || "owner")}`, { headers: { "X-Corvis": "1" } })
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => {
        if (blob) {
          const old = el.cpImg.src;
          el.cpImg.src = URL.createObjectURL(blob);
          if (old.startsWith("blob:")) URL.revokeObjectURL(old);
          el.cpImg.hidden = false;
          el.cpEmpty.hidden = true;
        }
      })
      .catch(() => {})
      .finally(() => { cpBusy = false; });
  }
  el.computerOpen.addEventListener("click", async () => {
    el.cpImg.hidden = true;
    el.cpEmpty.hidden = false;
    el.computerDialog.showModal();
    if (isPhone()) showSidebar(false);
    const s = await cpStatus();
    if (s && s.running) cpRefresh();
    else el.cpUrl.focus();
    clearInterval(cpTimer);
    cpTimer = setInterval(() => { if (!document.hidden) cpRefresh(); }, 1200);
  });
  el.computerDialog.addEventListener("close", () => clearInterval(cpTimer));
  el.computerClose.addEventListener("click", () => el.computerDialog.close());
  el.cpTab.addEventListener("change", () => { cpRefresh(); cpStatus(); });
  el.cpGo.addEventListener("submit", (e) => {
    e.preventDefault();
    const url = el.cpUrl.value.trim();
    if (url) cpAct({ action: "goto", url });
  });
  el.cpBack.addEventListener("click", () => cpAct({ action: "back" }));
  el.cpImg.addEventListener("click", (e) => {
    const r = el.cpImg.getBoundingClientRect();
    cpAct({ action: "click", x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height });
    el.cpText.focus({ preventScroll: true });
  });
  el.cpType.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = el.cpText.value;
    if (!text) return;
    el.cpText.value = "";
    cpAct({ action: "type", text });
  });
  el.cpType.addEventListener("click", (e) => {
    const k = e.target.closest("[data-key]");
    const s = e.target.closest("[data-scroll]");
    if (k) cpAct({ action: "key", key: k.dataset.key });
    if (s) cpAct({ action: "scroll", dy: Number(s.dataset.scroll) });
  });

  // ---------- start ----------
  (async function init() {
    if (isPhone()) {
      showSidebar(false);
      el.input.placeholder = "Ask Corvis anything";
    }
    await loadInfo();
    try {  // routines run in the owner's time zone
      await api("/api/owner", { method: "POST", body: { tz: Intl.DateTimeFormat().resolvedOptions().timeZone } });
    } catch (_) { /* older server */ }
    await refreshList();
    await route();
    api("/api/routines").then((d) => {
      el.routinesCount.textContent = d.routines.length ? `${d.routines.filter((r) => r.enabled).length} on` : "";
    }).catch(() => {});
    if ("serviceWorker" in navigator && window.isSecureContext) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});  // makes Corvis installable
    }
    setInterval(loadInfo, 20000);
    setInterval(() => { if (!document.hidden) refreshList(); }, 30000);
  })();
})();
