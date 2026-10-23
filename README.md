# Corvis

**C.O.R.V.I.S.** — *Cognitive Operations & Reasoning Virtual Intelligence System*

A JARVIS-style AI companion **and senior software engineer**. He helps you build projects
beyond your current skill level: he plans, writes, runs and debugs real code in any
language, learns from his own mistakes, and explains what he did so you learn too.

![Corvis web app](docs/corvis-web.png)

- **Swap AI models like the Claude and ChatGPT apps** — Claude Opus 5.5, Fable 5.1, Sonnet 5.5, Haiku 5.5, or ChatGPT, from a dropdown. The conversation carries over when you switch.
- **Workshop** — reads, writes and edits files in a project folder and runs commands (installs, programs, tests, git). You approve commands.
- **Self-learning** — saves engineering lessons (bug causes, fixes, techniques) and recalls them before new work, so he gets better on your projects over time.
- **Up-to-date knowledge** — on supported Claude models he can search the web and read documentation pages.
- **Personality and memory** — calm, loyal, dry wit, calls you "sir"; remembers you and your projects between conversations.
- **Self-image and bodies** — knows what he looks like, can build his own 3D model, and can move into a robot body.

![Corvis avatar](docs/corvis-preview.png)

## Quick start

```bash
pip install -e ".[chatgpt]"                 # drop [chatgpt] if you only want Claude
export ANTHROPIC_API_KEY=sk-ant-...          # https://console.anthropic.com
export OPENAI_API_KEY=sk-...                 # optional, for ChatGPT  https://platform.openai.com

python -m corvis --web                       # the web app at http://127.0.0.1:8800
python -m corvis                             # or chat in the terminal
```

Projects Corvis builds go in `workspace/` (change with `--workspace /path/to/folder`).

**Terminal commands:** `/models`, `/model <id>`, `/effort <low|medium|high|xhigh|max>`,
`/body <console|avatar|robot>`, `exit`. Typing just `stop`, `halt` or `freeze` halts any
robot motion instantly.

## How it fits together

```
config/models.yaml     the models you can switch between (add/remove freely)
identity/corvis.yaml   who he is: personality, expertise, work method, self-image, safety rules
data/memory.db         what he remembers, including lessons he has learned
corvis/
  brain.py             conversation + tools: remember / learn / recall / forget / describe_self
  providers.py         Claude (Anthropic API) and ChatGPT (OpenAI API) behind one interface
  workshop.py          list / read / write / edit files, run commands — confined to the workspace
  bodies/              console, 3D avatar (Blender + engine JSON), robot (simulated or ROS 2)
  web/                 the web app (no extra dependencies)
```

## Safety

- File tools can't reach outside the workspace folder.
- Commands are **not sandboxed** — they run on your computer with your permissions. That's
  why each one needs approval: the terminal asks y/N, and the web app has an
  **Allow commands** switch (off by default). Point `--workspace` at a dedicated folder.
- Robot bodies clamp every movement to hard speed, turn and duration limits.

## What "self-learning" means here

Corvis doesn't retrain the AI model. His skill comes from the model you pick; what he
learns is stored as memories and lessons that are given back to him in later conversations.
In practice that means he remembers your projects, your preferences, and the fixes that
worked, and stops repeating the same mistakes.

## Tests

```bash
pip install -e ".[dev,chatgpt]" && pytest
```

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for what's next.
