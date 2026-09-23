# Unified Web Studio Implementation Log

## 2026-09-23 - Consolidated local verification

- Python compilation completed successfully. The focused high-risk suite passed 34 tests covering Studio stores/capabilities, session personas, history, managed tasks, page configuration and video path safety.
- `pnpm install --frozen-lockfile --offline`, Astro diagnostics and the production build completed successfully. The repository has no lint script or lint configuration, so no new lint framework was introduced for this release.
- The production build was atomically installed to the default `pages/Settings` entry; the former Settings page is retained at `pages/LegacySettings`. The source/lockfile/artifact integrity manifest matches, `git diff --check` reported no whitespace errors, and the focused secret/path scan found no matches.
- Browser checks covered every Studio route at 1440x900 and representative installed-artifact pages at 390x844. A design-sidebar overflow and an incomplete preview API fixture were fixed; the final installed design, GIF and settings views have no main-content horizontal overflow or console diagnostics.
- No running AstrBot test instance or authorized provider credentials were available. Real page-bridge routing, chat delivery and paid image/video generation remain explicitly unverified.
- `_conf_schema.json` remains an unrelated local modification and was not edited as part of the Studio work.

## 2026-09-23 - R1–R5 core implementation pending consolidated verification

- R1: canvas generation nodes, stable submission keys, saved-project job binding, project job recovery, edges and local undo/redo.
- R2: persisted Agent planning, restricted provider capability validation, signed confirmation and independently recoverable subjobs.
- R3: GIF frame jobs, repeatable frame ordering and timing, worker encoding with explicit cancellation, server compatibility export and managed output.
- R4: normalized free-region slicing and managed tiles, dual-image guided repair through the edit job, static image asset embedding, sandbox preview, revisions and ZIP export.
- R5: legacy settings mapping for chains, concurrency, storage, network and replies; Studio entry switch, old Settings fallback, integrity manifest, version and changelog.
- No tests, compilation, type checking, lint, build, browser checks or provider calls have been run during this concentrated implementation. `pages/Studio` remains a stale build until the single final verification.
- GIF direct chat delivery is not exposed without a reliable session send handle. Dual-image repair is guided editing, not a provider-native mask API. These limitations must remain visible in release notes and cannot be claimed as verified.

## 2026-09-22 - History and managed-asset handoff

- History previews now include the requested session scope, and the server
  validates that scope before returning legacy history bytes.
- Synthetic history cards no longer expose edit/video actions directly. The
  explicit preserve action creates a managed copy; normal asset actions then
  become available without depending on the bounded history row.
- Astro diagnostics, Python compilation, static build and artifact installation
  passed. No browser or live history-eviction verification was performed.

## 2026-09-22 - Preserve legacy history into Studio assets

- History cards now offer an explicit preserve action instead of calling asset
  pinning with a synthetic history ID. The action makes an independent managed
  copy with source ID/time metadata and session ownership checks.
- Reading the source bytes uses the history write lock to coordinate with
  eviction; missing/expired history fails without producing a fake asset.
- Direct edit/video actions on synthetic history entries are hidden until a
  managed copy exists. The copy can use the regular asset actions.
- Python compilation, Astro check and static build/install passed. No new tests
  were added; live preservation and the 100-image eviction flow are unverified.
- Canvas/GIF pickers still need explicit handling of synthetic history entries.

## 2026-09-22 - Project-owned asset deletion protection

- Explicit Studio asset deletion now refuses assets referenced by current
  projects or their retained revision snapshots, as well as pinned assets.
- Project saves validate asset ownership/existence inside the same SQLite write
  transaction as the project update. Asset deletion takes the write lock before
  checking references, preventing a concurrent save/delete from dangling them.
- A temporary SQLite check passed for current references, historical references,
  deletion after project removal and rejection of already-deleted references.
  No new test files were added.
- This covers managed Studio assets and explicit deletion only. Legacy history
  promotion, automatic cleanup integration and historical media quotas remain.

## 2026-09-22 - Project revision snapshots

- Project updates now preserve the previous document, retaining up to 20 old
  revisions per project. Historical content is available through a scoped API.
