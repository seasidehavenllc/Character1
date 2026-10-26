# Corvis v2 foundation: reasoning, beliefs, experience, and model routing

This update is intentionally incremental and keeps the v1.1 application structure.

## Added

- `corvis/reasoning.py`: task-adaptive deliberation hint and structured decision record. The system prompt asks for evidence-aware conclusions, uncertainty, and concise rationale rather than hidden chain-of-thought.
- `corvis/beliefs.py`: persistent source-aware belief ledger with confidence, evidence, revision history, search, context retrieval, and deletion.
- `corvis/experience.py`: append-only task-outcome journal that records whether an outcome was verified and what lesson was drawn.
- `corvis/model_router.py`: provider-neutral routing and sequential fallback for clients implementing Corvis's existing OpenAI-compatible `ChatLLM` interface.
- `tests/test_cognition.py`: focused tests for the new components.
- Agent prompt updated with Corvis's reasoning philosophy.
- Agent context now retrieves relevant belief records and task experiences alongside existing chat memory.

## Important limitations

- The router supports OpenAI-compatible endpoints, including many local servers and compatible gateways. It is not a native adapter for every provider's proprietary API. Add and test native provider adapters before configuring a provider that does not expose the compatible interface.
- The belief store does not automatically infer or save opinions from every answer. Automatic belief extraction should be added only with evidence validation, user controls, and tests to avoid turning model speculation into persistent belief.
- Experience records are not automatically created for every tool call yet. Record an experience only after observing and preferably verifying a task outcome; do not treat failure alone as proof of its cause.
- Significant-action approval remains governed by the existing safety/tool policy. This change does not relax it. Review every tool and remote-node path before enabling unattended operation.
- This is a software foundation, not a claim of consciousness or guaranteed correct reasoning.

## Verify

From the project root, run:

```bash
python -m pytest -q
```

If browser tests report that Playwright's browser executable is missing, install the browser required by the existing project instructions and rerun those tests. Provider credentials, local model availability, Windows-specific computer controls, and cloud-node deployment must be tested in the target environment.

## Next engineering steps

1. Integrate an explicit experience-recording point after verified task completion.
2. Add user-facing review/edit/delete controls for beliefs and experiences.
3. Add native OpenAI, Anthropic, and Gemini provider adapters as separate, tested modules; keep keys in environment variables or the existing secret configuration mechanism.
4. Add policy tests that prove every significant action requires approval across chat, bots, routines, and remote PC paths.
5. Add an evaluation set for evidence quality, belief revision, factual accuracy, task success, cost, and latency.
