# Corvis

**C.O.R.V.I.S.** — *Cognitive Operations & Reasoning Virtual Intelligence System*

A JARVIS-style AI companion with:

- **A fixed personality** — calm, loyal, dry wit, calls you "sir" (all editable in [`identity/corvis.yaml`](identity/corvis.yaml))
- **Long-term memory** — remembers you, your projects and your preferences between conversations (`data/memory.db`)
- **A self-image** — he knows what he looks like (gunmetal humanoid, cyan visor, glowing icosahedron core) and can **build his own 3D model** from it
- **Swappable bodies** — the same Corvis (same identity, same memories) can run in a terminal, a 3D avatar, or a robot, and move between them mid-conversation

His brain is Claude (Anthropic API, `claude-opus-5-5`).

![Corvis preview](docs/corvis-preview.png)

## How it fits together

```
identity/corvis.yaml  ──►  who he is (personality, self-image, safety rules)
data/memory.db        ──►  what he remembers
corvis/brain.py       ──►  Claude + tools: remember / recall / forget / describe_self
corvis/bodies/        ──►  where he lives:
    console.py              text only
    avatar.py               3D: writes avatar/corvis_avatar.json + a Blender build script
    robot.py                drive / look / stop / read_sensors, with hard speed limits
                            → SimulatedDriver (default) or Ros2Driver (/cmd_vel)
```

The brain never talks to hardware directly — each body offers its own tools, and Corvis
only reports an action as done once the body confirms it.

## Quick start

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...      # from https://console.anthropic.com

python -m corvis                  # chat in the terminal
python -m corvis --body avatar    # 3D avatar mode — ask him to "build yourself"
python -m corvis --body robot     # simulated robot — "drive forward a meter"
python -m corvis --body robot --ros2   # a real ROS 2 robot
```

While chatting: `/body avatar` (or `robot`, `console`) moves him into another body.
Typing just `stop`, `halt` or `freeze` halts all motion instantly, without waiting on the AI.

### Building his 3D self

In avatar mode, ask *"Corvis, build yourself."* He generates:

- `avatar/corvis_avatar.json` — engine-neutral spec (colors, proportions, voice, expressions) for Unity / Unreal / three.js
- `avatar/build_corvis.py` — run `blender -P avatar/build_corvis.py` to see him modeled in Blender
- `avatar/state.json` — live expression + current speech, for a renderer to animate

Change his look by editing `self_image` in `identity/corvis.yaml`.

### Putting him in a robot

Subclass `RobotDriver` in `corvis/bodies/robot.py` for your hardware (Arduino over serial,
Raspberry Pi motors, ROS 2, etc.). `RobotBody` clamps every command to its speed, turn and
duration limits no matter what the AI asks for.

## Tests

```bash
pip install -e ".[dev]" && pytest
```

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for voice, vision, a live 3D viewer, and the
Claude plugins / tools that help build them.