- SQLite write transactions lock before revision checks, preventing two writers
  from accepting the same revision. Project deletion also removes its snapshots.
- Web projects can load an old revision into the editor and save it as a new
  revision or copy; no automatic overwrite occurs.
- A temporary SQLite check passed for simultaneous saves, snapshot retention
  and cross-session rejection. Python compilation, Astro check and static
  build/install passed; no new test files were added.
- Historical asset bytes are not duplicated or pinned by these snapshots.
  Restoring documents referencing cleaned assets can still fail validation.
  Full historical media retention and browser workflow verification remain open.

## 2026-09-22 - Static web project recovery and export

- Added reopening of saved `web_replica` projects, revision-aware updates,
  save-as-copy, and download of a server-created ZIP.
- ZIP export revalidates the session scope and complete static manifest before
  writing entries; it never reads client paths or plugin source directories.
- Static project validation now rejects unsafe filename characters, reserved
  Windows names, duplicate paths, scripts, external network references and
  oversized content.
- Astro diagnostics, Python compilation, static build and artifact installation
  passed. Browser preview and real route/download integration remain unverified.
- S11 remains incomplete: no model-driven replica generation, sandbox preview,
  image asset embedding workflow or multi-version history UI.

## 2026-09-22 - Static web project storage foundation

- Added HTML/CSS text editing and a web_replica project save path.
- File manifests enforce extension, path, duplicate-name, content-size and
  session-owned asset-reference constraints. Files remain SQLite document data;
  nothing is written into plugin source directories or executed.
- The current substring rejection is not an HTML sanitizer or an isolation
  boundary. No preview is exposed; sandboxed rendering, model generation,
  reopening/version history and safe ZIP export remain outstanding.
- Python compilation, Astro diagnostics and static build/install passed.
  No browser or live API verification was performed.

## 2026-09-22 - Design project continuity

- The design workspace now filters session-local projects, opens existing
  design projects, saves with revision checks, and supports saving a copy.
- Switching projects prompts before discarding current edits. Session changes
  invalidate pending saves and slice responses.
- Astro diagnostics, Python compilation, static build and artifact installation
  passed. No browser interaction or real image-model call was performed.
- S11 remains incomplete: web replica generation, sandboxed preview, inpainting
  and project export safety still need implementation.

## 2026-09-22 - Web task completion semantics

- Web Studio jobs no longer report chat delivery as part of their completion
  condition. They are complete after generation and controlled archival succeed;
  the existing chat task path still requires successful sending.
- This prevents a successful Web result from being shown as failed merely
  because it was not sent to a chat event.
- A temporary task-manager smoke check and Python compilation passed. No new
  test file was added and no provider request was made.

## 2026-09-22 - Agent confirmation binding

- Added a non-executing plan preview mode. The service signs the normalized
  request, session, task count, idempotency key and expiry before execution.
- Submission requires the matching confirmation token within 15 minutes.
  Restarting the plugin invalidates outstanding confirmations.
- The confirmation MAC also covers the current normalized provider configuration,
  including model/defaults/credentials, without returning that configuration.
  Configuration changes before submission require another review. Python
  compilation passed for this addition; a post-validation execution race is not
  solved by this check alone.
- The Agent form now separates review from explicit fee acknowledgement and
  execution; changing any plan field invalidates its local confirmation.
- Failed submissions retain their original idempotency key for manual retries.
- Python compilation, Astro check and static build/install passed. No paid
  requests or browser/API integration tests were run.
- This does not complete S09: model-generated planning, persisted conversations,
  execution-time configuration leasing and restricted Agent tool orchestration remain.

## 2026-09-22 - GIF project workflow

- Added explicit session-local GIF project selection and independent project
  saving. Switching projects requires confirmation when frames are present.
- Missing frame assets now retain their sequence slots rather than shifting
  the indices used by reorder and delete actions.
- Responses from a previous session cannot replace the current GIF project.
- Encoding rejects more than 60 frames rather than silently truncating, caps
  total input at 100MB, and checks individual image pixel counts before decoding.
- Python compilation, Astro check and static build/install passed. No tests
  were added. Browser project recovery and encoding remain unverified.
