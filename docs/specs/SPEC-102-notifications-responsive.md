---
type: Spec
id: SPEC-102
title: "Notifications page — responsive layout"
description: "Makes the Notifications page responsive, keeping the inline header on desktop and tablet and stacking it on mobile with a full-width Mark-read button under each message and touch-sized pager buttons."
spec_status: Completed
depends_on: [SPEC-095]
arc: responsive-and-files-ux
arc_order: 8
---

## Overview

The routed Notifications page (`/notifications`) is a read-only inbox reached from the header bell: a newest-first list with a 10-per-page replace pager, an All/Unread filter, a Refresh control, a Mark-all-read action, and a per-row Mark-read control. Today its layout is fixed — the page header keeps the filter + actions inline beside the title at every width, and controls stay compact regardless of viewport. On a phone the inline header crowds against the title and the compact per-row and pager buttons are below comfortable touch size. This spec makes the page reflow across the SPEC-095 breakpoints: desktop and tablet keep the current inline header (the "unchanged baseline"); mobile stacks the header (title over a filter + Mark-all row), drops each row's Mark-read below the message as a full-width ~34px touch button, and grows the pager buttons to full touch height. It is purely presentation/reflow — the data layer, write pipeline, and semantics are untouched. Unread state must continue to read as wash + dot + weight, never color alone.

## Scope

### In Scope

- Responsive reflow of the Notifications page across the three SPEC-095 breakpoints (mobile = base `< tablet`; tablet = `tablet`, 900–1299px; desktop = `desktop`, ≥1300px), mobile-first.
- A **stacked page header on mobile**: title on its own line, with the All/Unread filter segment + Mark-all (and Refresh) on their own row beneath it; inline header actions restored at `≥ tablet`.
- Per-row Mark-read reflow: inline (trailing) at `≥ tablet`; a full-width ~34px button below the message at `< tablet`.
- Pager buttons grow to full touch height at `< tablet`; the 10-per-page replace behavior and label are unchanged.
- A scoped, opt-in enhancement to `PageLayout`'s header so it can stack actions under the title at `< tablet` (shared by Connections/Help — must default to today's behavior for those pages).
- Preserving unread affordance (wash + dot + weight + visually-hidden "Unread:" label) at every width — never color-only.

### Out of Scope

- **Any change to the notifications write pipeline, the FIFO SQS queue, the writer Lambda, IAM, or infra** — presentation only.
- **Any change to the read service, `useNotifications`, the 60s background poll, or optimistic mutation logic.**
- **No delete** — there is no delete control on this page and none is added.
- Changing pager mechanics (still client-side, `PAGE_SIZE = 10`, Prev/label/Next replace paging), filter semantics, empty/loading/error states, or Toast behavior.
- Changing the header bell, the `/notifications` route, or notification content/copy.
- Restyling `Connections`/`Help` pages (they only inherit the opt-in `PageLayout` header behavior when it is explicitly enabled here — this spec enables it only for Notifications).

---

## Functional Requirements

### FR-001: `PageLayout` supports an opt-in stacked mobile header

#### Description:

`PageLayout` renders `title`/`subtitle` and a right-aligned `actions` cluster in a single flex row. Add an **opt-in** prop (decision: `stackActionsOnMobile?: boolean`, default `false`) that, when set, makes the header **stack below `tablet`**: the title/subtitle block on the first line and the `actions` cluster wrapping onto its own full-width row beneath the title, left-aligned. At `≥ tablet` the header is unchanged — title left, actions right, on one line. When the prop is absent or `false`, the header renders exactly as today at all widths, so Connections/Help are unaffected. This is the chosen mechanism (enhance the shared `PageLayout` header, opt-in) rather than the page rendering its own bespoke header.

#### Acceptance Criteria:

- [ ] `PageLayout` accepts `stackActionsOnMobile?: boolean` (default `false`); the prop is documented in the component's JSDoc.
- [ ] With `stackActionsOnMobile={false}` (or omitted), the rendered header markup/classes are identical to the pre-spec behavior at every width (Connections/Help visually unchanged — verified by their existing tests still passing).
- [ ] With `stackActionsOnMobile`, at `< tablet` the header is a vertical stack: the `<h1>` title (and optional subtitle) on its own line, then the `actions` cluster on a separate row below it, left-aligned and able to wrap; the actions row is not clipped or overlapped by the title.
- [ ] With `stackActionsOnMobile`, at `≥ tablet` the header is the single-row inline layout (title left, actions right) — indistinguishable from the non-opt-in layout at that width.
- [ ] The header still contains exactly one `<h1>`; `actions` remain reachable and operable in both stacked and inline arrangements.

