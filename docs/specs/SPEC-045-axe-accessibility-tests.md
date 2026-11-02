---
type: Spec
id: SPEC-045
title: "Automated Accessibility (axe) Test Suite"
description: "Gives developers an automated accessibility test layer that runs axe-core against rendered components and routes in the Vitest suite, catching machine-detectable WCAG A and AA failures at pull request time."
spec_status: Completed
depends_on: [SPEC-004, SPEC-026, SPEC-028]
---

**Dependency notes:** PR #89 (WCAG 2.2 AA pass — contrast, labels, keyboard, semantics, forms, live regions), SPEC-004 (Vitest CI), SPEC-026 (dialog pattern), SPEC-028 (Button/Input primitives)
> **Context:** PR #89 brought the app to strong WCAG 2.2 **AA** conformance by hand. This spec locks that in with an automated `axe-core` regression suite so accessibility defects fail in CI instead of being re-discovered by manual audit. It is a **testing/tooling** spec — no user-facing feature or infra change.

## Overview

Add an automated accessibility test layer that runs `axe-core` against rendered components and routes inside the existing Vitest + jsdom suite. The goal is to catch the *machine-detectable* subset of WCAG A/AA failures — missing accessible names, invalid ARIA, unlabeled inputs, bad roles, missing landmarks/headings, duplicate ids — at PR time, so the manual baseline established in PR #89 does not silently regress. The suite is explicitly **not** a substitute for manual screen-reader testing; it complements it and documents that boundary.

## Scope

### In Scope

- Add `vitest-axe` (wraps `axe-core`) as a dev dependency and register its `toHaveNoViolations` matcher in the existing `src/test-setup.ts`.
- A small shared test helper (`src/test/axe.ts`) that renders a node, runs axe with the project's standard ruleset/config, and asserts no violations — so every check is one consistent call.
- A **route-level** axe pass for each top-level page in a realistic state: Landing, Files (authenticated browser with content), Query workspace (editor + schema + results), Not Found.
- A **component-level** axe pass for the high-traffic primitives and stateful UI that route tests can't easily reach in every state: `Modal`/`ConfirmDialog`/`Drawer` (open), `Input` (error state), `Banner`/`Toast` (each variant), `UploadQueuePanel` (uploading/done/failed/collision), `CollisionPrompt`, `DestinationPicker`, `QueryTabStrip` (multi-tab), `Pager`.
- A documented, centrally-defined axe configuration: which rules run, and which are disabled **with a written reason** (notably `color-contrast`, unsupported in jsdom, and `region` for isolated component renders).
- A short contributor note in `apps/portal/info/best-practices/accessibility/accessibility.md` (or a sibling `testing.md`) describing how to add an axe check for new UI and what axe does/doesn't cover.

### Out of Scope

