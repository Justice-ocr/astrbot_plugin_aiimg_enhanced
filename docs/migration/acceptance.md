# Unified Web Studio Acceptance

This is a release checklist, not a request for a large test suite. Reuse existing tests and perform one concise manual pass for each main workflow.

## Non-negotiable invariants

- User changes in _conf_schema.json remain untouched unless explicitly requested.
- Existing chat commands and LLM tool names continue to work.
- Existing provider fields, including unknown extension fields, survive load and save.
- Browser code never receives provider API keys and never calls upstream generation endpoints directly.
- A task that may already have been accepted upstream is not submitted again automatically.
- Chat and Web generation share provider registry, personas, references, tasks and history rules.
- Image history remains capped at 100 and displays newest-first with session and generation time.
- Session persona selection remains isolated by AstrBot session.
- Studio job, asset and project reads/writes require a known matching session scope; missing or invented scopes are rejected.
- Legacy Settings remains available until Studio has completed one stable release cycle.

## Minimal automated checks

Only add or change tests where existing coverage is insufficient:

1. Media URL safety and redirect validation.
2. No duplicate paid submission after ambiguous submit or poll failure.
3. Typed request payloads preserve strings, booleans, numbers, lists and objects.
4. Active media is not deleted by cleanup.
5. Session, persona and history authorization boundaries.

Run affected existing tests during development. Run the existing full suite once at baseline and once before release. No coverage percentage gate is required.

## Manual workflow pass

One successful workflow may satisfy multiple rows.

| Area | Check | Evidence |
| --- | --- | --- |
| Shell | Studio loads through AstrBot's authenticated plugin route | URL and one screenshot |
| Responsive | No overlap at one desktop and one mobile viewport | Two screenshots |
| Image | Submit one text-to-image task and see progress, result and history | Task ID and result |
| Edit | Submit one edit with references and preserve reference order and roles | Task details |
| Selfie | Effective session persona and persona references are visible | Task details |
| Video | Submit one task; polling, recovery and download do not resubmit | Log excerpt and job record |
| Tasks | Cancel a local task and inspect clear state text | Task record |
| History | Newest is number 1; session and time are present; cap stays 100 | History screenshot |
| Canvas/GIF | Drag or transform a canvas node, undo/redo, reorder GIF frames, save and reload the project | Project record and one UI pass |
| Settings | Read and save one provider without losing fields | Before/after diff |
| Fallback | Disable Studio and open legacy Settings | URL or screenshot |

Current migration evidence (2026-09-22): Python compile, Astro check, static build/install, artifact scan and diff check pass. The xAI recovery path is implemented beside OpenAI Videos, Agnes and MiniMax H3; the first S08 canvas/GIF editing slice is installed. Live AstrBot route, real provider generation, project reload and restored runtime-data backup remain environment-dependent manual checks.

Real paid generation is performed only with user-approved credentials, model and cost. If unavailable, mark that provider not live-tested; do not create a mock platform solely for it.

## Phase gates

- S00: baseline, source manifest and feature inventory exist; runtime backup is verified or explicitly pending.
- S01: the five high-risk backend invariants above are fixed with focused evidence.
- S02: authenticated Yukina-based shell opens without replacing legacy Settings.
- S03-S07: current generation, provider, persona and configuration functions are available in Studio.
- S08-S11: Nova-derived workbench features share the same assets and jobs instead of separate services.
- S12: build artifacts are reproducible, migration is additive, and fallback is exercised once.
