# Help feature (`apps/portal/src/features/help/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `HELP_SECTIONS` | `helpContent.ts` | Static, code-grounded Help & guides content, eight sections in sidebar order: Files (incl. data quality), Query, Tables, Data Explorer, Shared spaces, Notifications, Getting around, Give feedback. An option a separate switch can remove is its own guide under that switch (`docs/decisions/browser.md`). Update on every spec that changes a user-facing feature (SPEC-074 FR-005). |
| `HelpPage` | `HelpPage.tsx` | Section selector + accordion cards; active section synced to the URL hash (`/help#query`), first-section fallback, first card default-open (SPEC-074). Mount-gates the rail (≥ tablet) vs `HelpSectionChips` (mobile) by `useIsMobile` (SPEC-103). |
| `HelpSidebar` | `HelpSidebar.tsx` | Left rail: one item per section (icon, label, guide count, `aria-current`); `w-[220px] desktop:w-[248px]`, short labels at tablet / full at desktop via `useBreakpoint` (SPEC-074/103). |
| `HelpSectionChips` | `HelpSectionChips.tsx` | Mobile horizontal `overflow-x-auto` chip section selector (`nav "Guides sections"`), active chip highlighted, hash-driven `onSelect` — the `< tablet` counterpart to `HelpSidebar` (SPEC-103). |
| `HelpGuideCard` | `HelpGuideCard.tsx` | One accordion guide: header button (`aria-expanded`/`aria-controls`), numbered steps, at most one Tip/Careful callout; independent open state (SPEC-074). `shrink-0`, so a scrolling flex column scrolls rather than crushing the cards. `clampHeading` holds a CLOSED card's title and subtitle to one line — opt-in, and only `HelpPanel` opts in: `/help` scrolls the document and its text column is the narrower of the two, so an ellipsis would cut more there and buy nothing. |
| `HelpLink` | `HelpLink.tsx` | Header help control — `HEADER_CONTROL`, shared with `NotificationsBell` and `ThemeMenu`, with the visible word `Help` at `tablet` and up. Opens `HelpPanel` on a route in `HELP_SURFACES`; a `NavLink` to `/help` (active on `/help`) everywhere else — the accessible name changes with the behaviour (SPEC-074/207). |
| `HelpPanel` | `HelpPanel.tsx` | One section's guides in the shared `Drawer` over the current route (`mobileVariant="full-height"`), with a footer link to `/help#<sectionId>`. Reads the flag-filtered sections, never `HELP_SECTIONS` (SPEC-207). Passes `clampHeading`, which is what keeps its list of headings shorter than the panel showing them. |
| `HELP_SURFACES` | `helpSurfaces.ts` | Route path → `HelpSectionId`, six rows. Carries no flag information; a test sweeps its import list (SPEC-207). |
| `visibleHelpSections(isEnabled)` / `useVisibleHelpSections()` | `visibleSections.ts` | `HELP_SECTIONS` with every flag-hidden section AND guide dropped — the one filter the page and the panel share (SPEC-207). |
| `useContextualHelp()` | `useContextualHelp.ts` | `{sectionId, open, openPanel, closePanel}` for the header control; `null` section on a route with no row or a hidden one, and the panel closes on a pathname change (SPEC-207). |
| `resolveHelpHash(hash, sections)` | `helpDeepLink.ts` | `/help` hash → `{sectionId, guideId}`; sections matched first, then a guide id across the given (already filtered) sections, else the first visible section (SPEC-207). |
| `renderInline(text)` | `inlineMarkup.tsx` | Parses `<b>`/`<kbd>`/`<code>`/`<i>` markup in guide intro, step + callout strings into `<strong>`/`<kbd>`/`<code>`/`<em>` elements (no `dangerouslySetInnerHTML`) (SPEC-074). Any other tag reaches the reader raw — `help.test.tsx` fails on one in `HELP_SECTIONS`. |

> **Guide visibility is flag-driven since SPEC-163.** The guides themselves are unchanged, but
> `HelpPage` filters both SECTIONS and individual GUIDES through `hiddenHelpIds()` — sections
> alone would leave the two data-quality guides listed with Data Quality off, because they live
> inside the Files section. The guide→flag mapping lives ONLY in `features/feature-flags/
> gatedSurfaces.ts`; `helpContent.ts` knows nothing about flags, so a guide cannot end up gated
> in the list and reachable by its anchor.

> **SPEC-185 adds the `data-explorer` section** — five guides, a new `HelpSectionId` and a new
> `HelpIconName` (`explore` → `EyeIcon`). It is the first section whose guides are gated
> individually AND collectively (the `files` shape), and the first whose guide rows sit outside the
> section the page opens on — which is what made `gatedSurfaces.test.tsx`'s guide recipe select the
> owning section before querying the card. Until then the recipe worked by coincidence.

> **SPEC-207 makes the header control contextual.** It opens a panel over the current route rather
> than navigating, on the six routes `HELP_SURFACES` names. A gated page's help is gated **by
> derivation** — its section is already filtered out — so `GATED_SURFACES` gained no row, and the
> panel's own gating is asserted by driving the control, never by a registry entry.