- **Color-contrast assertions** — jsdom has no layout/computed color, so `axe-core` cannot evaluate `color-contrast`. Contrast is governed by the design tokens (verified in PR #89) and remains a manual/visual concern. Disabled in config with a reason, not faked.
- **Real-browser / Playwright axe runs** — a future option for contrast + true focus/`:focus-visible` behavior; not built here.
- **CI gating policy changes** — the suite runs under the existing `npm test` (already required in CI per SPEC-004); no new workflow. (If a separate `test:a11y` script is desired, it's an optional FR below, not a new pipeline.)
- **Auth (Cognito Hosted UI) screens** — AWS-hosted, not in this repo; cannot be tested here.
- **Fixing newly-found violations beyond trivial ones** — if the suite surfaces a real defect on first run, fixing it is in scope; any larger remediation spins out to its own spec.

---

## Functional Requirements

### FR-001: axe tooling wired into the existing test harness

#### Description

Install `vitest-axe` and extend the global test setup so any test file can call the shared helper and use the `toHaveNoViolations` matcher. No change to how tests are run (`npm run test -w apps/portal`).

#### Acceptance Criteria

- [ ] `vitest-axe` (and transitively `axe-core`) is in `apps/portal` devDependencies, and the new dependency is noted in `CLAUDE.md` Tech Stack (testing row).
- [ ] `src/test-setup.ts` registers `toHaveNoViolations` so it's available in every test without per-file imports.
- [ ] Existing 522 tests still pass unchanged.

### FR-002: shared axe helper with one standard configuration

#### Description

A single helper renders a React node and asserts it has no axe violations, using one centrally-defined ruleset so config lives in exactly one place.

#### Acceptance Criteria

- [ ] `src/test/axe.ts` exports an async `expectNoA11yViolations(ui: ReactElement, options?)` that renders the node (via the project's existing render setup, incl. any required providers/router) and asserts `toHaveNoViolations`.
- [ ] The axe config runs the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, and `wcag22aa` rule tags.
- [ ] Disabled rules are enumerated in one place, each with an inline comment justifying it: `color-contrast` (no layout in jsdom), and `region` is overridable per-call for isolated component renders that legitimately aren't inside a landmark.
- [ ] The helper supports passing per-test rule overrides (e.g. re-enabling `region` for route-level renders).

### FR-003: route-level accessibility checks

#### Description

Each top-level page is rendered in a representative populated state and asserted clean by axe — this is where landmark, heading-order, and document-structure rules have meaning.

#### Acceptance Criteria

- [ ] Landing, Files (authenticated, with folders + files present), Query workspace (with a database, schema tables, and a succeeded result set), and Not Found each have an axe test that passes.
- [ ] Route-level checks run with the `region`/landmark rules **enabled** (so a missing `<main>` or unlabeled landmark fails).
- [ ] The Files and Query renders reuse the existing test mocks/fixtures (`mockUseFileBrowser`, schema/results mocks) rather than introducing new data layers.
- [ ] Each check asserts the page exposes exactly one `<h1>` and a `<main>` landmark (guards the PR #89 fixes specifically).

### FR-004: component-level accessibility checks for stateful UI

#### Description

Cover the shared primitives and stateful components in the states route tests don't naturally hit, so regressions in (e.g.) an error input or an open dialog are caught.

#### Acceptance Criteria

- [ ] axe passes for: `Modal`/`ConfirmDialog`/`Drawer` while open (dialog role + accessible name + no trap-induced violations), `Input` with an `error` (invalid + described-by wired), each `Banner` and `Toast` variant, `UploadQueuePanel` in uploading/done/failed/collision states, `CollisionPrompt`, `DestinationPicker`, multi-tab `QueryTabStrip`, and `Pager`.
- [ ] Component-level checks that render outside a landmark pass `region` disabled via the per-call override (FR-002), and this is commented as intentional.
- [ ] A test asserts the `QueryTabStrip` exposes `role="tablist"` with `role="tab"` children and an `aria-controls`-linked `role="tabpanel"` (guards the keyboard/tab work from PR #89).

### FR-005 (optional): dedicated `test:a11y` script

#### Description

A convenience npm script to run only the axe specs locally.

#### Acceptance Criteria

- [ ] `npm run test:a11y -w apps/portal` runs only the `*.a11y.test.tsx` files (e.g. via a Vitest name/path filter).
- [ ] Omitting this FR has no effect on FR-001–004 (the axe specs still run under the normal `npm test`).

---

## Data Model

No data model. Test-only helper signature:

```ts
// src/test/axe.ts
import type { ReactElement } from 'react';
import type { RunOptions } from 'axe-core';

// Renders `ui` (with the app's standard test providers/router) and asserts no
// axe violations. `axeOptions` merges over the project default config.
export function expectNoA11yViolations(
  ui: ReactElement,
  axeOptions?: RunOptions,
): Promise<void>;
```

## File & Folder Structure

```
apps/portal/
├── src/
│   ├── test-setup.ts                         # + toHaveNoViolations matcher (FR-001)
│   ├── test/
│   │   └── axe.ts                             # shared helper + standard config (FR-002)
│   ├── routes/
│   │   ├── LandingPage.a11y.test.tsx          # FR-003
│   │   ├── FilesPage.a11y.test.tsx            # FR-003
│   │   └── NotFoundPage.a11y.test.tsx         # FR-003
│   └── features/query/
│       └── QueryWorkspace.a11y.test.tsx       # FR-003
│   └── components/
│       └── primitives.a11y.test.tsx           # FR-004 (Modal/Drawer/Banner/Toast/Input/Pager)
│   └── features/file-browser/
│       └── fileBrowser.a11y.test.tsx          # FR-004 (UploadQueuePanel/CollisionPrompt/DestinationPicker)
└── package.json                               # + vitest-axe devDep, optional test:a11y (FR-001/005)
```

> Naming: co-locate axe specs next to the code they cover with a `.a11y.test.tsx` suffix so they're easy to find and filter (FR-005).

## Implementation Phases

### Phase 1: Tooling + helper + one proof check

- Add `vitest-axe`, register the matcher in `test-setup.ts` (FR-001).
- Write `src/test/axe.ts` with the standard config + disabled-rule comments (FR-002).
- Add a single route-level check (Landing) to prove the wiring end-to-end.
- Note the new dep in `CLAUDE.md`.

#### Checkpoint

`npm run test -w apps/portal` is green including the new Landing axe spec; deliberately introducing a violation (e.g. removing the landing `<main>`) makes it fail. Confirm `color-contrast` is reported as disabled, not silently passing.

### Phase 2: Remaining route + component checks

- Add Files, Query workspace, and Not Found route checks (FR-003), reusing existing mocks.
- Add the component-level checks (FR-004) for the dialogs, inputs, banners/toasts, upload queue, collision/destination, tab strip, pager.
- Add the optional `test:a11y` script if desired (FR-005).
- Add the contributor note to the accessibility docs.

#### Checkpoint

Full suite green; total test count increased by the new specs; `npm run lint` and `npm run build` clean. Spot-check that each route asserts one `<h1>` + a `<main>`, and that the tablist/tabpanel guard fails if the `aria-controls` wiring is removed.

## Open Questions

- [ ] Use `vitest-axe` vs `jest-axe` (jest-axe works under Vitest too)? Recommendation: `vitest-axe` (purpose-built for Vitest 4). Confirm before Phase 1.
- [ ] Keep axe specs in the default `npm test` run (recommended — CI already gates on it) or isolate them behind `test:a11y`? Default: keep them in the main run; add the script only as convenience (FR-005).
- [ ] Should a future Playwright-based pass (real browser, for contrast + focus) get its own spec? (Out of scope here; flag if there's appetite.)
