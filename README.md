# Corvis (v1.1)

> **New in v1.1: bots.** A team of AI teammates with their own jobs, memory, schedules and a
> computer that stays signed in to your tools. See "Bots" below.
>
> **New in v1.0: Corvis can live in the cloud.** He runs on a small server with a cloud model,
> so he works from your phone with your PC off, and still uses your PC's files, apps and games
> when it's on. Setup: **[CLOUD_SETUP.md](CLOUD_SETUP.md)**. Everything below still works as
> before if you'd rather keep him entirely on your PC.

The first piece of Corvis: a fully local coding agent that reads your project, plans,
edits code across many files, runs builds and tests, fixes its own errors, uses Git,
and can safely rewrite **its own code** on a branch you approve.

Voice, personality, memory, and the Blender/Unreal tools come next. They plug into
the same tool system, and Corvis can help build them itself.

---

## 1. Install (Windows, about 15 minutes)

1. **Python 3.10+** from python.org (tick "Add to PATH").
2. **Git** from git-scm.com.
3. **Ollama** from ollama.com. Then in a terminal, pull a coding model:
   ```
   ollama pull qwen3-coder:30b
   ```
4. **Give the model a big enough context window.** Ollama's default is small, and
   coding agents fail quietly without room to read files. Set this once, then restart Ollama:
   ```
   setx OLLAMA_CONTEXT_LENGTH 32768
   ```
5. Double-click **`Setup_Corvis.bat`** in this folder. It creates the Python environment,
   installs everything, and checks the model connection.
   You should see: `Model '<your model>' replied: online`.
6. From then on, double-click **`Start_Corvis.bat`**. Corvis opens in your browser.
   Keep the small black window open while you use him; closing it shuts Corvis down.
   (Prefer the terminal? `Corvis_Console.bat` still has the old menu.)

> Moving from the old Jarvis or Agent folder? Don't copy the old `.venv` folder over — Python
> environments break when moved. Setup_Corvis.bat makes a fresh one.

### Which model?

Quality depends almost entirely on the model, and the model depends on your GPU.
Check the Ollama library for the newest coding models, then pick by VRAM:

| VRAM | What to run | Expect |
|---|---|---|
| 8 GB | a 7–8B coder model | Small fixes, single files |
| 12–16 GB | a 14B coder, or a 30B MoE coder with offload | Solid multi-file work |
| 24 GB+ | `qwen3-coder:30b` or similar | Best local agentic coding |
| 48 GB+ / multi-GPU | 70B-class models | Strongest |

Change the model in `config.yaml`. If a model ignores tool calls, set `text_tool_mode: true`.

---

## 2. The chat app

Double-click `Start_Corvis.bat` and a chat page opens at http://127.0.0.1:8765.

- **Folder chip (top right):** choose where Corvis works. Paste a path (in File Explorer,
  right-click a folder and pick "Copy as path"). He can only touch files inside it.
  Choose **Corvis himself** to have him improve his own code instead.
- **Work log:** while he works you see each step (files read, edits, commands, his plan).
  Click a step's result to see the full output.
- **Allow / Deny:** commands that could change things wait for your answer, right in the chat.
- **Stop:** the send button turns into a stop button while he's working. He stops after the
  current step.
- **Chats are saved** in `data/conversations/` and keep their memory across restarts.
  Reloading the page mid-task is fine; it picks up where it was.
- **Restart button (bottom left):** reloads Corvis after he's updated himself.
- **Model status (bottom left):** green means the model is reachable. Red? Start Ollama.

Out of the box only this PC can open the chat. To use Corvis on your phone, see below.

## Corvis on your phone (iPhone and Android)

Corvis installs on your phone like an app: his own icon, full screen, no App Store.
This section is for Corvis running **on your PC**, so the PC must be on with the Corvis window
open. (For Corvis with your PC off, see [CLOUD_SETUP.md](CLOUD_SETUP.md).)

