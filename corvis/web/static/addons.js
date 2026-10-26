/* Connectors and plugins panels, and /command suggestions in the message box. */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const svg = (id) => `<svg><use href="#${id}"/></svg>`;
  let commands = [];

  async function api(path, opts = {}) {
    const headers = { "X-Corvis": "1" };
    if (opts.body) headers["Content-Type"] = "application/json";
    const res = await fetch(path, { method: opts.method || "GET", headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined });
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (res.status === 401 && data.login) { location.replace("/login"); throw new Error("Sign in first."); }
    if (!res.ok) { const err = new Error(data.error || `Corvis answered with an error (${res.status}).`); err.data = data; throw err; }
    return data;
  }
  let toastTimer;
  function toast(text, ms = 5000) {
    const t = $("#toast");
    t.textContent = text; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), ms);
  }
  function node(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function toggle(on, label, onChange) {
    const wrap = node("label", "toggle");
    wrap.title = label;
    const input = node("input");
    input.type = "checkbox"; input.checked = on; input.setAttribute("aria-label", label);
    input.addEventListener("change", () => onChange(input.checked, input));
    wrap.appendChild(input);
    return wrap;
  }
  function iconBtn(icon, label, onClick, cls = "") {
    const b = node("button", `icon-btn ${cls}`);
    b.type = "button"; b.title = label; b.setAttribute("aria-label", label); b.innerHTML = svg(icon);
    b.addEventListener("click", onClick);
    return b;
  }
  async function busy(btn, fn) {
    const old = btn.textContent;
    btn.disabled = true; btn.textContent = "Working…";
    try { return await fn(); } finally { btn.disabled = false; btn.textContent = old; }
  }

  // ---------- connectors ----------
  let modes = {};
  function statusLine(c) {
    const s = c.status || {};
    if (!c.enabled) return ["off", "Turned off"];
    if (s.state === "connected") return ["ok", `${s.tools} tool${s.tools === 1 ? "" : "s"}${s.server ? " · " + s.server : ""}`];
    if (s.state === "error") return ["err", s.error || "Couldn't connect"];
    if (s.state === "connecting") return ["", "Connecting…"];
    return ["", "Connects when Corvis first needs it"];
  }
  function renderConnectors(data) {
    modes = data.approval_modes || modes;
    const list = $("#connector-list");
    list.innerHTML = "";
    const count = data.connectors.filter((c) => c.enabled).length;
    $("#connectors-count").textContent = count ? `${count} on` : "";
    if (!data.connectors.length) {
      list.appendChild(node("li", "empty", "No connectors yet. Add one below: pick from the directory or connect your own."));
    }
    for (const c of data.connectors) {
      const li = node("li", c.enabled ? "" : "off");
      const [state, text] = statusLine(c);
      const dot = node("span", `dot ${state}`);
      const info = node("div", "info");
      const where = c.kind === "http" ? c.url : `${c.command} ${(c.args || []).join(" ")}`;
      info.append(node("b", "", c.name), node("small", "", (c.source !== "you" ? `From the ${c.source.slice(7)} plugin · ` : "") + where),
        node("small", `state ${state}`, text));
      const acts = node("div", "acts");
      if (c.source === "you") {
        acts.append(toggle(c.enabled, `Turn ${c.name} on or off`, async (on, input) => {
          try { renderConnectors(await api(`/api/connectors/${c.id}`, { method: "PATCH", body: { enabled: on } })); }
          catch (err) { input.checked = !on; toast(err.message); }
        }));
      }
      const more = node("details", "addon-more");
      const sum = node("summary", "", "Details");
      more.appendChild(sum);
      if (c.tools && c.tools.length) {
        const tl = node("ul", "tool-list");
        for (const t of c.tools) {
          const ti = node("li");
          ti.append(node("code", "", t.name), node("span", t.read_only ? "badge" : "badge warn", t.read_only ? "reads" : "changes things"));
          if (t.description) ti.appendChild(node("small", "", t.description));
          tl.appendChild(ti);
        }
        more.appendChild(tl);
      }
      const row = node("div", "more-acts");
      if (c.source === "you") {
        const sel = node("select");
        sel.setAttribute("aria-label", "When to ask you");
        for (const [k, v] of Object.entries(modes)) { const o = node("option", "", v); o.value = k; sel.appendChild(o); }
        sel.value = c.approval || "ask";
        sel.addEventListener("change", async () => {
          try { renderConnectors(await api(`/api/connectors/${c.id}`, { method: "PATCH", body: { approval: sel.value } })); }
          catch (err) { toast(err.message); }
        });
        row.appendChild(sel);
      }
      const test = node("button", "btn", "Reconnect");
      test.type = "button";
      test.addEventListener("click", () => busy(test, async () => {
        const r = await api(`/api/connectors/${c.id}/test`, { method: "POST", body: {} }).catch((e) => ({ error: e.message }));
        if (r.connectors) renderConnectors(r);
        toast(r.error ? `Couldn't connect: ${r.error}` : `${c.name} is connected.`);
      }));
      row.appendChild(test);
      if (c.source === "you") {
        if (c.kind === "http") {
          const tok = node("button", "btn ghost", c.has_token ? "Change token" : "Add token");
          tok.type = "button";
          tok.addEventListener("click", async () => {
            const v = prompt(`New token for ${c.name}:`);
            if (!v) return;
            try { renderConnectors(await api(`/api/connectors/${c.id}`, { method: "PATCH", body: { token: v } })); toast("Token saved."); }
            catch (err) { toast(err.message); }
          });
          row.appendChild(tok);
        }
        row.appendChild(iconBtn("i-trash", `Remove ${c.name}`, async () => {
          if (!confirm(`Remove the ${c.name} connector?`)) return;
          try { renderConnectors(await api(`/api/connectors/${c.id}`, { method: "DELETE" })); } catch (err) { toast(err.message); }
        }, "danger"));
      }
      more.appendChild(row);
      info.appendChild(more);
      li.append(dot, info, acts);
      list.appendChild(li);
    }
    renderCatalog(data.catalog || []);
  }
  function renderCatalog(catalog) {
    const box = $("#connector-catalog");
    box.innerHTML = "";
    for (const t of catalog) {
      const card = node("div", "card");
      card.append(node("b", "", t.name), node("small", "", t.about));
      if (t.needs) card.appendChild(node("small", "needs", `Needs ${t.needs}`));
      const btn = node("button", "btn", "Connect");
      btn.type = "button";
      btn.addEventListener("click", () => busy(btn, async () => {
        const body = { template: t.id };
        if ((t.asks || []).includes("folder")) {
          body.folder = prompt(`Which folder may ${t.name} use? (paste its full path)`);
          if (!body.folder) return;
        }
        if (t.token_label) {
          body.token = prompt(`${t.token_label}:\n${t.setup || ""}`);
          if (!body.token) return;
        }
        await addConnector(body);
      }));
      card.appendChild(btn);
      box.appendChild(card);
    }
  }
  async function addConnector(body) {
    try {
      const r = await api("/api/connectors", { method: "POST", body });
      renderConnectors(r);
      const added = r.connectors.find((c) => c.id === r.added);
      const s = added && added.status;
      toast(s && s.state === "connected" ? `${added.name} connected with ${s.tools} tools.`
        : `${added ? added.name : "Connector"} was added but didn't connect: ${(s && s.error) || "unknown error"}`, 8000);
      $("#connector-new").open = false;
    } catch (err) { toast(err.message); }
  }
  async function openConnectors() {
    try { renderConnectors(await api("/api/connectors")); } catch (err) { return toast(err.message); }
    $("#connectors-dialog").showModal();
  }
  $("#connectors-open").addEventListener("click", openConnectors);
  $("#connectors-close").addEventListener("click", () => $("#connectors-dialog").close());
  document.querySelectorAll('input[name="ckind"]').forEach((r) => r.addEventListener("change", () => {
    const http = document.querySelector('input[name="ckind"]:checked').value === "http";
    $(".kind-http").hidden = !http; $(".kind-stdio").hidden = http;
  }));
  $("#connector-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const kind = document.querySelector('input[name="ckind"]:checked').value;
    const env = {};
    for (const line of $("#cn-env").value.split("\n")) {
      const i = line.indexOf("=");
      if (i > 0) env[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
    await addConnector({ name: $("#cn-name").value.trim(), kind, url: $("#cn-url").value.trim(),
      token: $("#cn-token").value, command: $("#cn-command").value.trim(),
      args: $("#cn-args").value.trim(), env });
    $("#connector-form").reset();
  });

  // ---------- plugins ----------
  function renderPlugins(data) {
    commands = data.commands || [];
    const list = $("#plugin-list");
    list.innerHTML = "";
    const on = data.plugins.filter((p) => p.enabled).length;
    $("#plugins-count").textContent = on ? `${on} on` : "";
    if (!data.plugins.length) list.appendChild(node("li", "empty", "No plugins yet. Install one below."));
    for (const p of data.plugins) {
      const li = node("li", p.enabled ? "" : "off");
      const info = node("div", "info");
      const parts = [];
      if (p.skills.length) parts.push(`${p.skills.length} skill${p.skills.length > 1 ? "s" : ""}`);
      if (p.commands.length) parts.push(p.commands.map((c) => "/" + c).join(" "));
      if (p.connectors.length) parts.push(`${p.connectors.length} connector${p.connectors.length > 1 ? "s" : ""}`);
      if (p.tools.length) parts.push(`tools: ${p.tools.join(", ")}`);
      info.append(node("b", "", `${p.name}${p.version ? " " + p.version : ""}`),
        node("small", "", p.description || "No description"),
        node("small", "", (parts.join(" · ") || "Nothing to add yet") + (p.author ? ` · by ${p.author}` : "")));
      const acts = node("div", "acts");
      acts.append(toggle(p.enabled, `Turn ${p.name} on or off`, async (enabled, input) => {
        try { renderPlugins(await api(`/api/plugins/${encodeURIComponent(p.name)}`, { method: "PATCH", body: { enabled } })); }
        catch (err) { input.checked = !enabled; toast(err.message); }
      }), iconBtn("i-trash", `Remove ${p.name}`, async () => {
        if (!confirm(`Remove the ${p.name} plugin?`)) return;
        try { renderPlugins(await api(`/api/plugins/${encodeURIComponent(p.name)}`, { method: "DELETE" })); }
        catch (err) { toast(err.message); }
      }, "danger"));
      li.append(node("span", `dot ${p.enabled ? "ok" : ""}`), info, acts);
      list.appendChild(li);
    }
    const cmds = $("#plugin-commands");
    cmds.hidden = !commands.length;
    cmds.innerHTML = "";
    if (commands.length) {
      cmds.appendChild(node("b", "", "Slash commands: "));
      cmds.appendChild(node("span", "", "type them at the start of a message."));
      const ul = node("ul");
      for (const c of commands) {
        const li = node("li");
        li.append(node("code", "", `/${c.name}${c.hint ? " " + c.hint : ""}`), node("span", "", c.description ? ` ${c.description}` : ""));
        ul.appendChild(li);
      }
      cmds.appendChild(ul);
    }
    const markets = $("#market-list");
    markets.innerHTML = "";
    for (const m of data.marketplaces || []) {
      const box = node("div", "market");
      const head = node("div", "market-head");
      head.append(node("b", "", m.name), node("small", "", m.source),
        iconBtn("i-trash", `Remove the ${m.name} marketplace`, async () => {
          try { renderPlugins(await api(`/api/plugins/marketplaces/${encodeURIComponent(m.name)}`, { method: "DELETE" })); }
          catch (err) { toast(err.message); }
        }));
      box.appendChild(head);
      for (const p of m.plugins) {
        const row = node("div", "card");
        row.append(node("b", "", p.name), node("small", "", p.description || ""));
        const btn = node("button", "btn", p.installed ? "Update" : "Install");
        btn.type = "button";
        btn.addEventListener("click", () => busy(btn, () => install({ market: m.name, plugin: p.name })));
        row.appendChild(btn);
        box.appendChild(row);
      }
      markets.appendChild(box);
    }
  }
  async function install(body) {
    try {
      const r = await api("/api/plugins", { method: "POST", body });
      renderPlugins(r);
      toast(`Installed ${r.installed}.`);
      return true;
    } catch (err) {
      if (err.data && err.data.needs_code_approval) {
        if (confirm(`${err.message}\n\nInstall it anyway?`)) return install({ ...body, allow_code: true });
        return false;
      }
      toast(err.message, 8000);
      return false;
    }
  }
  async function openPlugins() {
    try { renderPlugins(await api("/api/plugins")); } catch (err) { return toast(err.message); }
    $("#plugins-dialog").showModal();
  }
  $("#plugins-open").addEventListener("click", openPlugins);
  $("#plugins-close").addEventListener("click", () => $("#plugins-dialog").close());
  $("#plugin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const source = $("#pl-source").value.trim();
    if (!source) return;
    const btn = e.submitter || $("#plugin-form button");
    if (await busy(btn, () => install({ source }))) $("#pl-source").value = "";
  });
  $("#pl-zip-btn").addEventListener("click", () => $("#pl-zip").click());
  $("#pl-zip").addEventListener("change", async () => {
    const file = $("#pl-zip").files[0];
    $("#pl-zip").value = "";
    if (!file) return;
    try {
      const res = await fetch(`/api/uploads?name=${encodeURIComponent(file.name)}`, {
        method: "POST", headers: { "X-Corvis": "1", "Content-Type": "application/zip" }, body: file });
      const meta = await res.json();
      if (!res.ok) throw new Error(meta.error || "Upload failed.");
      await install({ upload: meta.id });
    } catch (err) { toast(err.message); }
  });
  $("#market-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const source = $("#mk-source").value.trim();
    if (!source) return;
    const btn = e.submitter || $("#market-form button");
    await busy(btn, async () => {
      try { renderPlugins(await api("/api/plugins/marketplaces", { method: "POST", body: { source } })); $("#mk-source").value = ""; }
      catch (err) { toast(err.message, 8000); }
    });
  });

  // ---------- /commands in the message box ----------
  const input = $("#input"), slash = $("#slash-list");
  let pick = 0, shown = [];
  function hideSlash() { slash.hidden = true; slash.innerHTML = ""; shown = []; }
  function showSlash() {
    const m = input.value.match(/^\/([\w-]*)$/);
    shown = m ? commands.filter((c) => c.name.startsWith(m[1].toLowerCase())) : [];
    if (!shown.length) return hideSlash();
    pick = Math.min(pick, shown.length - 1);
    slash.innerHTML = "";
    shown.forEach((c, i) => {
      const li = node("li", i === pick ? "on" : "");
      li.setAttribute("role", "option");
      li.append(node("code", "", "/" + c.name), node("small", "", c.description || c.plugin));
      li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(c); });
      slash.appendChild(li);
    });
    slash.hidden = false;
  }
  function choose(c) {
    input.value = `/${c.name} `;
    input.setSelectionRange(input.value.length, input.value.length);
    hideSlash();
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  }
  input.addEventListener("input", () => { if (input.value.startsWith("/")) showSlash(); else hideSlash(); });
  input.addEventListener("keydown", (e) => {
    if (slash.hidden || !shown.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      pick = (pick + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length;
      showSlash();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault(); e.stopImmediatePropagation(); choose(shown[pick]);
    } else if (e.key === "Escape") hideSlash();
  }, true);
  input.addEventListener("blur", () => setTimeout(hideSlash, 150));

  // ---------- theme switch (dark by default) ----------
  const themeBtn = $("#theme-toggle");
  function applyTheme(light) {
    if (light) document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    const label = light ? "Switch to the dark theme" : "Switch to the light theme";
    themeBtn.title = label; themeBtn.setAttribute("aria-label", label);
    themeBtn.innerHTML = svg(light ? "i-moon" : "i-sun");
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = light ? "#f5f6fa" : "#151824";
  }
  applyTheme(document.documentElement.dataset.theme === "light");
  themeBtn.addEventListener("click", () => {
    const light = document.documentElement.dataset.theme !== "light";
    applyTheme(light);
    try { localStorage.setItem("corvis-theme", light ? "light" : "dark"); } catch (_) { /* private mode */ }
  });

  // ---------- startup ----------
  (async () => {
    try {
      const info = await api("/api/info");
      $("#connectors-open").hidden = info.connectors === false;
      $("#plugins-open").hidden = info.plugins === false;
      if (info.connectors !== false) {
        const c = await api("/api/connectors");
        const on = c.connectors.filter((x) => x.enabled).length;
        $("#connectors-count").textContent = on ? `${on} on` : "";
      }
      if (info.plugins !== false) {
        const p = await api("/api/plugins");
        commands = p.commands || [];
        const on = p.plugins.filter((x) => x.enabled).length;
        $("#plugins-count").textContent = on ? `${on} on` : "";
      }
    } catch (_) { /* the main app shows connection problems */ }
  })();
})();
