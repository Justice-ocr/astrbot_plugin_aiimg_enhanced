# Source Manifest

This file is the allow-list for borrowed code and assets. Nothing may be copied into the plugin until its source, destination and license status are recorded here.

## Reference repositories

| Source repository | Commit SHA | Upstream license | Current use | Gate |
| --- | --- | --- | --- | --- |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | MIT for repository code | Template and architecture study only | Preserve notice; register copied files |
| tianjiangqiji/nova-image-studio | b8cd44cc083a0429f8df6a7c9fc5b935b7ae0731 | AGPL-3.0 | Feature and interaction study only | Resolve combined-distribution obligations before copying code |

## File-level import manifest

No media from either reference repository has been copied as of 2026-09-22. The initial Studio shell is an independent implementation informed by the pinned Yukina layout and theme structure.

| Source repository | Commit SHA | Original file | Target file | License | Modification | Asset authorization evidence |
| --- | --- | --- | --- | --- | --- | --- |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | src/layouts/BaseLayout.astro, src/layouts/MainLayout.astro | web/src/layouts/YukinaStudioLayout.astro | MIT | Independent Astro layout adapted for one React workbench; no Swup, blog, RSS or copied markup | Not applicable |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | src/components/GlobalStyles.astro, src/components/NavBar.astro | web/src/styles/tokens.css, web/src/styles/yukina-shell.css | MIT | Independent variables and shell CSS; colors, dimensions and component rules rewritten for Studio | Not applicable |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | navigation and sidebar interaction pattern | web/src/app/StudioApp.tsx, web/src/app/routes.ts | MIT | Independent React implementation using lucide-react | Not applicable |

## Yukina asset authorization register

The user stated that Yukina materials have been authorized for non-commercial use. Before an asset enters web/public/authorized-assets, add one row per file or clearly defined directory.

| Asset path | Rights holder | Allowed use | Redistribution allowed | Attribution | Evidence location | Status |
| --- | --- | --- | --- | --- | --- | --- |
| not yet specified |  | Non-commercial use stated by user | Unknown | Unknown | Must be archived outside Git | Blocked for copying |

## Implementation rules

1. Prefer adapting layout structure and design tokens over copying whole repositories.
2. Do not copy Nova's Next.js server, database, service worker, Electron layer or provider keys.
3. Closely translated Nova code is treated as derivative and must be registered here.
4. Independently rewritten components still record the design reference and are marked independent implementation.
5. Update THIRD_PARTY_NOTICES.md in the same commit that adds borrowed material.
6. The plugin currently has no repository-root license file. Do not invent or change the project's license during this migration.
