---
type: Spec
id: SPEC-101
title: "Shared Connections — Responsive Reflow"
description: "Makes the Shared connections page reflow across breakpoints so connection cards stack and wrap and the member drawers go full-width on small screens, with no change to content or actions."
spec_status: Completed
depends_on: [SPEC-095]
arc: responsive-and-files-ux
arc_order: 7
---

## Overview

The Shared connections management surface (`ConnectionsPage`) was built as a fixed
horizontal layout: each connection is a single row with its name/pills/meta on the left
and its action buttons right-aligned, and the member drawers open at a fixed 440px width.
On narrow viewports the row overflows — long database-name + role/status pills collide,
the action cluster gets squeezed, and the 440px drawer is wider than a phone. This spec
makes the Connections surface responsive across the SPEC-095 breakpoints (mobile `< tablet`,
tablet `tablet` 900–1299px, desktop `desktop` ≥1300px) using a mobile-first reflow. It is a
**presentation-only** change: cards keep the same content and actions, they simply stack,
wrap, and go full-width on small screens, and the Manage-members / roster drawers opt into
the SPEC-095 `Drawer` `mobileVariant="full-height"` sheet below `tablet`. No behavior, data,
membership, service, IAM, or infra changes.

## Scope

### In Scope

- Responsive reflow of the connection card (`ConnectionRowItem`): single horizontal row
  `≥ tablet`, stacked layout `< tablet`.
- Mobile card actions become full-width (single action) or split 50/50 (two actions).
- Tablet (`tablet`) header treatment: shorten the "New shared connection" button label to
  "New" and trim the page subtitle; single-row cards that wrap only when name + pills would
  collide.
- Empty state, provisioning, and failed cards reflow with the same rules; inapplicable
  actions stay disabled/hidden exactly as today.
- Manage-members (`ManageMembersDrawer`) and roster (`MemberRosterDrawer`) opt into the
  SPEC-095 `Drawer` `mobileVariant="full-height"` sheet below `tablet`.
- Status stays legible at every size — dot + text label, never color-only
  (design-system.md §7).

### Out of Scope

- Any change to the shared-spaces control plane, membership, verbs, notifications, IAM,
  infra, services, hooks, or data shapes.
- Any change to the `Drawer`, `Modal`, `Button`, or `PageLayout` components themselves
  (the `mobileVariant` mechanics ship in SPEC-095; this spec only opts the member drawers
  into them).
- New tokens or breakpoints (reuse SPEC-095 breakpoints and `App.css` tokens).
- Restyling `CreateSharedConnectionDialog` (already responsive via SPEC-095; reference
  only).
- Copy/wording changes beyond the tablet subtitle trim and button-label shorten.

---

## Functional Requirements

### FR-001: Desktop card layout unchanged

#### Description:

At `desktop` (≥1300px) and `tablet`, a connection card renders as a single horizontal row: the
`min-w-0 flex-1` content block (mono name + role pill + status badge on line 1, meta below)
on the left, the action cluster right-aligned via `flex-none`. Page content stays left-
aligned and capped at ~920px.

#### Acceptance Criteria:

- [ ] At `≥ tablet`, each `ConnectionRowItem` is a single horizontal row with content left and
  actions right-aligned (no stacking).
- [ ] The action cluster stays `flex-none` and does not shrink the name block below its
  `min-w-0` truncation behavior.
- [ ] Page content remains left-aligned and capped at `max-w-[920px]`.
- [ ] The desktop rendering is visually unchanged from the pre-SPEC-101 layout (no
  regression).

### FR-002: Tablet header + single-row cards

#### Description:

At the `tablet` breakpoint, the page header's primary button label shortens from
"New shared connection" to "New", and the subtitle trims to a shorter form so the header
fits without wrapping. Cards remain single-row and only wrap the pills to a second line
when the name + pills would otherwise collide.

#### Acceptance Criteria:

- [ ] At `tablet`, the primary action button reads "New" (accessible name still conveys the
  full intent, e.g. `aria-label="New shared connection"`); at `≥ desktop` it reads
  "New shared connection".
- [ ] At `tablet`, the page subtitle renders its trimmed form (a shorter single line that does
  not wrap in the header).
- [ ] At `tablet`, a card stays a single row; the role/status pills wrap under the name only
  when the name + pills exceed the available inline width.
- [ ] The Refresh control remains visible and usable in the header at `tablet`.

### FR-003: Mobile card stacking

#### Description:

Below `tablet`, each card stacks vertically: name on line 1, role/status pills wrapping to
line 2 (under the name), meta on line 3, and the failed-reason line (when present) below
the meta. The name still truncates rather than forcing horizontal overflow.

#### Acceptance Criteria:

- [ ] At `< tablet`, the card content stacks: name (line 1), role + status pills (line 2, below
  the name), meta (line 3).
- [ ] Pills wrap under the name on mobile — they are not on the same line as the name.
- [ ] The mono name truncates within the card width and never causes horizontal scroll of
  the page.
- [ ] The failed-reason line, when the status is `failed`, renders below the meta line.

### FR-004: Mobile full-width / split card actions

#### Description:

Below `tablet`, a card's action buttons move to a full-width row at the bottom of the card.
A card with a single applicable action renders that button full-width; a card with two
applicable actions splits the row 50/50. The page-header "New" button spans full width at
`< tablet`.

