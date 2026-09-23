# Existing Feature Inventory

Baseline: plugin v4.11.4 at f51be0e149bbde73ad750246fd4ced6e15797c29.

Status meanings: retain keeps existing behavior; migrate adds a Studio UI over the same backend; new belongs to the unified workbench scope.

## Chat commands

| ID | Command and aliases | Existing behavior | Status | Studio destination |
| --- | --- | --- | --- | --- |
| C01 | /文生图 | Generate with draw presets | retain | Create / Image |
| C02 | /aiimg, /生图, /画图, /绘图, /出图 | Text-to-image, provider override and size | retain | Create / Image |
| C03 | /批量N | Planned concurrent image generation | retain | Create / Batch |
| C04 | /文生图预设列表 | List draw presets | retain | Presets |
| C05 | /预设列表 | List edit presets | retain | Presets |
| C06 | /aiedit, /图生图, /改图, /修图 | Image edit and preset dispatch | retain | Create / Edit |
| C07 | /改图帮助 | Edit usage help | retain | Legacy command |
| C08 | /自拍 | Persona-aware selfie generation | retain | Create / Selfie |
| C09 | /自拍参考 | Command-side selfie reference management | retain | Personas / References |
| C10 | /视频 | Background text or reference video task | retain | Create / Video |
| C11 | /视频预设列表 | List video presets | retain | Presets |
| C12 | /重发图片 | Resend history without regeneration | retain | History actions |
| C13 | /图片历史 | Session-scoped fixed history IDs | retain | Assets / History |
| C14 | /继续改图 | Continue editing a history image | retain | History to Edit |
| C15 | /服务商 | Show provider availability | retain | Settings / Providers |
| C16 | /链路 | Show feature provider chains | retain | Settings / Chains |
| C17 | /人设 | Show available and effective persona | retain | Personas |
| C18 | /切换人设 | Session-specific persona selection | retain | Personas / Sessions |
| C19 | /任务列表 | List current managed tasks | retain | Tasks |
| C20 | /取消任务 | Cancel local task processing | retain | Tasks |

Regex fallbacks for image-before-command messages, dynamic preset commands and alternate wake punctuation remain part of these command behaviors.

## LLM tools

| ID | Tool | Existing behavior | Status |
| --- | --- | --- | --- |
| T01 | aiimg_generate | Natural-language routing among draw, edit, selfie and history continuation | retain |
| T02 | aiimg_batch_generate | LLM-planned batch generation | retain |
| T03 | aiimg_generate_video | Provider-neutral text and reference video generation | retain |

Tool names and schemas are public compatibility surfaces and may not be changed casually.

## Existing Web surfaces

| ID | Surface | Current source | Status | Studio destination |
| --- | --- | --- | --- | --- |
| W01 | Feature switches and provider chains | pages/Settings/app.js | migrate/code complete, unverified | Settings / Features |
| W02 | Provider templates and forms | provider_catalog.js, provider_form.js | migrate/partial | Settings / Providers; Studio JSON editor with explicit secret operations |
| W03 | Draw, edit and video presets | app.js | migrate | Presets |
| W04 | Persona profiles and default persona | app.js | migrate/implemented | Personas |
| W05 | Persona reference upload, preview and roles | persona_refs.js | migrate/implemented | Personas / References |
| W06 | Session persona selection | app.js and Pages API | migrate/implemented | Personas / Sessions |
| W07 | Managed tasks and cancellation | operations.js and Pages API | migrate/implemented | Tasks |
| W08 | Global image history, search, details and download | history.js and Pages API | migrate/implemented | Assets / History |
| W09 | Output-size catalog | output_sizes.js and output_sizes.json | migrate/code complete, unverified | Create parameters; legacy catalog retained in Settings |
| W10 | Legacy Settings | pages/Settings | retain | Fallback route |

Existing Pages APIs retained during migration:

- get_tasks, cancel_task
- get_session_personas, set_session_persona
- get_history, get_history_image
- get_config, save_config
- get_persona, switch_persona
- get_image_b64, upload_ref_image, upload_ref_image_b64

## Provider templates

All current templates must round-trip through the new capability catalog. Studio may hide unsupported controls but may not discard unknown fields.

| Family | Template keys | Status |
| --- | --- | --- |
| NovelAI | nai_native, nai_gateway | retain/migrate |
| OpenAI-compatible image | openai_images, openai_chat, openai_full_url_images, modelscope_openai_images | retain/migrate |
| Gemini image | gemini_native, gemini_openai_images, gemini_openai_chat | retain/migrate |
| Grok image | grok_images, grok_images_edit, grok_chat, grok2api_images | retain/migrate |
| Gitee image | gitee_images, gitee_async | retain/migrate |
| Other image | flow2api, vertex_ai_anonymous, jimeng | retain/migrate |
| Specialized video | agnes_video, minimax_h3_video, xai_video, grok_video, grok2api_video, flow2api_video | retain/migrate |
| Generic video | openai_video, custom_video | retain/migrate |

## Data and lifecycle behavior

| ID | Existing behavior | Owner | Status | Acceptance |
| --- | --- | --- | --- | --- |
| D01 | Provider registry and feature chains | core/provider_registry.py | retain/share | Web and chat resolve the same instances |
| D02 | In-memory managed tasks and cancellation | core/task_manager.py | extend | Existing tasks remain visible; Studio jobs become persistent later |
| D03 | Image history SQLite and independent copies | core/image_history.py | retain/share | Global cap 100, newest-first, session and time present |
| D04 | Persona profiles | core/persona_manager.py | retain/share | No duplicate Studio persona database |
| D05 | Session persona SQLite | core/session_personas.py | retain/share | Selection remains session-isolated |
| D06 | Persona references and roles | core/persona_ref_service.py, core/ref_store.py | retain/share | Order and identity, clothing, pose and scene roles survive |
| D07 | Output files and sending fallback | core/image_manager.py, core/video_manager.py | retain/harden | Studio does not bypass delivery lifecycle |
| D08 | Config merge and live reload | core/pages_config_service.py, handlers/pages_api.py | retain/harden | Unknown fields and active old clients survive |

## New unified workbench scope

| ID | Capability | Reference | Status | Constraint |
| --- | --- | --- | --- | --- |
| N01 | Authenticated Yukina-based Studio shell | Yukina | new | No blog, RSS, Pagefind or Swup runtime |
| N02 | Unified image, edit, selfie and video workbench | Existing plugin and Nova patterns | new | Same Python generation services and jobs |
| N03 | Asset library and project reuse | Nova | new/partial | Generated history remains capped at 100; saved assets use explicit quota |
| N04 | Canvas editor | Nova | code complete, unverified | Generation nodes, connections, local history and project recovery; no paid action in undo |
| N05 | Prompt gallery, optimization and reverse prompt | Nova | new | Calls authenticated AstrBot APIs |
| N06 | Guarded Agent workflow | Nova | code complete, unverified | Saved plan, capability validation, confirmation binding and durable jobs |
| N07 | GIF frame generation, tuning and export | Nova | code complete, unverified | Worker and server export, generated frames and managed output; chat direct send unavailable |
| N08 | Slice and Web reproduction workspace | Nova | code complete, unverified | Free/grid slicing, dual-image guided edit, static preview and managed image ZIP |

## Ownership and evidence

Until contributors are explicitly assigned, all rows are owned by the unified Studio migration branch. Update status and a concise acceptance note in the same commit that changes behavior. Existing commands must remain unchanged unless a separately approved compatibility change is recorded here.
