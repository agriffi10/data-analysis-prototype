# Spec: Help & Guides Page (Top-Bar Icon + Documentation Page)

**ID:** SPEC-074
**Status:** Completed
**Last Updated:** 2026-07-03

> **Implementation note (2026-07-03).** FR-005's exclusion examples were authored 2026-06-30 when Table Builder
> (SPEC-066→072) and shared-space join status (SPEC-073) were still Draft. Both **shipped before this spec was
> implemented**, so under FR-005's governing principle — *document what's shipped and wired end-to-end* — they
> are now **in scope and documented**: a "Create a table from a folder" guide under **Files**, and pending/active
> join status folded into the **Shared connections** section. The examples in Out of Scope / FR-005 below are
> retained for historical context but are superseded. See the delivery doc.
**Depends On:** SPEC-008 (auth-gated layout + react-router routes), SPEC-023 (app shell: `Header`, `PageLayout`), SPEC-028 (shared UI primitives), SPEC-052/057 (`Sidebar` left-rail pattern), SPEC-060 (`NotificationsBell` header-icon pattern to mirror), SPEC-031 (document title), SPEC-045 (axe a11y baseline)

> **Standalone UI/content spec.** Adds an in-app **Help & guides** surface: a new **help icon in the top
> bar** (mirroring the notifications bell) that links to a dedicated **`/help` page**. The page uses the
> **Files/Query left-rail layout** — a sidebar lists the app's user-facing features (Files, Query, Shared
> connections, Notifications), each with a count of its guides; selecting one swaps the main panel to that
> feature's how-to guides, rendered as expandable accordion cards. **The guide content is static and must be
> grounded in the features that actually exist in the code at the time of writing (FR-005).** It adds **no
> services, no data fetching, no IAM, no infra, no env vars, no dependencies** — it is presentation + authored
> content only. Design artifact: `docs/design/help-page-mockup.html`.

## Overview

New users (and returning ones) have no in-product explanation of what the portal can do. This spec adds a
first-class **Help & guides** page reached from a new icon in the top bar, sitting alongside the notifications
bell. The page documents how to use each feature of the portal in plain, step-by-step terms. It adopts the
same left-rail shell as the Files and Query workspaces: a sidebar of feature sections (each showing how many
guides it contains) on the left, and the selected section's guides on the right as expandable cards — each
card a single task ("Upload files", "Create a shared connection") with a short subtitle and numbered steps.
The content is authored documentation maintained in the repo, not user data, so the page has no loading or
error states and touches no AWS. Critically, the documentation must describe **only what the application can
actually do** at the moment the spec is implemented — the implementer audits the live feature set and writes
guides against it, so the help page never promises behavior that isn't shipped.

## Scope

### In Scope

- **Top-bar help icon** in `Header.tsx`, in the authenticated user-zone, placed **left of the
  `NotificationsBell`** (order: help → bell → username → avatar → Sign out). An `IconButton`-styled react-router
  **link** (`NavLink` to `/help`) using a new **help/question-mark icon** added to `icons.tsx` (no icon
  library — inline SVG, per SPEC-024). Active-route styling when on `/help` (mirrors the bell's
  `is-active` treatment). Rendered only when `status === 'authenticated'`.
- **`/help` route + `HelpPage`** — a new authenticated route under the SPEC-008 auth-gated layout, rendering a
  page-level route component (`default` export per convention, mirroring `routes/NotificationsPage.tsx`). Sets
  the document title (SPEC-031), e.g. `"Help & guides"`.
