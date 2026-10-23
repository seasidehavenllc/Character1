# Corvis roadmap

## Next features

| Feature | How |
|---|---|
| Voice (talk to him out loud) | Speech-to-text (e.g. Whisper / faster-whisper) into `Corvis.chat`; text-to-speech (Piper, ElevenLabs) in a body's `speak()` using `self_image.voice` |
| Wake word ("Corvis…") | openWakeWord or Porcupine in front of the voice loop |
| Vision | Send camera frames to Claude as image blocks from a `look_through_camera` robot tool |
| Live 3D viewer | three.js page that loads `avatar/corvis_avatar.json` and animates from `avatar/state.json` |
| Unity / Unreal avatar | Read `corvis_avatar.json` at startup; poll `state.json` for expressions |
| Smart home control | A `HomeBody`-style tool set (Home Assistant REST API) |
| Better memory recall | Add embeddings next to the SQLite full-text search |

## Claude add-ons that help build Corvis

Things you can enable in Claude Code / claude.ai while developing:

- **Unity plugin** (already available in this workspace) — skills for building the 3D avatar
  in Unity: UI, navigation (`initialize-ai-navigation`), audio, URP shaders, multiplayer.
- **Claude API skill** (`/claude-api`) — up-to-date reference for the Anthropic SDK Corvis's brain uses.
- **Adobe / Canva connectors** — concept art, logos and textures for his look (need to be signed in via claude.ai connector settings).
- **MCP servers** — e.g. a Blender MCP server lets Claude drive Blender directly to refine his model;
  a Home Assistant MCP server for smart-home control.
- **GitHub integration** — reviews, PRs, CI for this repo.
