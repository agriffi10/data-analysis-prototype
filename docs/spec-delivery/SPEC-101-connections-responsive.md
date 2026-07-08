# Completed Spec — SPEC-101: Shared Connections Responsive Reflow

## What was completed?

The Connections management surface reflows across the SPEC-095 breakpoints. Presentation only — no control-plane/membership/service/IAM change; **all pure CSS on one component tree** (no mount-gate).

- **Card (FR-001/003/004):** `ConnectionRowItem` is `flex flex-col … tablet:flex-row tablet:items-center` — stacked on mobile (name / pills / meta / reason), single horizontal row with a right-aligned `flex-none` action cluster at ≥ tablet. Pills wrap **under the name** on mobile via a wrapper that becomes `tablet:contents` (its children fold into the inline row at ≥ tablet). Actions build into an array rendered as a full-width `grid grid-cols-1|2` (single = full-width, two = 50/50) on mobile, `tablet:flex tablet:w-auto` inline at ≥ tablet; each button `w-full tablet:w-auto`.
- **Header (FR-002):** opts into `PageLayout` `stackActionsOnMobile`; the primary button reads **"New"** below desktop / **"New shared connection"** at desktop (visible spans) with a stable `aria-label="New shared connection"` and `w-full tablet:w-auto`; the subtitle's second sentence is `hidden desktop:inline` (trimmed below desktop; not doubled for AT).
- **Member drawers (FR-005):** `ManageMembersDrawer` + `MemberRosterDrawer` already pass `mobileVariant="full-height"` (added in SPEC-095) → full-height sheet below tablet.
- **Status (FR-006):** `StatusBadge` (dot + `connectionStatusLabel` + transient pulse) unchanged — never color-only.

## What changed from earlier specs?

- `ConnectionsPage` (SPEC-052) card + header reflowed; consumes the SPEC-102 `stackActionsOnMobile`. No data/behavior change.

## Verification

`format` + `lint` + `tsc -b` + `build` clean; full suite green (1118, +7). New tests: card stacked-mobile/row-at-tablet, pills stack, two-action 50/50 grid + single-action full-width, "New" label + full accessible name, stacked header, and Manage opening as a **full-height** sheet variant. Auth-gated page not browser-verified (preview can't hold a Cognito session).