- S10 remains incomplete: frame generation, browser-worker encoding, output
  sizing and delivery integration still need to be reconciled with the plan.

## 2026-09-22 - Durable task retention

- Pruning now targets only completed standalone jobs. Active, uncertain and
  plan-owned job records remain available for recovery and plan idempotency.
- Retired jobs leave a minimal durable key record so pruning cannot enable a
  repeat paid submission with the same idempotency key.
- Reusing an existing key with changed task parameters is rejected. Creation
  transactions acquire the SQLite write lock before checking existing keys.
- A temporary SQLite smoke check passed for active retention, retired-key
  rejection, changed-payload rejection and two concurrent identical submissions.
  No test files or frameworks were added. This is not full runtime acceptance.
- The configured ledger limit now bounds completed standalone records only;
  recovery records and retired keys are intentionally retained beyond that limit.

## 2026-09-22 - Creation workflow integration

- Connected legacy draw/edit/video presets to the creation composer, with
  confirmation before replacing a nonempty prompt.
- Exposed image size and resolution fields from the provider capability catalog.
  Provider changes reset parameters instead of retaining another provider's values.
- Added ordered reference previews, removal and movement controls, append uploads,
  reference-mode count feedback and first/last-frame labels.
- Upload responses from a previous session or an unmounted composer are ignored.
- Astro check and build passed. Browser interaction and live generation remain
  unverified; this does not complete S05/S06 or the full migration.

## 2026-09-22 - Preset editor and canvas cleanup

- Added a Studio preset editor for draw, edit and video preset lists. It uses
  revision checks, validates the legacy `name:prompt` format, preserves
  unsupported entries instead of overwriting them, and writes through the
  existing plugin configuration service.
- Corrected canvas node deletion so an inline delete action removes the node
  that was clicked, and corrected layer movement controls to match their labels.
- Python compilation, Astro diagnostics, static build and artifact installation
  passed. No new tests were added.
- Dynamic preset slash-command registration still occurs during plugin startup;
  newly added or removed commands may require a plugin restart, while the
  updated preset data is available to the web editor and existing dispatchers.

## 2026-09-22 - Prompt tools, asset handoff and grid slicing

- Added explicit AstrBot model selection for prompt optimization, tag conversion
  and image reverse prompting. Image input is resolved from session-owned assets;
  no generation is started automatically. Live model calls remain unverified.
- Added asset/canvas actions to carry a reference into edit or video creation.
- Added design grid slicing with bounded image dimensions and at most 32 PNG
  tiles. Tiles retain source asset and pixel-box metadata in the shared library.
  Partial persistence errors leave already-created assets available.
- Python compilation and Astro type checking passed. No new tests were added.
- Grid slicing is not web reproduction or inpainting. Those workflows, browser
  interaction checks and the complete release acceptance remain outstanding.
- Slicing was subsequently included in the preset-editor static build.

## 2026-09-22 - S00 started

### Repository baseline

| Item | Value |
| --- | --- |
| Working repository | E:\Codex\astrbot_plugin_aiimg_enhanced |
| Starting branch | master |
| Starting commit | f51be0e149bbde73ad750246fd4ced6e15797c29 |
| Migration branch | refactor/unified-web-studio |
| Plugin version | v4.11.4 |
| Yukina reference | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa |
| Nova reference | b8cd44cc083a0429f8df6a7c9fc5b935b7ae0731 |

### Pre-existing working tree changes

- _conf_schema.json was already modified before this migration started. It is user-owned and must not be restored, reformatted, staged or committed as part of the Studio rebuild unless the user explicitly requests it.
- docs/WEB_STUDIO_REBUILD_PLAN.md was created for this migration and was untracked at branch creation.

### Completed in this entry

- Created the migration branch.
- Pinned both reference repository commits.
- Inventoried current commands, LLM tools, Web surfaces, data stores and provider templates.
- Recorded source-license boundaries and that no Yukina or Nova source has been copied yet.
- Defined a small acceptance set. Existing tests are reused; no coverage target or large E2E suite is introduced.

### Operational work still required before data migration