#### Acceptance Criteria:

- [ ] At `< tablet`, card actions render as a full-width row beneath the card content (not
  right-aligned inline).
- [ ] A card with one action (e.g. a provisioning owner card showing a disabled Manage)
  renders that button full-width.
- [ ] A card with two actions (owner active: Manage + Delete; member active: View members +
  Leave; failed: Dismiss + Retry) splits the row 50/50.
- [ ] At `< tablet`, the page-header primary ("New") button spans the full content width.
- [ ] At `≥ tablet`, actions return to the right-aligned inline cluster (FR-001).

### FR-005: Member drawers become full-height sheets on mobile

#### Description:

`ManageMembersDrawer` and `MemberRosterDrawer` pass `mobileVariant="full-height"`
(SPEC-095) to the shared `Drawer`, so below `tablet` "Manage" and "View members" open a
full-screen (full-height, full-width) sheet instead of the 440px side panel. At `≥ tablet`
they keep the 440px drawer.

#### Acceptance Criteria:

- [ ] `ManageMembersDrawer` renders its `Drawer` with `mobileVariant="full-height"`.
- [ ] `MemberRosterDrawer` renders its `Drawer` with `mobileVariant="full-height"`.
- [ ] At `< tablet`, opening "Manage" or "View members" presents a full-height sheet (per the
  SPEC-095 sheet mechanics).
- [ ] At `≥ tablet`, both drawers keep the existing 440px side-panel presentation.
- [ ] The drawer header accessory (Refresh + Add members), members list, and nested
  Add/Remove dialogs remain usable inside the mobile sheet.

### FR-006: Status legibility and reflowed empty/provisioning/failed states

#### Description:

The status badge remains a dot + text label at every size (color is never the only
signal). The empty state, provisioning cards, and failed cards reflow with the same
stacking/full-width rules as active cards, and actions that don't apply stay disabled or
hidden as today.

#### Acceptance Criteria:

- [ ] `StatusBadge` renders both a dot and the `connectionStatusLabel` text at mobile,
  tablet, and desktop widths (no color-only state).
- [ ] The empty-state panel and its copy remain readable and non-overflowing at `< tablet`.
- [ ] A provisioning owner card at `< tablet` stacks and shows a full-width disabled "Manage"
  (Delete hidden while non-active), matching the desktop enable/disable rules.
- [ ] A failed card at `< tablet` stacks, shows the reason line, and splits Dismiss + Retry
  50/50.
- [ ] Transient (`provisioning`/`leaving`/`deleting`) status dots keep their pulse at all
  sizes.

---

## Data Model

No new or changed types. `ConnectionRow`, `Member`, `SharedConnectionRole`, and
`SharedConnectionStatus` (in `apps/portal/src/features/shared-spaces/sharedSpaces.types.ts`)
are unchanged; this spec touches only presentation/className logic in the components below.

## File & Folder Structure

```
apps/portal/src/
├── features/
│   └── shared-spaces/
│       ├── ConnectionsPage.tsx          # header (tablet "New" label + trimmed subtitle);
│       │                                 # ConnectionRowItem reflow (stack < tablet, single-row ≥ tablet,
│       │                                 # full-width/50-50 mobile actions); StatusBadge unchanged
│       ├── ConnectionsPage.test.tsx      # (new/updated) assert reflow rules per FRs
│       ├── ManageMembersDrawer.tsx       # add mobileVariant="full-height" to <Drawer>
│       └── MemberRosterDrawer.tsx        # add mobileVariant="full-height" to <Drawer>
```

Reference only (already responsive via SPEC-095, not modified here):
`apps/portal/src/features/shared-spaces/CreateSharedConnectionDialog.tsx`,
`apps/portal/src/components/Drawer.tsx`, `apps/portal/src/components/PageLayout.tsx`.

## Implementation Phases

### Phase 1: Card reflow

- Restructure `ConnectionRowItem` to a mobile-first layout: stacked container `< tablet`
  (name / pills / meta / reason), switching to the current single-row
  `flex items-center gap-3` at `tablet` and up.
- Move the action cluster into a full-width bottom row at `< tablet` (single = full-width,
  two = 50/50 grid) and back to the right-aligned `flex-none` inline cluster at `≥ tablet`.
- Ensure name truncation, `min-w-0`, and the `StatusBadge` dot + label hold at every size.

### Phase 2: Header + drawer sheet opt-in

- In `ConnectionsPage`, render the primary button label as "New" at `tablet` and
  "New shared connection" at `≥ desktop` (keep the full accessible name), and provide the
  trimmed subtitle at `tablet`; keep Refresh visible.
- Add `mobileVariant="full-height"` to the `Drawer` in `ManageMembersDrawer` and
  `MemberRosterDrawer`; verify header accessory, members list, and nested dialogs work in
  the mobile sheet.

### Phase 3: States + tests

- Verify empty, provisioning, leaving/deleting, and failed cards reflow correctly and keep
  the existing enable/disable/hidden action rules.
- Add/adjust `ConnectionsPage` tests asserting the binary criteria: single-row `≥ tablet` vs
  stacked `< tablet`, pills wrap under the name on mobile, full-width/50-50 mobile actions,
  "New shared connection" → "New" at `tablet`, member drawers pass `mobileVariant="full-height"`,
  and status is never color-only.
