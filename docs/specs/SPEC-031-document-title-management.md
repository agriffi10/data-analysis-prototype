---
type: Spec
id: SPEC-031
title: "Document Title Management"
description: "Gives every page a meaningful browser tab title in the form 'Page — S3 File Portal' through a small reusable hook, replacing the Vite default title for users and screen readers."
spec_status: Completed
depends_on: []
---

## Overview

The app currently leaves `document.title` as the Vite default ("Vite + React + TS") on every page. Each page should display a meaningful title in the format `"{Page} — S3 File Portal"` — useful for browser tab identification, history navigation, and accessibility (screen readers announce the title on page change). A small reusable hook centralises the title-setting logic so no page has to manage `document.title` directly.

## Scope

### In Scope

- `apps/portal/src/hooks/usePageTitle.ts` — the hook that sets `document.title`.
- `apps/portal/src/lib/formatPageTitle.ts` — the pure formatting function (testable without DOM).
- Calling `usePageTitle` from every existing page component: `LandingPage.tsx`, `FilesPage.tsx`, `NotFoundPage.tsx`.
- The base title tag in `apps/portal/index.html` — updated to "S3 File Portal" as the fallback (shown until React hydrates).

### Out of Scope

- Per-prefix breadcrumb titles in the file browser (e.g. "Documents — Files — S3 File Portal") — the current browser is a single `/files` route; sub-prefix navigation is client-side state, not a route. Deferred until routing is added for prefixes.
- Open Graph / meta description tags — deferred to a future SEO spec.
- Server-side rendering considerations — the app is a static SPA.

---

## Functional Requirements

### FR-001: `formatPageTitle` utility

#### Description

A pure function that formats a page name into the canonical title string. Lives in `src/lib/` so it can be unit-tested without a DOM.

#### Acceptance Criteria

- [ ] Located at `src/lib/formatPageTitle.ts`, named export `formatPageTitle`.
- [ ] Signature: `function formatPageTitle(page?: string): string`
- [ ] When `page` is provided and non-empty: returns `"{page} — S3 File Portal"` (em-dash, not a hyphen).
- [ ] When `page` is omitted or empty string: returns `"S3 File Portal"` (used by the landing page where the product name alone is the title).
- [ ] The app name suffix (`"S3 File Portal"`) is a constant in the same file — not hardcoded at each call site.
- [ ] A co-located test `src/lib/formatPageTitle.test.ts` verifies:
  - `formatPageTitle('Files')` → `'Files — S3 File Portal'`
  - `formatPageTitle('')` → `'S3 File Portal'`
  - `formatPageTitle()` → `'S3 File Portal'`
  - `formatPageTitle('Not Found')` → `'Not Found — S3 File Portal'`

### FR-002: `usePageTitle` hook

#### Description

A React hook that calls `formatPageTitle` and sets `document.title` as a side effect. Pages call this at their top level.

#### Acceptance Criteria

- [ ] Located at `src/hooks/usePageTitle.ts`, named export `usePageTitle`.
- [ ] Signature: `function usePageTitle(page?: string): void`
- [ ] Implementation uses a single `useEffect` with `[page]` dependency:
  ```ts
  useEffect(() => {
    document.title = formatPageTitle(page);
  }, [page]);
  ```
- [ ] No cleanup / title-restore on unmount — SPAs typically do not restore the title when a component unmounts; the next page sets its own title.
- [ ] The hook is in `src/hooks/` following project conventions (`useCamelCase.ts`).

### FR-003: Page title assignments

#### Description

Every page component calls `usePageTitle` at its top level with the appropriate page name.

#### Acceptance Criteria

- [ ] `LandingPage.tsx`: `usePageTitle()` — no argument, yields "S3 File Portal" (the product name alone is correct for the marketing page).
- [ ] `FilesPage.tsx`: `usePageTitle('Files')` — yields "Files — S3 File Portal".
- [ ] `NotFoundPage.tsx`: `usePageTitle('Not Found')` — yields "Not Found — S3 File Portal".
- [ ] `usePageTitle` is called unconditionally at the top of each component (not inside a condition or nested function), consistent with the Rules of Hooks.

### FR-004: `index.html` base title

#### Description

The `<title>` tag in `index.html` provides the title before React mounts. It should be the product name, not the Vite scaffold default.

#### Acceptance Criteria

- [ ] `apps/portal/index.html` `<title>` is changed from `"Vite + React + TS"` (or whatever the current value is) to `"S3 File Portal"`.

---

## Data Model

```ts
// src/lib/formatPageTitle.ts
const APP_NAME = 'S3 File Portal';
export function formatPageTitle(page?: string): string { ... }
```

---

## API / Interface Contract

```ts
// Usage in a page component:
import { usePageTitle } from '../hooks/usePageTitle';

export default function FilesPage() {
  usePageTitle('Files');
  // ...
}
```

---

## File & Folder Structure

```
apps/portal/
├── index.html                         ← update <title>
└── src/
    ├── hooks/
    │   └── usePageTitle.ts            ← new hook
    ├── lib/
    │   ├── formatPageTitle.ts         ← new utility
    │   └── formatPageTitle.test.ts    ← new tests
    └── routes/
        ├── LandingPage.tsx            ← add usePageTitle()
        ├── FilesPage.tsx              ← add usePageTitle('Files')
        └── NotFoundPage.tsx           ← add usePageTitle('Not Found')
```

---

## Implementation Phases

### Phase 1: Utility and hook

Create `formatPageTitle.ts` and its test file. Create `usePageTitle.ts`. Run tests — all pass.

#### Checkpoint

`npm run test -w apps/portal` passes, including the new `formatPageTitle.test.ts` cases.

### Phase 2: Wire into pages and update index.html

Call `usePageTitle` in the three page components. Update `index.html`. Verify in the browser.

#### Checkpoint

Open the dev server. Tab title reads "S3 File Portal" on `/`, "Files — S3 File Portal" on `/files`, "Not Found — S3 File Portal" on a bad URL. Navigate between routes — the title updates on each transition without a page reload.

---

## Open Questions

_None._
