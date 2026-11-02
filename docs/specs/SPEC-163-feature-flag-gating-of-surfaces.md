---
type: Spec
id: SPEC-163
title: "Feature Flags — Gating Nav, Routes & Cross-Feature Entry Points"
description: "Makes a disabled feature flag remove every way into that feature (its tab, route and cross-feature buttons and links), using a registry of gated surfaces and a test that walks it."
spec_status: Completed
depends_on: [SPEC-162, SPEC-074, SPEC-045, SPEC-155]
arc: feature-flags
arc_order: 2
---

**Dependency notes:** SPEC-162 (the resolved flag set), SPEC-074 (Help & guides content), SPEC-045 (axe assertions), SPEC-155 (`components/` may not import `features/`)
## Overview

SPEC-162 resolves four booleans that nothing reads. This spec makes them do their job: when a
feature is off, **every** way into it disappears — its tab, its route, and every button and link
that reaches it from somewhere else. A user with Query off has no Query tab, cannot reach `/query`
by typing the URL, and cannot create a table from a folder in the file browser. Data Quality off
means no "Check data quality" anywhere, and no runs dashboard.

The hard part is not the tab; it is the cross-feature entry points. "Create table from this folder"
lives in the file browser but is a *Query* feature; "Share table" lives in the Query rail but pushes
into *Shared Workspaces*. Those are exactly the surfaces a per-component approach misses. So this
spec does not gate components one at a time — it builds a **registry** that enumerates every gated
surface and a test that walks it, the discipline `reviewer-contract.md` records for a finding that is an
instance of a rule rather than a one-off.

## Scope

### In Scope

- `useFeature(key)` and a `<FeatureGate flag>` wrapper over SPEC-162's hook.
- A **gated-surface registry** naming every surface each flag controls, and a test that walks it.
- **Primary navigation**: `PrimaryNav` tabs and the `AppNavDrawer` items for disabled features.
- **Routes**: a disabled route renders a "not available" state rather than the app's 404, including
  when reached by deep link or a notification link.
- **Cross-feature entry points** — the table below is the contract, not an example list.
- **Help & guides**: a disabled feature's guide is not listed or reachable (SPEC-074's
  document-only-what-is-shipped rule, applied at runtime).
- Behaviour while the flag set is still loading, and behaviour under SPEC-162's `'fallback'` status.
- Accessibility: the reduced shell is axe-clean and leaves no dangling `aria-controls`/label
  references.

### Out of Scope

- Changing what any feature *does* when it is on. Every gated surface behaves exactly as today.
- New flags, or flags below feature granularity.
- Revoking permissions when a flag is off (SPEC-162 FR-006 forbids it) — a determined user with a
  disabled feature still holds the same IAM grants; hiding is presentation.
- The file-send entry point, which does not exist yet — SPEC-167 registers it.

### The gating contract

| Flag | Surfaces it hides |
|---|---|
| `files` | `/files` route; Files tab + drawer item; the **"Go to Dashboard"** control an already-signed-in visitor sees on the landing page (the *unauthenticated* landing page has no gated surface — see FR-007) |
| `query` | `/query` route; Query tab + drawer item; **"Create table from this folder"** in the file browser; **"Refresh table"**, **"Share table"** and **create-view** in the Query schema rail; any "open in Query" link elsewhere |
| `sharedWorkspaces` | `/connections` route; Connections tab + drawer item; the spaces list in the Files sidebar and mobile drawer; the `?space=` deep link (falls back to personal); **Add members**; the **Shared spaces** recipient kind in the Share-table dialog; **shared databases in the Query schema rail** and **shared spaces as a move/copy destination** (added during build — see below) |
| `dataQuality` | `/data-quality` and `/data-quality/:space/:requestId` routes; Data quality tab + drawer item; **"Check data quality"** in the selection toolbar and the file-browser dialogs; the data-quality link on a notification |

