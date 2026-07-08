# Completed Spec — SPEC-103: Help & Guides Responsive Layout

## What was completed?

The `/help` page reflows across the SPEC-095 breakpoints. Presentation only — content model, routing, and hash-selection logic unchanged.

- **Rail (FR-001/002):** `HelpSidebar` stays a vertical rail at ≥ tablet — `w-[220px] desktop:w-[248px]` (narrower at tablet, 248px at desktop). Labels: **full at desktop, short at tablet** (only `shared-connections` → "Shared"), picked in JS via `useBreakpoint().isDesktop` (not two CSS spans — avoids doubling the button's accessible name). Short-label map is presentation-only, co-located in `HelpSidebar`.
- **Mobile chips (FR-003):** new **`HelpSectionChips`** — a `<nav aria-label="Guides sections">` horizontal `overflow-x-auto` single-row of chips (`shrink-0 whitespace-nowrap`), active chip highlighted (`aria-current`), driving the same hash `onSelect`.
- **Shared state / one selector (FR-004):** `HelpPage` **mount-gates** rail-vs-chips with `useIsMobile` (`{!isMobile && <rail>}` / `{isMobile && <chips>}`), so exactly one selector exists per width (a CSS swap would duplicate the section buttons in the DOM).
- **Card reflow (FR-005):** `HelpGuideCard` step content is `px-[18px] … tablet:pl-[68px]` (mobile uses the card gutter instead of over-indenting under the header icon); steps + callouts + accordion unchanged. No search control added anywhere.

## What changed from earlier specs?

- `HelpSidebar` (SPEC-074) gained tablet width + short labels; `HelpPage` now renders one of two selectors by width; `HelpGuideCard` step padding is responsive. No content/type change.

## Verification

`format` + `lint` + `tsc -b` + `build` clean; full suite green (1111, +11). New tests: `HelpSectionChips` (labelled nav, one active chip, `onSelect`, single-row, axe); `HelpSidebar` short-label at tablet / full at desktop; `HelpPage` rail-at-≥tablet-vs-chips-on-mobile exclusivity, chip selection via hash, and **no search control** at 400/1024/1400px. Auth-gated page not browser-verified (preview can't hold a Cognito session).
