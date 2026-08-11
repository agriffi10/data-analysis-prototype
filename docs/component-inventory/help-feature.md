# Help feature (`apps/portal/src/features/help/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `HELP_SECTIONS` | `helpContent.ts` | Static, code-grounded Help & guides content (Files incl. table builder, Query, Shared connections incl. join status, Notifications). Update on every spec that changes a user-facing feature (SPEC-074 FR-005) (SPEC-074). |
| `HelpPage` | `HelpPage.tsx` | Section selector + accordion cards; active section synced to the URL hash (`/help#query`), first-section fallback, first card default-open (SPEC-074). Mount-gates the rail (≥ tablet) vs `HelpSectionChips` (mobile) by `useIsMobile` (SPEC-103). |
| `HelpSidebar` | `HelpSidebar.tsx` | Left rail: one item per section (icon, label, guide count, `aria-current`); `w-[220px] desktop:w-[248px]`, short labels at tablet / full at desktop via `useBreakpoint` (SPEC-074/103). |
| `HelpSectionChips` | `HelpSectionChips.tsx` | Mobile horizontal `overflow-x-auto` chip section selector (`nav "Guides sections"`), active chip highlighted, hash-driven `onSelect` — the `< tablet` counterpart to `HelpSidebar` (SPEC-103). |
| `HelpGuideCard` | `HelpGuideCard.tsx` | One accordion guide: header button (`aria-expanded`/`aria-controls`), numbered steps, at most one Tip/Careful callout; independent open state (SPEC-074). |
| `HelpLink` | `HelpLink.tsx` | Header help control — `NavLink` to `/help` styled like `NotificationsBell`, active on `/help` (SPEC-074). |
| `renderInline(text)` | `inlineMarkup.tsx` | Parses `<b>`/`<kbd>` markup in guide step + callout strings into `<strong>`/keyed elements (no `dangerouslySetInnerHTML`) (SPEC-074). |

> **Guide visibility is flag-driven since SPEC-163.** The guides themselves are unchanged, but
> `HelpPage` filters both SECTIONS and individual GUIDES through `hiddenHelpIds()` — sections
> alone would leave the two data-quality guides listed with Data Quality off, because they live
> inside the Files section. The guide→flag mapping lives ONLY in `features/feature-flags/
> gatedSurfaces.ts`; `helpContent.ts` knows nothing about flags, so a guide cannot end up gated
> in the list and reachable by its anchor.