> **Contract extended during build (2026-08-11):** shared **databases in the Query schema rail**
> join the `sharedWorkspaces` row (user decision, asked before building), and so do **shared
> spaces as a move/copy destination** plus the data-quality start dialog's space list — found in
> review, where hiding the rail alone had left the WRITE path open (the picker offers a space
> selector whenever it has more than one option). The `dataQuality` row's **"data-quality link on
> a notification"** was in the table from the start and had no gating until review; it now has a
> registry row. Leaving `teamspace` browsable there while the
> spaces list and `/connections` are gone reads as a bug rather than a policy. Filtered **at the
> view, never at the service** — `useConnections` still resolves every space and a saved query
> naming a hidden database still runs, because a flag may not touch a service (SPEC-162 FR-006).

---

## Functional Requirements

### FR-001: The gate primitives

#### Acceptance Criteria:

- [ ] `useFeature(key)` returns a boolean and is the **only** way app code asks whether a feature is
      on; nothing else reads `useFeatureFlags` directly except the registry test.
- [ ] `<FeatureGate flag="query">…</FeatureGate>` renders its children only when the flag is on, and
      renders **nothing** (no wrapper element, no placeholder) when it is off.
- [ ] Both live in `features/feature-flags/`; `components/` continues to import no feature (the
      SPEC-155 ESLint rule stays green), so shared components take gating as a prop rather than
      reaching for the hook.

### FR-002: The registry and its test

#### Description:

Every gated surface is declared in one place, so adding a fifth entry point is a registry edit, not a
discovery exercise.

#### Acceptance Criteria:

- [ ] A `gatedSurfaces.ts` registry maps each flag to descriptors for its surfaces — route path,
      nav label, and a named test id or accessible name for each control.
- [ ] One test walks the registry and, for each entry, renders with that flag **off** and asserts the
      surface is absent by accessible name, then with it **on** and asserts it is present.
- [ ] The gating contract table above is covered entry-for-entry; a surface in the table with no
      registry row fails the test.
- [ ] A guard-the-guard case fails if the registry is empty or if any flag has zero surfaces —
      a test that walks nothing must not read as a pass (SPEC-153).

### FR-003: Navigation

#### Acceptance Criteria:

- [ ] A disabled feature's tab is absent from `PrimaryNav` — not present-and-disabled, not visually
      hidden.
- [ ] The same item is absent from `AppNavDrawer` below `tablet`.
- [ ] With three of four features off, the remaining single tab renders correctly at 400px and on
      desktop, and the nav is axe-clean.
- [ ] Nothing in the header retains an `aria-controls`, `aria-labelledby` or `aria-describedby`
      pointing at a removed element.

### FR-004: Routes

#### Acceptance Criteria:

- [ ] Navigating to a disabled feature's route — by typing the URL, by browser history, or from a
      notification link — renders a **"not available"** page, not the 404 page: the route exists, the
      feature does not.
- [ ] The unavailable page names the feature, says it is not available in this environment, offers a
      link to a feature that *is* enabled, and issues **no** AWS request for the disabled feature.