The current workspace does not identify a running AstrBot instance or its actual plugin data_dir. Therefore no runtime data backup has been claimed.

Before S04 introduces persistent Studio data, the operator must:

1. Locate the test instance's actual data/plugin_data/astrbot_plugin_aiimg_enhanced directory.
2. Stop that test instance from writing.
3. Back up configuration, personas, persona_refs, image_history.sqlite3, history_images, session_personas.sqlite3, generated images and videos.
4. Restore the backup into a disposable test directory and open at least one restored history image.
5. Record the backup path and restore result here. Never commit the backup.

### Verification performed

- Baseline suite before implementation: 217 passed, 5 subtests passed in 27.12s.
- Runtime backup and restore verification: pending because no AstrBot runtime path is available in this workspace.

## 2026-09-22 - S01 completed

Implemented:

- Video wrapper pages are checked by the network policy before every request and redirect.
- Wrapper inspection is capped at 512 KiB instead of loading an unbounded response.
- Video cache cleanup ignores partial files and protects files being downloaded or sent.
- Known accepted video tasks raise a no-fallback error after polling or download failure.
- Ambiguous submit transport failures for OpenAI Videos, Agnes, MiniMax H3 and xAI are not automatically retried or switched to another provider.
- Repeatable AstrBot file tokens are now limited to reference-image tokens registered by this plugin. Other tokens delegate to the original AstrBot handler.
- Changed provider instances are leased while in use and close after the last active task releases them.
- OpenAI video JSON fallback preserves boolean, numeric, list and object values from extra_form.
- Legacy Grok, Grok2API, Flow2API and custom video adapters now stop on ambiguous successful or interrupted submissions instead of regenerating automatically.
- OpenAI backend-specific cache cleanup shares the same active-media leases as VideoManager.

Focused verification:

- Final focused S01 run: 83 relevant tests passed in 2.76s.
- Added six focused cases covering URL blocking, active-file cleanup, accepted-task fallback, ambiguous-submit retry, provider retirement and typed JSON fallback. Existing tests cover the remaining changed paths.

No second full-suite run was performed at this phase; the plan reserves that for release.

## 2026-09-22 - S02 in progress

Implemented:

- Added web/ as a static Astro plus React source project.
- Added one React Studio root with hash navigation for Create, Tasks, History, Personas and Providers.
- Reused the existing AstrBotPluginPage bridge and existing authenticated Pages APIs. Browser code has no provider keys and makes no upstream generation requests.
- Added a Yukina-derived shell and theme-token structure without Swup, Svelte, Tailwind, blog, RSS, sitemap, Pagefind or external font/CDN requirements.
- Added scripts/build_studio.mjs for atomic, path-checked installation into pages/Studio while retaining pages/Settings.
- Added a preview-only fake bridge gated by the explicit preview=1 query parameter. Normal access still requires the real AstrBot bridge.
- Used the plugin's own logo.png only. No Yukina or Nova media was copied.

Build and visual evidence:

- Portable Node v22.23.2 was downloaded outside the repository and verified against the official SHA256 list. It does not modify system PATH.
- Frontend dependency audit: 0 vulnerabilities after moving to Astro 7.3.3.
- Astro check: 0 errors, 0 warnings and 0 hints.
- Static build: 1 page built successfully and installed under pages/Studio.
- Desktop viewport 1440 by 900: no horizontal overflow.
- Mobile viewport 390 by 844: no horizontal overflow; hash navigation and history grid work.
- Browser console: no warnings or errors.

Still required to complete S02:

- Open pages/Studio through a real AstrBot plugin details page and confirm the host mount path, authenticated bridge and sibling legacy Settings link.
- Record the real test URL and authentication result here.

## 2026-09-22 - S03 completed

Implemented:

- Added a server-owned provider capability catalog derived from provider templates and explicit `studio_capabilities` declarations.
- Capability responses distinguish supported, unsupported and unknown behavior without inferring features from model-name substrings.
- Added protocol and last-verified metadata, operation support, reference modes and image limits, accepted media types, duration, aspect ratio, size, resolution, streaming and cancellation fields.
- Kept xAI text, first-frame and multi-reference modes distinct; reference mode remains capped at 720p.
- Kept OpenAI Videos reference field modes distinct and marks multipart `input_reference` unavailable in JSON-only mode.
- Recorded MiniMax H3 text, reference and first/last-frame limits separately, including the 1080p restriction for frame mode.
- Custom video templates expose video generation but leave undeclared reference and parameter behavior unknown; administrators can declare exact capabilities explicitly.
- Added an authenticated read-only `get_provider_capabilities` Pages API.
- Studio creation modes and provider choices now come from capability data instead of template-name guesses in the browser.
- Existing Settings provider catalog remains in place, and configuration save behavior still preserves unknown provider fields.

Focused verification:

- Capability catalog plus existing config round-trip tests: 5 passed. Only two new focused tests were added.
- Astro check: 0 errors, 0 warnings and 0 hints.
- Astro static build completed successfully.
- Installed the rebuilt static page atomically into `pages/Studio` after stopping only the verified local preview process that held the old directory open.
- Preview smoke check at 1440x900 and 390x844: no horizontal overflow; provider filtering, long protocol wrapping, Agnes reference limits and browser console state were checked.
- No full Python suite was run for this phase.

## 2026-09-22 - S04 in progress

Implemented the first S04 slice:

- Added `studio.sqlite3` job ledger with version-compatible additive table creation, request snapshots, result metadata, terminal state timestamps and idempotency keys.
- Added `StudioGenerationService` for Web text-to-image and edit requests, reusing the existing draw/edit routers, provider registry, task manager and image history.
- Added authenticated Pages endpoints for create/list/detail/cancel Studio jobs.
- Repeated requests with the same idempotency key return the original job and do not start another worker.
- On plugin startup, jobs left queued or running by a previous process are marked `interrupted`; they are never silently re-submitted.
- Added Web API client contracts for durable Studio jobs; the existing task surface remains intact.
- Video job submission is intentionally deferred to S06 so the existing video-specific accepted-task and download safeguards are reused instead of duplicated.

Focused verification:

- Job-store, capability-catalog and config round-trip checks: 6 passed.
- Python compile check passed for changed S04 modules.
- Astro check remains 0 errors, 0 warnings and 0 hints.
- Studio preview check: target-session selector and image submit button work in the preview bridge; desktop viewport has no horizontal overflow.

## 2026-09-22 - S05/S06 in progress

Implemented the next workbench slice:

- Web image jobs now support text-to-image, edit with uploaded multi-reference paths, and selfie mode using the selected session's persona references.
- Reference uploads use the existing base64 fallback API and remain under the plugin data directory.
- Web video jobs now select the configured video backend, reuse its polling and accepted-task safeguards, download the result through `VideoManager`, and expose only a guarded job-media download endpoint.
- Job media paths are checked against the plugin `videos` directory before sending a file response; arbitrary local paths are rejected.
- Studio task rows show durable job state, cancellation and completed video download actions.

Focused verification:

- Python compile check passed for changed orchestration and Pages API modules.
- Astro check: 0 errors, 0 warnings and 0 hints.
- Astro static build completed successfully.
- Existing focused job/capability/config checks: 6 passed. No additional broad test suite was added.

## 2026-09-22 - S04/S05/S06 authorization and session slice completed

Implemented:

- Studio scope is now accepted only when it matches a session already observed by the plugin through task, history, persona-selection or Studio ledgers; invented four-part scopes are rejected.
- Studio job detail, cancel and video download require the matching scope.
- Studio asset list, upload, preview, download, pin, delete and GIF creation require the matching scope.
- Studio project list, detail, save and delete require the matching scope; saving an existing project across sessions is rejected.
- Asset-backed reference images are checked for both image type and owning session before edit or video generation.
- The web client uses `asset_id` for newly uploaded references instead of legacy persona-reference paths.
- The selected session is now a Studio-wide state shared by create, assets, canvas, GIF, design and Agent views. Switching it reloads scoped jobs, assets and projects.
- Static rendering no longer reads `localStorage` on the server, so the Astro production build is reproducible.

Verification performed:

- `python -m compileall -q handlers core/studio`: passed.
- Astro check: 0 errors, 0 warnings and 0 hints.
- Astro static build and atomic installation into `pages/Studio`: passed.
- Temporary-directory storage smoke check passed for scope indexing and cross-session project-update rejection; it also caught and fixed the first-save project ID closure bug.
- `git diff --check`: passed; only Git's existing line-ending normalization warnings remain.
- No broad test suite or additional test matrix was added for this slice; the bundled Python runtime does not include `pytest`.

Remaining before the next phase:

- Resume/interrupted Studio jobs with retained upstream IDs and separate resend delivery.
- Persona profile/reference-role editing in Studio.
- Provider template editing with secret replacement/clearing and unknown-field round-trip.
- Backend Agent plan records instead of browser-side repeated job creation.
- Deeper Nova canvas, GIF tuning and design/slice workflows.

## 2026-09-22 - S07/S08 Studio management slice completed

Implemented:

- Added Studio persona APIs for list, create, edit, delete and reference-image upload.
- Reused the existing `PersonaManager`, `PersonaRefService` and `session_personas.sqlite3`; no parallel persona database was introduced.
- Studio persona editing supports base prompts, ordered references and the existing identity/clothing/pose/scene responsibilities.
- Deleting a persona selects a valid remaining global default and clears stale session selections that pointed to the deleted persona.
- Added a Studio persona editor while keeping per-session persona selection separate from the global default.
- Added a provider editor that round-trips ordinary and unknown template fields through JSON.
- Provider secrets are redacted in browser responses; replacement and clearing require explicit per-field operations.
- Provider saves use the existing config persistence and registry hot-reload path, so chat and Studio continue to share provider instances.

Verification performed:

- Bundled Python compile check for `handlers`, `core/studio` and session-persona storage: passed.
- Astro check: 0 errors, 0 warnings and 0 hints.
- Astro static build and installation into `pages/Studio`: passed.
- `git diff --check`: passed; only existing Git line-ending normalization warnings remain.
- Added no broad test suite. Direct API import smoke testing is unavailable in the bundled runtime because `quart` is not installed; compile and frontend checks remain valid.

## 2026-09-22 - S04/S06 recovery and delivery slice completed

Implemented:

- Persisted the selected video provider, upstream task ID, accepted state, delivery state and Agent plan metadata in the Studio job ledger.
- Added an authenticated `resume_job` endpoint and a task-center action that continues polling an already accepted upstream video task; it never submits a new generation request.
- Added xAI request-ID recovery through the native polling endpoint, alongside the existing OpenAI Videos, Agnes and MiniMax H3 recovery paths.
- Kept providers without a durable upstream task ID explicit as non-resumable instead of guessing or regenerating.
- Added strict persona edit ID validation so an edit cannot silently become a second profile when the client changes `original_id`.

Verification performed:

- Bundled Python `compileall` for `core` and `handlers`: passed.
- Astro check: 0 errors, 0 warnings and 0 hints.
- No new test file was added for this slice; existing focused tests remain the regression boundary.
- The bundled runtime does not include `quart` or `pytest`, so direct Pages API execution and a full Python test run remain environment-dependent.

Remaining before release:

- Complete the deeper Nova-derived canvas editing, prompt tools, Agent confirmation details, GIF frame tuning and sandboxed design workspace described in S08-S11.
- Perform one real AstrBot route check and one provider-backed generation check with approved credentials; mark unavailable providers as untested rather than simulating paid traffic.

## 2026-09-22 - S08 canvas and GIF editing slice completed

Implemented:

- Upgraded the Studio canvas from a static node list to an editable surface with pointer dragging, selection, scale, rotation, layer ordering, deletion and bounded undo/redo history.
- Canvas projects now write `version: 2` documents while still reading the earlier `version: 1` node shape.
- Added GIF frame preview and playback, explicit frame ordering, frame removal, per-frame duration and loop controls.
- GIF projects persist ordered `frames`, `duration_ms` and `loop`; generated GIF metadata records the exact ordered asset IDs.
- Added server-side project-document validation for canvas, GIF and design asset references, document size and collection limits. Project and GIF references must belong to the current Studio session.
- Kept project optimistic locking and the legacy Settings route unchanged.