### FR-002: Notifications header — inline `≥ tablet`, stacked `< tablet`

#### Description:

`NotificationsPage` opts into the stacked-header behavior. At tablet and desktop the header keeps the current inline arrangement (All/Unread `FilterTabs` + Refresh `IconButton` + "Mark all read" `Button` beside the title). At mobile the header stacks: "Notifications" title on its own line, and the filter segment + Mark-all (+ Refresh) on a row below the title. Desktop additionally caps the content column at ~760px; tablet caps at the same width (already applied via `contentClassName`).

#### Acceptance Criteria:

- [ ] `NotificationsPage` passes `stackActionsOnMobile` to `PageLayout`; no other page enables it.
- [ ] At `≥ tablet` (tablet and desktop), the All/Unread filter, Refresh, and Mark-all controls render on the same row as the "Notifications" title (inline header), matching the current baseline.
- [ ] At `< tablet`, the "Notifications" title is on its own line and the filter segment + Mark-all + Refresh render on a distinct row beneath the title.
- [ ] The content column stays capped (`max-w-[760px]`) at desktop and tablet; the cap does not force horizontal scrolling at mobile widths (content fits the viewport).
- [ ] All header controls (filter toggle, Refresh, Mark-all) remain keyboard-focusable and operable in both the inline and stacked arrangements, with `aria-pressed` still the sole active-filter signal.

### FR-003: Per-row Mark-read — inline `≥ tablet`, full-width 34px button `< tablet`

#### Description:

`NotificationRow` renders unread rows with a trailing "Mark read" button. At `≥ tablet` this stays a compact trailing (inline, end-aligned) control as today. At `< tablet` the Mark-read control drops **below the message + timestamp**, as a full-width button ~34px tall (a comfortable touch target), inside the message column. Read rows never show a Mark-read control at any width.

#### Acceptance Criteria:

- [ ] At `≥ tablet`, an unread row's "Mark read" button renders inline as a trailing control on the same row as the message (current layout).
- [ ] At `< tablet`, an unread row's "Mark read" button renders below the message and timestamp, spans the full width of the message column, and is ~34px tall (`h-[34px]` or token-equivalent).
- [ ] Read rows render no Mark-read control at any width (and keep the aligned empty marker slot).
- [ ] Clicking/activating "Mark read" calls `onMarkRead(id)` identically in both arrangements; keyboard focus/activation works at both widths.
- [ ] The row's message text wraps (`break-words`) without overflow at mobile width; the timestamp remains visible.

### FR-004: Pager grows to full touch height on mobile; 10/page unchanged

#### Description:

The client-side `Pager` (Prev / range label / Next) keeps its `PAGE_SIZE = 10` replace-paging behavior. On mobile the Prev/Next buttons grow to full touch height (~38px) so they clear the minimum touch target; at `≥ tablet` the pager keeps its current compact height. No change to the label, the `aria-live` announcement, or clamp/reset logic.

#### Acceptance Criteria:

- [ ] `PAGE_SIZE` remains `10`; the page still shows at most 10 rows per page with a Prev/label/Next replace pager.
- [ ] At `< tablet`, the Prev and Next buttons are at least ~38px tall (full touch height); at `≥ tablet` they render at the current compact height (`h-9`).
- [ ] The range label ("1–10 of 23") and its `aria-live="polite"` announcement are unchanged at all widths.
- [ ] Disabled states (Prev disabled on first page, Next on last), clamp-on-shrink, and snap-to-newest behavior are unchanged.
- [ ] The pager reflow introduces no horizontal overflow at mobile width (Prev/label/Next fit the row).

### FR-005: Unread affordance stays non-color-only across all widths

#### Description:

At every breakpoint and in both header/row arrangements, the unread state must be conveyed by the accent wash + marker dot + heavier text weight + the visually-hidden "Unread:" prefix — never by color alone. Reflowing the row (especially the mobile stacked Mark-read) must not drop any of these signals.