**Easiest: double-click `Setup_Phone_Access.bat`.** It sets your password, checks Tailscale
(and opens its download page if it's missing), turns on HTTPS, updates `config.yaml`, and
prints the address to open on your phone. The steps below are what it does, if you'd rather
do it by hand.

**1. Set an owner password** (once). Double-click `Set_Corvis_Password.bat`. Every phone or
other device has to sign in with it. The PC itself signs in automatically.

**2. Turn on remote access** in `config.yaml`:

```yaml
remote:
  enabled: true
```

**3. Choose how your phone reaches the PC:**

*Option A: from anywhere, privately (recommended).* Uses [Tailscale](https://tailscale.com),
free for personal use. Nothing is opened to the internet; only your own devices can connect.

1. Install Tailscale on the PC and on your phone, and sign in to the same account on both.
2. On the PC, in a terminal: `tailscale serve --bg 8765`
   (if it asks you to enable HTTPS for your tailnet, follow the link it shows, then run it again).
   It prints your address, like `https://my-pc.tail1234.ts.net`.
3. Add that name to `config.yaml`, then restart Corvis:
   ```yaml
   remote:
     enabled: true
     allowed_hosts: [my-pc.tail1234.ts.net]
   ```
4. On your phone, open that address and sign in.

*Option B: same Wi-Fi only.* Set `web.host: 0.0.0.0` in `config.yaml` and restart Corvis.
The Corvis window shows the address to open on your phone, like `http://192.168.1.20:8765`.
If Windows asks about the firewall, allow **Private networks**. Plain `http` works for
chatting; for the full app install and offline screen, Android needs Option A's https.

**4. Install it:**
- **iPhone:** open the address in **Safari**, tap **Share**, then **Add to Home Screen**.
- **Android:** open it in **Chrome**, tap **⋮**, then **Install app** (or **Add to Home screen**).

Photos you send from the phone can come straight from the camera or your photo library.
Use the sign-out button (bottom left of the menu) to sign a device out. Setting a new password
signs out every device.

*Your own domain (DuckDNS):* possible, but it means opening a computer to the internet.
Tailscale gives you the same "from anywhere" with far less risk, and it's what the cloud hub
uses too.

### Bots: a team of AI teammates
Corvis can have a team. Each **bot** is a teammate with a job you write in plain words
("find new leads in our CRM every morning and draft follow-ups; never send without my OK").

- **Make one:** the **+** next to *Bots* in the menu. Give it a name, its job, and what it can
  use: code, the web, its own computer, your PC.
- **Talk to one:** click it in the menu for a new chat, or write **@Name** in any chat to bring
  it into the thread. Bots catch up on what was said while they weren't involved.
- **They pass work along:** a bot hands part of a task to a teammate whose job fits better
  ("Looping in Sales Outbound…"), gets the result back, and carries on. You see every step.
- **They get smarter:** what a bot learns doing its job (who approves deals, how a customer
  likes to work) goes into *its own* memory and is used next time. The Memory panel shows
  which bot learned what. Facts about you are shared by every bot.
- **Routines:** work on a schedule, like "weekdays at 8:00, Sales Outbound checks for new leads".
  Add them in *Routines*, or just ask a bot ("every Monday at 9, summarise last week's commits").
  New routines need your OK. Each posts its result in its own chat, marked unread. On the cloud
  hub they run with your PC and phone off.
- **Their own computer:** a real web browser where Corvis runs, which stays signed in to your
  tools. Open **Computer** in the menu, go to a site, and sign in once (you see the screen and
  click and type on it). Bots never type passwords, and clicks that buy, pay, send, post or
  delete ask you first. Each bot works in its own tab; you can watch any of them.
  On the hub it's installed for you; on your PC run `pip install playwright` then
  `python -m playwright install chromium` to turn it on.

### Memory

Corvis remembers across all your chats:

- **Earlier chats:** every message, he looks through your saved chats for anything related and
  brings it along (you'll see a "Remembered earlier chats" step). He can also search them on
  purpose ("what did we decide about the inventory last week?") and open a whole old chat.
- **Facts about you:** when you tell him something lasting ("my games are in D:\Games",
  "I use Unreal 5 and C++") he saves it, and keeps it in mind in every chat. Open the
  **Memory** button (bottom left, notebook icon) to see, add or delete what he remembers.
- Everything stays in `data/` on your PC. Turn pieces off under `memory:` in `config.yaml`.

### Files and photos

Send Corvis files and pictures: click the paperclip, drag them onto the page, or paste a
screenshot straight into the message box (up to 10 files, 25 MB each).

- **Code, text, logs, JSON, CSV:** he reads them with your message (big files in parts).
- **PDF and Word documents:** he reads their text. **Zip files:** he sees what's inside.
- **Photos and screenshots:** coding models can't see, so Corvis asks a vision model to look
  and works from what it reports (including any text or error messages in the picture). He
  can ask it follow-up questions. Set one up once:
  `ollama pull qwen2.5vl:7b`, then in `config.yaml` set `vision: model: qwen2.5vl:7b`.
  Without one, files still work and he'll tell you he can't see pictures.
- He can also copy anything you send into your project ("put this texture in Assets/Textures").
- Attachments are kept in `data/uploads/` on your PC.

### Your whole PC

Corvis can work with files anywhere on your PC, not just the project folder: list, read,
search, create, move and delete. The **Files** button (bottom left, folder icon) lets you
browse your PC from any device, preview code and pictures, download files, ask Corvis about
a file, or start a chat working in a folder.

Guardrails:
- **Deleting** sends things to the Recycle Bin and always asks you first.
- **Moving**, **overwriting files outside the project**, and **creating scripts or programs
  outside the project** ask you first.
- **Never touched:** passwords and keys, browser data, password managers, Windows system
  folders, Program Files (read only), Startup folders, and Corvis's own code and password.
- Limit him further with `pc_access.roots` (e.g. only `D:/Games`) and hide folders with
  `pc_access.private`. Turn it all off with `pc_access.enabled: false`.

### Apps, games and installs

- "Open VS Code", "open Helldivers 2", "close Spotify", "what's open?" He finds apps
  through your Start Menu and your Steam library. Closing an app asks first.
- "Write a player controller and open it in VS Code": he writes the file, then opens it in
  VS Code for you.
- "Install Blender": he uses **winget** (Windows' own app catalog) first. If something isn't
  there, he finds the official website and downloads from it. **Installing or running anything
  always asks you first**, and he tells you which site a download came from.

### Voice

- **Talk to him:** tap the mic in the message box, speak, tap again. With
  `Install_Voice.bat` your speech is turned into text privately on your PC (Whisper).
  Without it, the mic uses your browser's speech recognition (Chrome sends audio to Google,
  Safari to Apple).
- **Hear him:** tap the speaker (top right), turn on "Read Corvis's replies aloud" and pick
  a voice. He picks a British male voice by default. On Windows, Microsoft Edge offers the
  most natural voices ("Ryan" or "Thomas", English UK).
- On a phone, the mic needs the https address from the phone setup.
- His manner (calm, warm, a bit witty, British) is set by `personality:` in `config.yaml`.

### Web

Corvis can search the internet and read pages, and cites his sources as links.

- Default search is DuckDuckGo: no account or key. If it ever stops working, switch
  `internet.search_provider` to `brave` (free API key from brave.com/search/api) or
  `searxng` (your own private search server).
- Only your search words leave your PC. He can't open addresses on your PC or home
  network from the web tools, and he treats web pages as information, never as orders.
- Turn it off with `internet: enabled: false`.

## 3. Terminal use

```bash
# One task
python -m corvis code --repo "D:/Games/MyGame" "add a stamina system to the player, drained by sprinting"

# Chat mode (keeps context between requests)
python -m corvis code --repo "D:/Games/MyGame"

# Corvis edits itself (one request, or leave the request off for interactive mode)
python -m corvis self-edit "add a plugin that runs Blender python scripts headless"
python -m corvis self-edit
```

- **Don't point `code --repo` at Corvis's own folder.** That edits Corvis with no safety
  branch, no tests and no approval. Corvis now refuses unless you add `--force`; use
  `self-edit` instead.

- Corvis can only touch files **inside `--repo`**.
- Safe commands (git status, tests, builds) run automatically. Anything else asks you first.
  `-y` auto-approves everything except the always-blocked list. Use it only on projects under Git.
- Put an `AGENTS.md` in any project with its style rules and build commands.
  Corvis reads it on every task. This is the biggest boost to quality you can give it.

---

## 4. How it works

```
corvis/
  __main__.py      CLI: code, self-edit, check
  config.py        loads config.yaml, wires everything together
  llm.py           local model client (Ollama / llama.cpp / LM Studio), tool-call parsing
  agent.py         the loop: model -> tool calls -> results -> repeat; context trimming, loop guard
  prompts.py       the system prompt (how Corvis works as an engineer)
  safety.py        workspace sandbox, command allow/ask/block policy
  selfedit.py      branch -> edit -> test -> show diff -> you approve -> merge
  web/
    server.py      the chat app's server, API, sign-in guard, restart
    auth.py        owner password, device sessions, rate limiting
    runs.py        runs Corvis in the background, live events, Allow/Deny
    static/        the chat page (HTML, CSS, JS), phone app manifest, icons, offline page
  conversations/
    store.py       saved chats (data/conversations/*.json)
  memory.py        facts about you + search over all saved chats (recall)
  internet.py      web search (DuckDuckGo / Brave / SearXNG) and page reading
  attachments.py   files you send: storage, reading text/PDF/Word/zip
  vision.py        looking at images through a vision model
  pc.py            files anywhere on the PC, with guardrails
  apps.py          finding, opening and closing apps and Steam games
  installs.py      winget installs and safe downloads
  voice.py         speech to text on the PC (Whisper)
  phone_setup.py   the Setup_Phone_Access.bat steps
  nodes.py         on the hub: paired PCs, the job queue, approvals relayed from the PC
  node.py          on the PC: Corvis Node (python -m corvis node) and link-pc
  supervisor.py    python -m corvis serve: restarts, and undoes a self-update that won't start
  hub_setup.py     the hub installer's questions: OpenRouter key, model, password
  config_edit.py   edits config.yaml sections without losing your comments
  bots.py          the team: each bot's job, abilities, color; @mentions
  routines.py      schedules and the scheduler that runs them
  computer.py      the bots' computer: a Chromium browser, live view, address guard
  tools/
    base.py        Tool + ToolRegistry (every capability is a Tool)
    plan.py        update_plan checklist
    files.py       read_file, write_file, edit_file, list_dir, delete_file
    search.py      find_files, grep
    shell.py       run_command
    git_tools.py   git_status, git_diff, git_log, git_commit
    memory_tools.py  search_chats, read_chat, remember, forget
    web_tools.py   web_search, fetch_page
    attachment_tools.py  read_attachment, look_at_image, save_attachment
    pc_tools.py    pc_list, pc_read, pc_find, pc_write, pc_make_folder, pc_move, pc_delete
    app_tools.py   find_app, open_app, close_app, list_open_apps, open_path, open_url,
                   search_installable, install_app, download_file
    node_tools.py  on the hub: the PC's tools, forwarded to Corvis Node while the PC is on
    team_tools.py  ask_bot: one bot hands work to another
    routine_tools.py  create_routine, list_routines, delete_routine
    browser_tools.py  browser_open/read/click/type/press/scroll on the bots' computer
  plugins/         drop-in tools, loaded automatically (Blender, Unreal, etc. go here)
deploy/
  install_hub.sh   sets up the cloud hub on Ubuntu (see CLOUD_SETUP.md)
tests/             runs without a model, using a scripted FakeLLM
```

### Adding a tool

Create `corvis/plugins/my_tool.py`:

```python
from corvis.tools.base import Tool, params

def register(reg, ctx):
    def say_hi(name: str) -> str:
        return f"Hi {name}"
    reg.register(Tool("say_hi", "Greets someone", params(["name"], name={"type": "string"}), say_hi))
```

Or just ask: `python -m corvis self-edit "add a tool that ..."`.

If a plugin has a bug, Corvis prints a warning at startup and keeps running; other
plugins still load.

### Renaming

The name lives in one place: `name:` at the top of `config.yaml`. Change it and the
prompt and console use the new name. (The Python package stays `corvis`.)

### Self-editing safety

- Needs a clean Git tree, so it never mixes with your uncommitted work.
- Won't start from a leftover self-edit branch.
- All changes land on an `corvis/self-edit-*` branch. If it crashes or you press Ctrl+C,
  partial work is saved on that branch and you're put back on `main`.
- Tests run, you see the diff summary, and nothing merges unless you say yes.
- After a merge he restarts on the new code. If it crashes within 90 seconds, the supervisor
  (`python -m corvis serve`, which Start_Corvis.bat and the hub use) puts the previous version
  back and tells you. Merged branches are kept, so you can always look at what changed.
- Undo any merged self-edit yourself with `git revert -m 1 HEAD`.

---

## Fonts

Corvis bundles Lora (headings, his name) and Source Code Pro (code), both under the SIL Open
Font License, so the app looks the same on every device, even offline. Body text uses each
device's own reading font. See `corvis/web/static/fonts/`.

## 5. Known placeholders

None. (The old `engineering_partner.py` stub that always answered "Code looks good!" was removed.)

## 6. Honest expectations

A local model won't match a frontier cloud model (the cloud hub uses one through OpenRouter). The harness (planning, precise edits,
build-and-fix loop, project notes) closes a lot of that gap, but the model sets the ceiling.
Good habits that help: give clear, scoped tasks; keep an `AGENTS.md`; let it run tests.

## 7. Next pieces (suggested order)

1. **Blender plugin**: run bpy scripts headless, generate and export models.
2. **Unreal plugin**: Python remote execution, create C++ classes, build with UBT.
3. **System control plugin**: open and close apps, window focus.
4. **Voice loop**: always-on listening, name-anywhere detection, local TTS.
5. **Memory + owner key**: encrypted local store, owner-only admin and shutdown.
6. ~~**Hub + phone access**~~: done in v1.0 (cloud hub, Tailscale, PC node).
7. **More nodes**: other devices (a laptop, a Raspberry Pi with a camera, robots) join the hub
   the same way your PC does, each lending its own tools.

## Corvis Mission Control and Creative Studio

Open **Mission Control** from the left sidebar or visit `/studio`. This increment adds a persistent creative-project brief planner, a local application detector, model/repository catalog, current Corvis chat-run overview, paired-node overview, and project event history. Project data is stored under `data/studio/jobs.json`; project output folders are reserved inside the configured workspace at `CorvisStudio/<project-id>`.

### Creative tools to install separately

Mission Control detects these applications if their command-line launchers are available on `PATH`: GIMP, Krita, Inkscape, darktable, RawTherapee, Blender, Kdenlive, FFmpeg, DaVinci Resolve, and Scribus. Detection is not installation and does not guarantee every feature is automatable on every operating system. Official project links are shown in the UI.

The model catalog links to Wan, LTX-Video, HunyuanVideo, and CogVideoX. A GitHub link is not a running model: local inference needs compatible model weights, a supported runtime, sufficient RAM/VRAM, and acceptance of the exact model license. Hosted generation requires an authorized provider and a working adapter. Keep secrets in environment variables; do not put keys in `config.yaml`.

### Current execution boundary

This release stores project briefs and workflow plans, detects local creative applications, exposes API endpoints for job creation/status/cancellation, and records explicit approval state. **It does not yet execute end-to-end AI image/video generation or automate all creative applications from a project brief.** The approval endpoint deliberately does not start an external process until an execution adapter is configured. The UI labels this boundary rather than inventing completion, progress, or artifacts. Live desktop streaming and coordinated local/cloud creative workers remain follow-on integrations; the existing computer-access and node features are separate and retain their existing safety controls.

### Tests

Run `python -m pytest -q`. The project tests exercise the creative job store and API. Browser automation tests may require the Playwright browser binary to be installed separately, per the existing setup instructions.


## Graphify knowledge graph (optional)

Corvis Mission Control can use [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) to build and query a local knowledge graph for code and project documentation. The integration supports graph build, natural-language graph queries, concept explanations, and shortest-path tracing. It reports provenance based on Graphify's output and does not claim a graph exists until `graphify-out/graph.json` is present.

Install the official CLI separately with `uv tool install graphifyy` (Python 3.10+ and `uv` required). Then open Mission Control and use the **Knowledge Graph** panel. Corvis does not silently install the tool or send code to a remote service. Code indexing is local; if you enable Graphify's optional semantic processing for documents/media, review its backend configuration and privacy implications.

For safety, Graphify operations from Mission Control are restricted to the configured Corvis workspace and run without a shell, with bounded execution time. Start by selecting a project folder inside that workspace.


## Unified Productivity Workspace (new)

Open **Workspace** from Mission Control or visit `/workspace`. This Corvis-native workspace adds persistent local notes, tasks, calendar events, Markdown documents, and email drafts, plus a Model Lab for comparing up to four models exposed by the configured OpenAI-compatible endpoint. Data is stored in `data/workspace/workspace.json` using atomic replacement.

The email feature currently manages drafts only; it does not connect to IMAP/SMTP or send messages. Calendar events are local; CalDAV sync is not yet implemented. Model comparison calls the configured model endpoint and may incur provider costs if that endpoint is remote. Model inventory and comparison require the endpoint to expose `/v1/models` and `/v1/chat/completions`.

### Feature coverage added from the Odysseus feature set

- Notes and persistent local workspace records.
- Task list with status, priority, and due date.
- Calendar event records with start/end times (local-only at present).
- Markdown-first document storage and editing.
- Email draft composition (no send/inbox connector yet).
- Model inventory and same-prompt model comparison.
- Existing Corvis capabilities retained: chat, agent tools, attachments, web research/search, conversations/sessions, memory, Graphify, Mission Control, and creative project planning.

Not represented as complete: IMAP/SMTP inbox and send, CalDAV synchronization, hardware-aware model downloads/serving, true blind comparison/synthesis, 2FA, and a full image editor/gallery. These require separate tested integrations rather than UI-only claims.

## Connectors and plugins (new)

**Connectors** link Corvis to outside apps and services, the same way Claude's connectors do: they
use MCP (Model Context Protocol), so any MCP server works. Open **Connectors** in the menu, then
pick one from the directory (GitHub, Filesystem, Fetch, Git, Memory) or add your own: a remote
server address (with an optional token) or a program on your PC (like `npx some-mcp-server`).

- Each connector's tools work in every chat, and for bots you give the **Connectors** ability.
- Anything that changes something in the connected app asks you first; tools the server marks as
  read-only run straight away. Per connector you can switch to "ask before every use" or "never ask".
- Tokens and settings are stored in `data/connectors.json` on this PC and never shown again in the app.
- Directory programs need Node.js (`npx`) or uv (`uvx`) installed.

**Plugins** bundle skills, slash commands, connectors and tools. They use Claude Code's plugin
format, so many Claude Code plugins install unchanged. Open **Plugins** in the menu to install from
a GitHub address (`owner/repo`), a folder, a `.zip`, or a marketplace (a Git repository with
`.claude-plugin/marketplace.json`).

- **Skills** (`skills/<name>/SKILL.md`): expert instructions Corvis loads when a task matches.
- **Slash commands** (`commands/<name>.md`): type `/name what to do` at the start of a message.
- **Connectors** (`.mcp.json`): start and stop with the plugin.
- **Tools** (`tools/*.py`, Corvis only): Python code. Installing a plugin with code asks you first,
  because it runs on your PC.

Try it: in Plugins → Marketplaces, add the folder `examples/marketplace` and install
**corvis-starter** (code-review and debugging skills, plus `/review`, `/explain` and `/plan`).
Turn either feature off with `connectors: enabled: false` or `plugins: enabled: false` in config.yaml.

## Blueprints: the hologram workshop (new)

Say **"Corvis, open blueprints"** in the chat (typed or with the mic), or click **Blueprints** in the sidebar.
The workshop opens at `/blueprints`:

- **Library** (left): `+ New` starts a blueprint from a template (blank, rover, robot arm, quad drone, arc reactor);
  click one to load it, the bin deletes it.
- **Hologram** (middle): drag to orbit, scroll to zoom. **Split** pulls the parts apart so you can see inside,
  **Isolate** shows just the selected part, **Move** lets you drag a part in 3D, **Fit** re-centres.
- **Part / Parts** (right): click any part to edit its name, shape, material, size, position, rotation,
  power, battery and how solid it is. Add new boxes, cylinders, spheres, cones, rings and capsules.
  Everything saves by itself.
- **Test**: run the design through a load on top, heat, a drop, wind, or a power/battery check, and drag the
  sliders to watch the results change live. Parts turn green (fine), amber (close to the limit) or red (fails),
  and the hologram acts it out (it bounces on a drop, tilts or tips in wind).
- **Talk bar**: ask Corvis to change, design or test the open blueprint ("make the arm carbon fibre and test
  it with 50 N"). His edits show up in the hologram as he makes them.

Corvis has matching tools (`create_blueprint`, `edit_blueprint`, `test_blueprint`, `open_blueprints`, ...),
and deleting a blueprint always asks you first. Blueprints are stored in `data/blueprints/`. The tests are quick
engineering estimates for spotting weak points early, not a replacement for real CAD/FEA simulation.
The 3D engine (three.js, MIT licence) is bundled in `corvis/web/static/vendor/three/`, so it works offline.
Turn the feature off with `blueprints: {enabled: false}` in config.yaml.