Verification performed:

- Bundled Python `compileall` for `core` and `handlers`: passed.
- Astro check: 0 errors, 0 warnings and 0 hints.
- Static build and atomic installation into `pages/Studio`: passed.
- Built-asset scan found no local development paths, API keys or hard-coded localhost endpoints.
- No broad test suite or new test matrix was added for this UI slice.

## 2026-09-23 - Static preview implementation (not security acceptance)

## Concentrated implementation queue (unverified)

Per the user's latest direction, no tests, builds, type checks or browser
acceptance are run until the remaining core modules have been implemented.

- Added managed-media project ZIP export for canvas/GIF/design, with scope
  authorization, generated archive paths and a 100MB media limit.
- Canvas can submit an image job tied to its saved project; uncertain submission
  retries in the mounted editor retain the same idempotency key.
- Canvas project jobs are fetched independently of the global recent-job list.
  Reopening a project polls existing jobs rather than submitting new ones.
- New Studio image results are copied to managed storage before history insertion.
- Canvas can insert completed project-job results into its editable nodes.
- Still unfinished: persisted pre-submit canvas intents, pagination past 100
  project jobs, generation-node parameter snapshots, connections and undo,
  Agent planning/persistence, GIF worker/frame generation/delivery, design
  embedding/inpainting and remaining settings mappings.
- All changes in this queue are unverified; static release artifacts are stale.

Workflow follow-up:

- Web replica model selection now uses the existing redacted AstrBot provider
  catalog rather than requiring a manually typed ID.
- Design save, slicing and model reference input promote history images to
  managed assets; a session-local cache avoids repeat promotion during editing.
- Scope changes clear pending draft/reference state and ignore stale responses.
- Empty starting file lists are accepted for generation; non-object documents
  are rejected before model invocation.
- Astro check/build, Python compile and static artifact installation passed.
  These do not substitute for live API or browser acceptance.

Follow-on implementation:

- Added an explicit model-call action for creating/revising static web file
  drafts through an AstrBot text/vision provider, without tool access.
- Requires scope ownership for optional image references, validates the returned
  manifest, limits output size and rejects overlapping calls in one session.
- Generated files replace the editor only after success; saving is separate.
  UI requests confirmation of possible model charges; no automatic retry.
- Astro check/build and Python compilation passed; installed static artifacts.
  No live model call was made. Durable request recovery, model selection UI,
  reference embedding and browser security acceptance remain unfinished.

- Added a static HTML/CSS preview to the design editor using an empty-sandbox
  iframe, no same-origin or script permissions, and no-referrer policy.
- Reconstructs an allowlisted document before rendering, omitting navigation,
  embedded documents, event handlers and external image URLs. CSP precedes
  generated content and blocks resource requests except inline raster images.
- Astro check and build passed; static output installed into pages/Studio.
  Python compileall passed after correcting a Windows wildcard invocation.
- Browser adversarial and desktop/mobile verification has NOT been performed.
  These checks remain required before claiming the isolation boundary verified.
- S11 is still incomplete: model-driven replica generation, image embedding,
  inpainting and real AstrBot route acceptance remain outstanding.

## 2026-09-22 - S08 canvas/GIF module consolidation

Implemented:

- Canvas imports now block conflicting drag/save operations while a history image is being promoted to a managed asset.
- GIF projects support repeated source assets as separate frames, preserving intentional repetition instead of treating asset IDs as a set.
- GIF projects persist `frame_durations_ms`; frame reorder and removal keep the duration list aligned with the frame list.
- GIF playback uses each frame's own duration, with a default-duration fallback for older projects.
- GIF export validates per-frame durations, normalizes mixed-size frames onto one centered canvas, and records the frame timing metadata.
- Existing GIF projects using `duration_ms` remain readable and can be upgraded on the next save.

Focused verification:

- Astro check: 0 errors, 0 warnings and 0 hints.
- Static Astro build completed successfully.
- Python compile check passed for the changed Pages API and storage modules.
- A temporary Pillow smoke check passed for mixed dimensions, repeated source frames and per-frame durations.
- No live AstrBot route or paid provider request was performed.