#### Acceptance Criteria:

- [ ] Unread rows retain the accent wash background, the accent marker dot, and the bolder message weight at mobile, tablet, and desktop.
- [ ] The visually-hidden "Unread: " prefix (`sr-only`) is present for unread rows at all widths.
- [ ] Read rows keep the neutral surface, the aligned empty marker slot, and lighter text at all widths.
- [ ] Removing color (simulated grayscale / forced-colors check) still distinguishes unread from read via dot + weight + hidden label.
- [ ] `vitest-axe` finds no new a11y violations on the page in a narrow (`< tablet`) render.

---

## Data Model

No new or changed types. This spec is presentation-only; `Notification`, `useNotifications`, and the notifications service shapes are untouched.

The only interface change is one added prop on `PageLayout`:

```ts
// apps/portal/src/components/PageLayout.tsx
type PageLayoutProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  contentClassName?: string;
  /**
   * When true, the header stacks below `tablet`: title (+ subtitle) on the first
   * line, then the `actions` cluster on its own full-width row beneath it.
   * At `>= tablet` the header is the usual single inline row. Default false —
   * other hosts (Connections/Help) are unaffected unless they opt in.
   */
  stackActionsOnMobile?: boolean;
  children: ReactNode;
};
```

---

## File & Folder Structure

```
apps/portal/src/
├── components/
│   ├── PageLayout.tsx              # add opt-in `stackActionsOnMobile` header stacking (FR-001)
│   ├── PageLayout.test.tsx         # cover inline (default) vs stacked (opt-in) header
│   └── Pager.tsx                   # mobile full-touch-height Prev/Next; compact at `>= tablet` (FR-004)
├── features/
│   └── notifications/
│       ├── NotificationsPage.tsx       # opt into stacked header; keep inline `>= tablet` (FR-002)
│       ├── NotificationsPage.test.tsx  # header inline `>= tablet` / stacked `< tablet`; 10/page unchanged
│       ├── NotificationRow.tsx         # per-row Mark-read inline `>= tablet`, full-width 34px `< tablet` (FR-003, FR-005)
│       └── NotificationRow.test.tsx    # Mark-read placement per breakpoint; unread never color-only
└── routes/
    └── NotificationsPage.tsx           # thin re-export — no change expected
```

## Implementation Phases

### Phase 1: `PageLayout` opt-in stacked header + Pager touch height

- Add `stackActionsOnMobile?: boolean` (default `false`) to `PageLayout`; when set, switch the header to a mobile-first stack (`flex-col` at base, `tablet:flex-row tablet:items-center` at `≥ tablet`) with the actions cluster on its own row `< tablet` and right-aligned inline `≥ tablet`. Default path renders unchanged markup.
- Update `PageLayout` JSDoc to document the prop and the default-off contract.
- Grow `Pager`'s Prev/Next buttons to full touch height at `< tablet` (e.g. `h-[38px] tablet:h-9`), leaving label + `aria-live` untouched.
- Tests: `PageLayout.test.tsx` asserts default (inline at all widths) vs opt-in (stacked `< tablet`, inline `≥ tablet`); confirm Connections/Help behavior is unchanged.

### Phase 2: Notifications header + row reflow

- `NotificationsPage`: pass `stackActionsOnMobile`; keep the existing `actions` cluster (filter/Refresh/Mark-all) and `contentClassName="max-w-[760px] gap-2"`.
- `NotificationRow`: make the Mark-read control inline/trailing at `≥ tablet` and a full-width ~34px button below the message + timestamp at `< tablet` (move it into the message column with responsive classes); preserve wash + dot + weight + `sr-only` "Unread:" for unread rows.
- Verify content column caps at 760px (desktop/tablet) without mobile horizontal overflow.

### Phase 3: Tests + a11y verification

- `NotificationsPage.test.tsx`: header actions inline `≥ tablet` / stacked `< tablet`; `PAGE_SIZE`/10-per-page and pager label unchanged; filter still signals active via `aria-pressed`.
- `NotificationRow.test.tsx`: Mark-read placement per breakpoint (inline vs full-width 34px below message); read rows show no control; unread distinguished without color.
- `vitest-axe` narrow-render assertion has no new violations; forced-colors/grayscale reasoning documented in the delivery doc.
