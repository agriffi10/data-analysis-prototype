# Spec: Metadata Panel Visual Polish

**ID:** SPEC-027  
**Status:** Completed  
**Last Updated:** 2026-06-16  
**Depends On:** SPEC-021

## Overview

The metadata panel (`MetadataPanel.tsx`) is a right-side slide-over drawer that shows read-only S3 object details for a selected file. Currently it uses generic Tailwind blue/gray classes and a plain `shadow-xl`. This spec updates it to the design system's drawer pattern: `shadow-lg`, `border-border` hairline, uppercase `text-xs text-text-3` field labels, `text-sm text-text` values, and the standard close-button ghost style.

## Scope

### In Scope

- `apps/portal/src/features/file-browser/MetadataPanel.tsx` — all JSX and `className` props.
- The `Field` and `MetadataFields` sub-components within the same file.

### Out of Scope

- Drawer animation / slide-in transition — deferred (no animation library is in the stack yet).
- Any change to `useObjectMetadata` hook or the `ObjectMetadata` type.

---

## Functional Requirements

### FR-001: Drawer container

#### Description

The drawer is a fixed right panel, 380px wide on large viewports (full-width on very small viewports), with a `shadow-lg` to separate it from the content behind.

#### Acceptance Criteria

- [ ] `<aside>`: `fixed inset-y-0 right-0 z-40 flex w-full max-w-[380px] flex-col bg-surface border-l border-border shadow-lg overflow-hidden`.
- [ ] The current `shadow-xl` is replaced with `shadow-lg`.
- [ ] A semi-transparent scrim **is not added** — the panel is non-blocking (`aria-modal="false"` preserved) and the content behind stays interactive.

### FR-002: Drawer header

#### Description

The header row shows the filename and a close button.

#### Acceptance Criteria

- [ ] Header: `flex items-center justify-between border-b border-border px-4 h-14 shrink-0`.
- [ ] Filename: `text-base font-semibold text-text truncate flex-1 min-w-0` with `title={file.name}`.
- [ ] Close button: ghost icon button — `shrink-0 ml-3 h-8 w-8 flex items-center justify-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text` containing an ✕ SVG (16×16) or the inline `×` character. Replace the current `✕` text character with:

```tsx
<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
     className="h-4 w-4" aria-hidden="true">
  <path strokeLinecap="round" d="M2 2l12 12M14 2L2 14" />
</svg>
```

- [ ] `aria-label="Close details"` is preserved.

### FR-003: Scrollable body

#### Description

The body of the panel scrolls independently when metadata fields exceed the viewport height.

#### Acceptance Criteria

- [ ] Body `<div>`: `flex-1 overflow-y-auto px-4 py-4`.

### FR-004: Loading state

#### Description

While the metadata fetch is in progress, show a centered loading indicator.

#### Acceptance Criteria

- [ ] Loading `<div>`: `flex flex-col items-center justify-center py-16 text-text-3`.
- [ ] An animated pulsing placeholder (a simple `animate-pulse` set of `rounded` gray bars) or just the existing "Loading…" text in `text-sm text-text-3` — either is acceptable; keep simple.

### FR-005: Error state

#### Description

If the metadata fetch fails, show an inline error block.

#### Acceptance Criteria

- [ ] Error container: `rounded-lg border border-danger-soft bg-danger-soft p-3 text-sm`.
- [ ] Heading: `font-medium text-danger` — "Couldn't load details".
- [ ] Detail text: `mt-1 text-danger/80` (or `text-danger text-opacity-80`).

### FR-006: Field rows

#### Description

Each metadata field is a `<dt>`/`<dd>` pair with a hairline divider below it.

#### Acceptance Criteria

- [ ] `Field` component outer `<div>`: `border-b border-border-2 py-3 last:border-0`.
- [ ] `<dt>`: `text-xs font-semibold uppercase tracking-wide text-text-3`.
- [ ] `<dd>`: `mt-1 text-sm text-text break-all` (use `break-all` for ETags and long paths, which don't have natural word-break points).

### FR-007: Custom metadata section

#### Description

The "Custom metadata" section has a section header and the same field rows.

#### Acceptance Criteria

- [ ] Section header `<h3>`: `text-xs font-semibold uppercase tracking-wide text-text-3 mt-6`.
- [ ] "No custom metadata" empty state: `mt-2 text-sm text-text-3`.
- [ ] Custom field entries use the same `Field` component as the main fields.

---

## Data Model

_No new TypeScript types._

---

## File & Folder Structure

```
apps/portal/src/features/file-browser/
└── MetadataPanel.tsx    ← visual update
```

---

## Implementation Phases

### Phase 1: Update MetadataPanel.tsx

Replace all `className` props. The `Field` sub-component is updated in the same pass. No logic changes.

#### Checkpoint

`npm run dev`: click "Details" on any file row. The panel slides in from the right, 380px wide, hairline left border, `shadow-lg`. Field labels are uppercase gray, values are `text-sm text-text`. Click ✕ or press Escape — panel closes. `npm run test -w apps/portal` passes (tests check ARIA roles, not class names).

---

## Open Questions

_None._