- [ ] `/data-quality/:space/:requestId` with `dataQuality` off renders the unavailable page and
      makes no S3 request — it must not become an existence oracle for a report (SPEC-113's rule).
- [ ] A route re-enabled at runtime (the flags refetch resolves differently) renders normally on the
      next navigation without a reload.

### FR-005: Cross-feature entry points

#### Acceptance Criteria:

- [ ] With `query` off, the file browser shows **no** "Create table from this folder" control and the
      table-builder dialog cannot be opened by any path.
- [ ] With `dataQuality` off, neither the selection toolbar nor the file-browser dialogs offer
      "Check data quality", and no data-quality request can be enqueued from the UI.
- [ ] With `sharedWorkspaces` off, the Files sidebar shows no spaces list, and the Share-table dialog
      offers **only** the Users recipient kind.
- [ ] With `sharedWorkspaces` off, a `?space=` deep link resolves to the **personal** space with
      **no** notice. This needs its own mechanism — the route ignores the parameter while the flag
      is off. It must **not** be routed through `useFileSpace`'s `fellBack`: that path fires only for
      a space the user genuinely cannot browse (gone/revoked/not-yet-active), and it renders the
      visible "That shared space is no longer available" banner, which would be untrue. A valid
      space still resolves normally through `useConnections`, because SPEC-162 FR-006 forbids a flag
      touching a service.
- [ ] With `sharedWorkspaces` off, the Share-table dialog's kind toggle does not render as a
      single-option control — it renders no toggle at all, and the field is labelled for usernames.
- [ ] Every removed control's absence is asserted by accessible name in the registry test, not by
      CSS class or test id alone.

### FR-006: Help & guides

#### Acceptance Criteria:

- [ ] A disabled feature's guide is absent from the Help page's list and unreachable by its anchor.
- [ ] Help renders correctly with any combination of flags off, including all four.
- [ ] The mapping from guide to flag lives in the registry, not duplicated in `helpContent.ts`.

### FR-007: Loading and fallback

#### Acceptance Criteria:

- [ ] While `status === 'loading'`, gated surfaces render **nothing** — a tab that appears and then
      vanishes under the pointer is worse than one that arrives a tick late.
- [ ] The **unauthenticated** landing page renders identically regardless of flag status and never
      waits on the document — it shows sign-in/sign-up, which nothing gates. This is consistent with
      SPEC-162 FR-004 gating the fetch on a signed-in user, and it is why the gating contract's
      landing-page row names the **signed-in** visitor's "Go to Dashboard" control specifically.
- [ ] An already-signed-in visitor on `/` with `files` **off** sees no "Go to Dashboard" control;
      the landing page instead offers the first enabled feature, and if **no** feature is enabled it
      renders the same "not available" state FR-004 defines, naming no feature.
- [ ] A test covers the signed-in landing page in both states — the surface only exists for an
      authenticated visitor, so an unauthenticated-only test would pass while shipping it visible.
- [ ] Under `status === 'fallback'` every feature is on (SPEC-162's compiled defaults) and the app is
      indistinguishable from an all-on `'ready'`.
- [ ] No layout shift beyond the nav's own reflow, and no spinner is introduced in the header.

---

## Data Model

```ts
// src/features/feature-flags/gatedSurfaces.ts

export type GatedSurface = {
  /** Accessible name of the control or nav item, as the registry test queries it. */
  name: string;
  kind: 'nav' | 'route' | 'control' | 'guide';
  /** Route path for `kind: 'route'`; the owning route otherwise. */
  path: string;
};

export const GATED_SURFACES: Record<FeatureFlagKey, readonly GatedSurface[]>;
```

## File & Folder Structure

```
apps/portal/src/features/feature-flags/
├── FeatureGate.tsx
├── useFeature.ts
├── gatedSurfaces.ts
├── gatedSurfaces.test.tsx        # walks the registry, both states, + guard-the-guard
└── index.ts
apps/portal/src/routes/
└── FeatureUnavailablePage.tsx
```

## Implementation Phases

### Phase 1: Primitives + registry

- `useFeature`, `FeatureGate`, `gatedSurfaces.ts` populated from the gating contract table, and the
  walking test (failing at first — the surfaces are not gated yet).

### Phase 2: Nav and routes

- `PrimaryNav`, `AppNavDrawer`, the route gate and `FeatureUnavailablePage`, including the
  no-S3-request assertion on the report route.

### Phase 3: Cross-feature entry points and Help

- File browser (create table, check data quality), Query rail (refresh/share/create view), the Files
  spaces list and `?space=` fallback, the Share-table kind toggle, and the Help list.

### Phase 4: Verification

- The registry test green in both states; axe on the reduced shell; responsive check of a one-tab nav.
- **Live check (owed), Safari:** publish a document with `query` and `dataQuality` off, sign in, and
  confirm at 400px and desktop that both tabs are gone, `/query` renders the unavailable page, the
  file browser offers neither "Create table from this folder" nor "Check data quality", and the Help
  page lists neither guide. Then flip both back on and confirm everything returns.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, component-inventory rows in the feature-flags area file, one Key
  Decisions line (gating is by registry, not per-component opt-in), and the **Help & guides sweep** —
  the guides themselves are unchanged, but their visibility is now flag-driven, which the help
  feature's inventory row must say.
