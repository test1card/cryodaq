# Third-Party Notices

CryoDAQ incorporates design assets and patterns from third-party sources.
This file lists all external sources and their license terms.

## UI UX Pro Max skill v2.5.0

**Source:** https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
**License:** MIT
**Copyright:** (c) 2024 Next Level Builder

Used components:
- Color palette tokens (Smart Home/IoT Dashboard base + extensions)
- Typography pairing recommendations (Dashboard Data: Fira Code + Fira Sans)
- UX guidelines and anti-pattern rules (subset of 99 entries)
- Style direction synthesis (Real-Time Monitoring + Data-Dense Dashboard)

The skill itself is not redistributed. Only derived design tokens and
guidelines are applied to CryoDAQ's own theme.py and design-system
documentation.

Full extraction analysis: docs/design-system/FINDINGS.md

## Fira Code

**Source:** https://github.com/tonsky/FiraCode
**License:** SIL Open Font License 1.1
**Copyright:** (c) Nikita Prokopov

Bundled in src/cryodaq/gui/resources/fonts/ for display, numeric, and
label text rendering.

## Fira Sans

**Source:** https://github.com/mozilla/Fira
**License:** SIL Open Font License 1.1
**Copyright:** (c) Mozilla Foundation, Telefonica S.A.

Bundled in src/cryodaq/gui/resources/fonts/ for body text and prose
rendering.

## Inter (legacy, transition only)

**Source:** https://github.com/rsms/inter
**License:** SIL Open Font License 1.1
**Copyright:** (c) The Inter Project Authors

Bundled during Phase UI-1 v1. Replaced by Fira Sans in B.4.5. Files
remain in resources/fonts/ until B.7 cleanup.

## JetBrains Mono (legacy, transition only)

**Source:** https://github.com/JetBrains/JetBrainsMono
**License:** SIL Open Font License 1.1
**Copyright:** (c) JetBrains s.r.o.

Bundled during Phase UI-1 v1. Replaced by Fira Code in B.4.5. Files
remain in resources/fonts/ until B.7 cleanup.

## Lucide icons

**Source:** https://github.com/lucide-icons/lucide
**License:** ISC License
**Copyright:** (c) Lucide contributors

10 SVG icons bundled in src/cryodaq/gui/resources/icons/ for ToolRail
navigation.
