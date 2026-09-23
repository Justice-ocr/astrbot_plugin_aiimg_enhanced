# Source Manifest

This file is the allow-list for borrowed code and assets. Nothing may be copied into the plugin until its source, destination and license status are recorded here.

## Reference repositories

| Source repository | Commit SHA | Upstream license | Current use | Gate |
| --- | --- | --- | --- | --- |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | MIT for repository code; user-confirmed material modification and redistribution authorization | Directly derived Studio shell and authorized favicon | Preserve notice and file-level register |
| tianjiangqiji/nova-image-studio | b8cd44cc083a0429f8df6a7c9fc5b935b7ae0731 | AGPL-3.0 | Feature and interaction study only | Resolve combined-distribution obligations before copying code |

## File-level import manifest

As of 2026-09-23, the Studio shell directly derives its layout and theme layer from the pinned Yukina files. Nova remains a feature and interaction reference; no Nova source or media has been copied.

| Source repository | Commit SHA | Original file | Target file | License | Modification | Asset authorization evidence |
| --- | --- | --- | --- | --- | --- | --- |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | src/layouts/BaseLayout.astro, src/layouts/MainLayout.astro | web/src/layouts/YukinaStudioLayout.astro, web/src/app/StudioApp.tsx | MIT | Directly adapted centered navigation, main container and sidebar shell for one React workbench; blog, Swup, RSS and search runtime removed | User confirmed modification and redistribution rights on 2026-09-23 |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | src/components/GlobalStyles.astro, src/components/NavBar.astro, src/components/SideBar.astro, src/styles/animations.css | web/src/styles/yukina-upstream.css | MIT | Direct derivative translated from Tailwind utilities to scoped plain CSS and adapted to Studio controls | User confirmed modification and redistribution rights on 2026-09-23 |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | public/favicon.svg | web/public/yukina-favicon.svg, web/src/assets/yukina-favicon.svg | MIT plus user-confirmed material authorization | Copied for the Page favicon and inlined into the Studio brand at build time; formatting adjusted | User confirmed modification and redistribution rights on 2026-09-23 |
| WhitePaper233/yukina | 4077d8c17fcb7429dcdd5e3f8577bcf6150b52fa | LICENSE | web/public/licenses/YUKINA-LICENSE.txt | MIT | Verbatim license copy | Not applicable |

## Yukina asset authorization register

The user confirmed on 2026-09-23 that the authorization covers modification and redistribution of Yukina materials. Each imported asset remains listed below.

| Asset path | Rights holder | Allowed use | Redistribution allowed | Attribution | Evidence location | Status |
| --- | --- | --- | --- | --- | --- | --- |
| public/favicon.svg | WhitePaper233/yukina upstream | Modification and redistribution confirmed by user | Yes | Upstream MIT notice retained | Codex task conversation, 2026-09-23 | Imported as `web/public/yukina-favicon.svg` |

## Implementation rules

1. Import only the Yukina files needed by the Studio shell; keep provenance and the upstream MIT notice alongside distributed assets.
2. Do not copy Nova's Next.js server, database, service worker, Electron layer or provider keys.
3. Closely translated Nova code is treated as derivative and must be registered here.
4. Independently rewritten components still record the design reference and are marked independent implementation.
5. Update THIRD_PARTY_NOTICES.md in the same commit that adds borrowed material.
6. The plugin currently has no repository-root license file. Do not invent or change the project's license during this migration.
