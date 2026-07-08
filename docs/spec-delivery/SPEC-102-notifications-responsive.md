# Completed Spec — SPEC-102: Notifications Page Responsive Layout

## What was completed?

The `/notifications` page reflows across the SPEC-095 breakpoints. Presentation only — no data/write-pipeline/IAM/service change.

- **`PageLayout` (FR-001):** new opt-in `stackActionsOnMobile?: boolean` (default `false`). When set, the header stacks below `tablet` (title on line 1, `actions` cluster on a full-width row beneath, left-aligned) and is the shipped inline row at `≥ tablet`. Default path renders the same class set as before, so Connections/Help are untouched.
- **Notifications header (FR-002):** `NotificationsPage` passes `stackActionsOnMobile`; content stays capped `max-w-[760px]`.
- **Per-row Mark-read (FR-003):** `NotificationRow` renders it as a compact trailing control at `≥ tablet` and a **full-width `h-[34px]` button below the message/timestamp** on mobile. **Mount-gated via `useIsMobile`** (one button — a CSS swap would duplicate it in the DOM).
- **Pager (FR-004):** Prev/Next grow to `h-[38px]` on mobile, `tablet:h-9` at ≥ tablet; label + `aria-live` + 10/page unchanged.
- **Unread affordance (FR-005):** wash + dot + weight + `sr-only` "Unread:" preserved at every width (unchanged).

## What changed from earlier specs?

- `PageLayout` (SPEC-060-era) gained `stackActionsOnMobile` (additive, default off). `Pager` (SPEC-038) Prev/Next now `h-[38px] tablet:h-9`. Both changes are inherited by every host but default to the prior look at `≥ tablet` (and the Pager is only taller on mobile).

## Verification

`format` + `lint` + `tsc -b` + `build` clean; full suite green (1100, +5). New tests: `PageLayout` default-inline vs opt-in-stacked header; `NotificationRow` Mark-read placement per breakpoint (trailing ≥ tablet / full-width 34px below on mobile, exactly one button) + read-row no-control + unread-not-color-only; `NotificationsPage` opts into the stacked header. Forced-colors/grayscale reasoning: unread is dot + weight + `sr-only` label (not color-only), so removing color still distinguishes it. Auth-gated page not browser-verified (preview can't hold a Cognito session).