- **Left-rail section navigation** — a sidebar mirroring the Files/Query `Sidebar` pattern (248px surface panel,
  right hairline border, `bg-accent-soft`/`text-accent-text` active item, hidden below `md`). Lists one nav item
  per feature **section** with the section's **feature icon, label, and a count of guides** in that section
  (right-aligned, like the `Sidebar`'s status/`user space` badge). Selecting an item makes it the active section.
- **Section content panel** — the main column uses `PageLayout` with the **active section's title and subtitle**;
  the body renders that section's guides as a vertical list of accordion cards. No top filter tabs and **no search
  bar** (removed per design review).
- **Accordion guide cards** — each guide renders a header row (feature icon + **title with its subtitle beneath
  the title** + chevron) that expands/collapses to reveal **numbered steps**, plus an optional **callout** (an
  info "Tip" in the accent style, or a "Careful" warning in the danger style for irreversible/destructive
  actions). Cards collapse independently; the first card of a section may default to open.
- **Section deep-linking** — the active section is reflected in the URL (hash, e.g. `/help#query`) so a section is
  shareable/bookmarkable and the browser back button moves between sections; an unknown/absent hash falls back to
  the first section.
- **Authored, code-grounded content** — a static, typed content module (`helpContent.ts`) holding the sections
  and guides. The content must be derived from the features that exist in the codebase at implementation time
  (**FR-005**), covering at least: **Files**, **Query**, **Shared connections**, **Notifications**.
- **Accessibility** — sidebar items expose `aria-current`; accordion headers are buttons with
  `aria-expanded`/`aria-controls`; the new help icon has an accessible name; the page meets the SPEC-045 axe
  baseline; co-located `*.a11y.test.tsx`.
- **Design pass** — the page + icon match the existing app design (design-system + `docs/design/help-page-mockup.html`),
  consistent with the Files/Query/Notifications surfaces.

### Out of Scope

- **Any data layer / network / AWS** — no service file, no fetch, no SQS/S3, no IAM, no infra, no env vars. The
  content ships in the bundle as a typed module.
- **User-editable or remotely-sourced docs** — content is maintained in the repo by engineers, not authored or
  edited in-product, and not loaded from a CMS/markdown-at-runtime.
- **Free-text search across guides** — explicitly removed in design review; navigation is by section only.
- **Documenting unshipped / Draft-spec features** — e.g. Table Builder (SPEC-066→072) and shared-space join
  status (SPEC-073) are **excluded** until they ship (enforced by FR-005). The help page documents current
  behavior only.
- **Localization / i18n** of the content (English only, matching the rest of the app today).
- **Per-step screenshots / video / images** — guides are text + steps in v1.
- **Adding Help to the main tab bar** (Files | Query | Connections) — it is reached via the top-bar icon only,
  consistent with how Notifications is reached via the bell.
- **An unauthenticated/public help page** — the icon and route live inside the authenticated shell in v1.

---

## Functional Requirements

### FR-001: Top-bar help icon + active state

#### Description:

A help control in the header user-zone, left of the notifications bell, that links to the help page.

#### Acceptance Criteria:

- [ ] In `Header.tsx`, the authenticated user-zone renders a help **link** (react-router `NavLink`) to `/help`,
  positioned **before** `NotificationsBell` (order: help → bell → username → avatar → Sign out).
- [ ] The control uses a new **help/question-mark icon** added to `components/icons.tsx` (inline SVG, no icon
  library) and the same `IconButton`/bell sizing and hover/focus styling (32px hit target, 20px icon,
  focus-visible ring).
- [ ] The link's accessible name is descriptive, e.g. `"Help & guides"`.
- [ ] The link shows an active/current state (`aria-current="page"` + the bell's active styling) when the user is
  on `/help`.
- [ ] The control is only rendered when `status === 'authenticated'`.

### FR-002: `/help` route + page

#### Description:

A dedicated authenticated page that hosts the help content in the Files/Query left-rail shell.

#### Acceptance Criteria:

- [ ] A `/help` route is registered under the authenticated layout (SPEC-008); visiting it unauthenticated
  redirects to sign-in like the other protected routes.
- [ ] The route renders a `default`-exported page component (mirroring `routes/NotificationsPage.tsx`) that
  composes the section sidebar + the active-section content panel.
- [ ] The page sets a document title (SPEC-031), e.g. `"Help & guides"`.
- [ ] The page renders with **no loading/error/network states** (content is static and synchronous).

### FR-003: Section sidebar with per-section guide counts + selection

#### Description:

A left rail listing the feature sections, each with a guide count, that drives the active section.

#### Acceptance Criteria:

- [ ] The sidebar mirrors the `Sidebar` pattern (248px, surface bg, right hairline border, `aria-current` on the
  active item, `bg-accent-soft`/`text-accent-text` active styling, hidden below `md`).
- [ ] One nav item per section in `helpContent`, in authored order, each rendering the section's **feature icon**,
  **label**, and a **right-aligned count** equal to the number of guides in that section (derived from the
  content, not hardcoded).
- [ ] Selecting an item sets it active: the main panel's title/subtitle and guide list update to that section;
  exactly one section is active at a time; the first section is active by default.
- [ ] The active section is reflected in the URL hash (e.g. `/help#shared-connections`); loading `/help` with a
  known section hash activates that section; an unknown/absent hash falls back to the first section; browser
  back/forward moves between visited sections.
- [ ] Section selection does not alter scroll position of the page chrome in a jarring way (content panel resets to
  top on section change).

### FR-004: Section content panel + accordion guide cards

#### Description:

The main column shows the active section's guides as independently-expandable cards.

#### Acceptance Criteria:

- [ ] The main column uses `PageLayout` with the active section's **title** and **subtitle**.
- [ ] Each guide renders as a card with a header row: the section feature icon, the guide **title**, the guide
  **subtitle directly beneath the title**, and a chevron affordance; there is **no search bar and no filter tabs**.
- [ ] The header is a `button` toggling the card open/closed (`aria-expanded` reflects state; chevron rotates);
  clicking another card does not collapse it (cards are independent); the first card of a section may default to
  open.
- [ ] Expanded content shows the guide's **ordered, numbered steps**; step text may contain inline emphasis for UI
  labels (e.g. button names).
- [ ] A guide may render **at most one callout**: an info **Tip** (accent styling) or a **Careful** warning (danger
  styling) for irreversible/destructive actions; absence of a callout renders nothing extra.
- [ ] A section with zero guides renders a neutral empty message (defensive — not expected given FR-005).

### FR-005: Content grounded in features available to users (code + infra audit)

#### Description:

The help content must document only the application behavior that actually exists and is **reachable by users**
at the time the spec is implemented — not planned, drafted, or removed features. A capability counts as
"available to users" only when **both** the frontend code and the supporting infrastructure that backs it are in
place; the implementer must explicitly audit **both** layers before documenting a feature.

#### Acceptance Criteria:

- [ ] Before/while authoring `helpContent.ts`, the implementer audits the **current** user-facing feature set
  across **both layers**: (a) the **frontend code** — `apps/portal/src/features/*`, routes, `Header`/`PrimaryNav`
  — and (b) the **infrastructure** — `infra/` modules, IAM/policy templates, Lambdas, and provisioning pipelines
  (e.g. shared-space control plane, notifications write pipeline, analytics/Glue/Athena/Lake Formation), plus the
  corresponding `docs/spec-delivery/` / `docs/component-inventory.md` / `architecture.md` entries — and writes
  guides only for capabilities present and wired end-to-end in both.
- [ ] Every guide maps to a real, reachable capability in the shipped app; every referenced UI affordance (tab,
  button, menu, control name) exists in the current code **and** is backed by the infra/IAM that makes it
  function for a real user. Steps describe the actual flow (e.g. S3 has no native move/rename → the app does
  copy-then-delete; collisions warn-and-confirm because versioning is off; shared-space create is async via the
  control plane and creator-only).
- [ ] A capability that is present in the frontend but **not** backed by deployed infra/IAM (or vice versa) is
  treated as **not available to users** and is not documented.
- [ ] Features that are **Draft / not yet shipped** (e.g. Table Builder SPEC-066→072, shared-space join status
  SPEC-073) are **not** documented; removed/superseded behaviors are not documented.
- [ ] Content covers, at minimum, the four current feature areas: **Files** (upload, folders, download,
  rename/move/copy/delete, file details/metadata), **Query** (write/run SQL, schema rail + active database, saved
  queries, history, results incl. resize/export), **Shared connections** (create, add members, manage/remove
  members, leave, delete), and **Notifications** (the bell + unread indicator, the notifications page incl.
  10/page, mark-read / mark-all-read).
- [ ] The spec's **verification step** cross-checks the authored guides against **both the code and the infra** (a
  fresh-context reviewer or subagent confirms each documented behavior exists, is backed end-to-end, and that no
  Draft / un-deployed feature leaked in) — accuracy is part of acceptance, not just rendering.
- [ ] `helpContent.ts` carries a short top-of-file note stating the content reflects the feature set as of
  implementation and must be revisited when features change (so future feature specs update it).

### FR-006: Accessibility, design, and states

#### Acceptance Criteria:

- [ ] The new help icon, sidebar, and accordion are keyboard-operable and screen-reader-labeled: sidebar items
  expose `aria-current`; accordion headers are `button`s with `aria-expanded` (and `aria-controls` to their
  panel); the help icon has an accessible name (FR-001).
- [ ] The page passes the SPEC-045 axe baseline; co-located `*.a11y.test.tsx` covers the page and the header icon.
- [ ] No information is conveyed by color alone (active section, open/closed state, and callout type are also
  conveyed by text/structure/iconography).
- [ ] The page, icon, sidebar, and cards visually match the design (`docs/design/help-page-mockup.html` + design-system),
  consistent with the Files/Query/Notifications surfaces.

---

## Data Model

Static, typed content — no runtime/user data. Place types in the feature folder (UI-local, not `src/types/`,
since nothing else consumes them).

```ts
// apps/portal/src/features/help/help.types.ts

// A single how-to guide (one task the user can perform).
export type HelpGuide = {
  id: string;            // stable slug, unique within its section (e.g. 'upload-files')
  title: string;         // e.g. "Upload files"
  subtitle: string;      // one line shown beneath the title
  steps: string[];       // ordered steps; may contain inline emphasis markup for UI labels
  callout?: HelpCallout; // at most one (FR-004)
};

export type HelpCallout =
  | { kind: 'tip'; text: string }       // accent styling
  | { kind: 'warning'; text: string };  // danger styling (irreversible/destructive actions)

// A feature section (one sidebar item + one content panel).
export type HelpSection = {
  id: HelpSectionId;     // matches the URL hash (FR-003), e.g. 'files'
  label: string;         // sidebar + page title, e.g. "Files"
  subtitle: string;      // PageLayout subtitle for the section
  icon: HelpIconName;    // which feature icon to render
  guides: HelpGuide[];   // count drives the sidebar badge (FR-003)
};

export type HelpSectionId =
  | 'files'
  | 'query'
  | 'shared-connections'
  | 'notifications';

export type HelpIconName = 'files' | 'query' | 'connections' | 'notifications';
```

```ts
// apps/portal/src/features/help/helpContent.ts
// NOTE: this content reflects the app's feature set as of implementation (SPEC-074 FR-005).
// Revisit when features change — guides must describe only behavior that exists in the code.
export const HELP_SECTIONS: HelpSection[] = [ /* files, query, shared-connections, notifications */ ];
```

## API / Interface Contract

```tsx
// routes/HelpPage.tsx — default-exported route component (thin wrapper, mirrors routes/NotificationsPage.tsx)
export default function HelpPage(): JSX.Element;

// features/help/HelpPage.tsx — composes sidebar + content; owns active-section state (synced to URL hash)
export function HelpPage(): JSX.Element;

// features/help/HelpSidebar.tsx — left rail
type HelpSidebarProps = {
  sections: HelpSection[];
  activeId: HelpSectionId;
  onSelect: (id: HelpSectionId) => void;
};

// features/help/HelpGuideCard.tsx — one accordion card
type HelpGuideCardProps = {
  guide: HelpGuide;
  iconName: HelpIconName;
  defaultOpen?: boolean;
};
```

No service signatures — there is no service layer in this spec.

## Environment Variables

None.

## File & Folder Structure

```
apps/portal/src/
├── components/
│   ├── icons.tsx                          # + HelpCircleIcon (and ChevronDownIcon if not already present)
│   └── Header.tsx                         # mount the help icon link left of NotificationsBell (FR-001)
├── features/
│   └── help/
│       ├── HelpPage.tsx                   # sidebar + content panel; active-section state synced to URL hash (FR-002/003/004)
│       ├── HelpPage.test.tsx
│       ├── HelpSidebar.tsx                # left rail: section nav + per-section counts (FR-003)
│       ├── HelpSidebar.test.tsx
│       ├── HelpGuideCard.tsx              # one accordion guide: title + subtitle + steps + optional callout (FR-004)
│       ├── HelpGuideCard.test.tsx
│       ├── helpContent.ts                 # authored, code-grounded section/guide content (FR-005)
│       ├── help.types.ts                  # HelpSection/HelpGuide/HelpCallout/… types
│       ├── HelpPage.a11y.test.tsx         # SPEC-045 axe baseline (FR-006)
│       └── index.ts                       # barrel exports
├── routes/
│   └── HelpPage.tsx                       # default-export route wrapper (mirrors routes/NotificationsPage.tsx)
└── App.tsx                                # register the /help route under the auth-gated layout (FR-002)
```

## Implementation Phases

### Phase 1: Icon + route shell + left-rail navigation

- Add `HelpCircleIcon` (and `ChevronDownIcon` if missing) to `icons.tsx`; add the help `NavLink` to `Header.tsx`
  left of `NotificationsBell` with active-route styling (FR-001).
- Register the `/help` route under the auth-gated layout with a `default`-exported wrapper + `HelpPage` shell that
  sets the document title (FR-002).
- Build `HelpSidebar` mirroring the `Sidebar` pattern: section items with feature icon, label, and per-section
  guide count; selection + `aria-current`; active-section state in `HelpPage` synced to the URL hash with
  first-section fallback (FR-003). a11y for the icon + sidebar.

### Phase 2: Content panel + accordion cards

- `HelpGuideCard` (header button with title + subtitle beneath + chevron; `aria-expanded`/`aria-controls`;
  independent open/close; numbered steps; optional Tip/Warning callout) and the section content panel via
  `PageLayout` (title/subtitle + card list; defensive empty state) (FR-004/006).

### Phase 3: Author code- and infra-grounded content + verify

- Audit the current feature set across **both layers** — frontend (`features/*`, routes, `Header`/`PrimaryNav`)
  and infrastructure (`infra/` modules, IAM/policy templates, Lambdas, pipelines) + delivery/architecture docs;
  author `helpContent.ts` for Files, Query, Shared connections, and Notifications, documenting only behavior that
  is shipped and backed end-to-end, excluding Draft / un-deployed features; add the top-of-file maintenance note
  (FR-005).
- Verification (fresh context / subagent): cross-check every guide against **the code and the infra**, confirm no
  Draft / un-deployed feature leaked in, and run the axe baseline (FR-005/006).
```
