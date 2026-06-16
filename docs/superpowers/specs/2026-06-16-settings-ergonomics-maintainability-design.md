# Settings Ergonomics And Maintainability Design

## Goal

Improve the Settings page ergonomics for persona reference image workflows and make the backend page API easier to maintain without changing the core image generation path.

## Scope

This change focuses on the AstrBot plugin Settings page and the backend routes that serve it:

- Persona editor layout and reference image upload flow.
- Settings page JavaScript structure around persona references and output-size helpers.
- `handlers/pages_api.py` responsibilities for config save, persona references, and registry reload.
- Tests for config normalization, reference image handling, encoding, and output-size consistency.

Out of scope:

- Changing provider generation/edit behavior.
- Changing command syntax.
- Redesigning the whole plugin visual identity.
- Splitting the entire `main.py` module.

## Frontend Design

The persona editor remains a modal, but it becomes a clearer two-column workspace.

Left column:

- Persona ID.
- Persona display name.
- Persona base prompt.
- Any existing primary persona fields.

Right column:

- A sticky top toolbar containing the reference image upload entry.
- Upload button, hidden file input, upload status text, and a clear-all command.
- Reference images below the toolbar in an auto-flow grid.
- Each image keeps its original aspect ratio and has compact actions for delete and open/copy path where existing code supports it.

The upload control moves out of the left form area and into the right reference panel top bar. This makes the relationship between upload action and image list obvious and keeps form editing from shifting when upload status changes.

The reference panel should handle:

- Empty state with a short actionable hint.
- Uploading state with disabled upload button.
- Partial failure state that reports how many images succeeded and failed.
- Broken preview state with a visible fallback instead of a blank area.

## Frontend Structure

The current `pages/Settings/app.js` is large. The first maintainability pass should split only the highest-change persona/reference code while keeping existing runtime behavior:

- `pages/Settings/app.js`: application state, initialization, tab rendering, save/load orchestration.
- `pages/Settings/persona_refs.js`: reference preview loading, upload coordination, modal reference list rendering helpers.
- `pages/Settings/output_sizes.js`: output-size data loading, normalization, option rendering.

The split should use ES modules because `index.html` already loads `app.js` as a module. Existing global IDs and bridge API names remain unchanged.

## Backend Design

`handlers/pages_api.py` should become a route layer, not the place where all page-service logic lives.

Add `core/persona_ref_service.py`:

- Validate image bytes by magic header.
- Infer extension and MIME type.
- Generate safe reference filenames.
- Save uploaded image bytes to `data_dir/persona_refs`.
- Convert base64 data URLs in persona config into saved local files.
- Safely read local reference image previews as data URLs.
- Reject unsafe paths.

Add `core/pages_config_service.py`:

- Normalize provider payloads from the Settings page.
- Convert frontend `__type` into persisted `__template_key`.
- Apply supported top-level config sections from a save payload.
- Detect provider changes and return the data needed for registry reload.

Keep registry reload in the plugin class because it owns the registry instance, but wrap it in a small helper so `_pages_save_config` reads as a short sequence:

1. Parse JSON.
2. Normalize and apply config changes.
3. Save persona references.
4. Reload registry when needed.
5. Persist config.
6. Return active persona and provider IDs.

## Data Flow

Persona reference upload:

1. User clicks the right-panel upload toolbar.
2. Frontend sends each file through `upload_ref_image`.
3. Backend validates bytes and saves to `persona_refs`.
4. Backend returns `{ success, path, url }`.
5. Frontend appends `path` to the modal reference list and caches `url` for preview.
6. Saving persona writes only paths, not base64 payloads.

Reference preview:

1. Frontend receives a local reference path.
2. Frontend asks `get_image_b64`.
3. Backend checks path safety and image type.
4. Backend returns a data URL.
5. Frontend caches and displays it.

Save config:

1. Frontend sends compact JSON with reference paths.
2. Backend normalizes sections and provider configs.
3. Backend converts any legacy data URL references to local files.
4. Backend updates persona manager.
5. Backend reloads changed provider cache only when provider config changed.

## Error Handling

Frontend errors should be actionable:

- Upload route unavailable: show "上传接口不可用，请保存后刷新重试".
- Unsupported file type: show "仅支持 PNG/JPEG/WebP/GIF".
- Save failure: keep edits in memory and show the backend message.
- Preview failure: keep the reference path visible and show a broken-preview placeholder.

Backend errors should avoid leaking absolute paths or secret values:

- Unsafe path returns a 400 JSON error.
- Non-image upload returns a 400 JSON error.
- Unexpected failures are logged server-side and return a generic message.

## Testing

Add or update tests for:

- Clean UTF-8 UI sources and literal output-size labels.
- Output-size JSON and schema consistency.
- Provider normalization from frontend payload to persisted payload.
- Reference image detection by magic bytes.
- Reference filename sanitization.
- Data URL reference conversion.
- Unsafe local reference paths rejected.

Full verification should include:

- JavaScript syntax check for all Settings modules.
- JSON validation for settings data files and schema.
- `python -m compileall -q .`
- `python -m pytest -q`

## Acceptance Criteria

- The persona upload control is in the right reference panel toolbar.
- The persona reference panel still supports multiple uploads and preview display.
- `pages_api.py` no longer directly owns low-level image detection, filename generation, or base64 reference conversion.
- Config save behavior remains compatible with existing Settings payloads.
- Existing tests pass, and new tests cover the extracted backend services.
- No absolute local paths, API keys, or base64 image payloads are written to docs or committed test fixtures.
