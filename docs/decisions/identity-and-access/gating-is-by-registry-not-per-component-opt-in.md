---
type: Decision
title: "Gating is by REGISTRY, not per-component opt-in (SPEC-163)"
description: "`GATED_SURFACES` names every surface each flag hides and one test walks it in both states; consumers ask through `useFeature`, `FeatureGate` or `useFeatureSet`, and a hidden surface is removed from the tree, never `display: none` or disabled."
---

**`GATED_SURFACES` names every surface every flag hides — 26 rows, keyed by flag — and one test
walks it in both states.** Not a checklist and not a convention: a row carries the surface's
ACCESSIBLE NAME, and `gatedSurfaces.test.tsx` renders each twice (flag off, flag on) and asserts
by that name. A row it cannot make disappear fails; a row with no reach-recipe fails; a recipe
with no row fails; an empty registry, or a flag with zero surfaces, fails.

**THE TABS ARE THE EASY PART, AND THAT IS THE WHOLE ARGUMENT.** "Create table from this folder"
lives on a file-browser toolbar and is a *Query* feature. "Share table" lives in the Query rail
and pushes into *Shared Workspaces*. "Check data quality" is a button on a file-browser selection. A
per-component pass finds three of those and ships the fourth visible — the failure mode
`reviewer-contract.md` records from log-forge's SPEC-033. Adding a fifth entry point is now a registry
edit rather than a discovery exercise.

**The reach-recipes live in the TEST, not in the registry.** The registry stays declarative and
reviewable by someone who has read no component; the driving (open this drawer, expand that
node, click that menu) is test business. A guard asserts the two sets are equal, so they cannot
drift.

**One sanctioned door, and it is now absolute.** `useFeature(key)` answers "is this on?";
`FeatureGate` wraps; `useFeatureSet()` serves the three consumers that genuinely cannot ask one
question — `Header` builds one predicate for two nav components, `FeatureRoute` must tell "off"
from "not known yet", `LandingPage` picks the first enabled destination. **A tripwire test fails
if any module outside `features/feature-flags/` so much as names `useFeatureFlags`.** The spec
asked that nothing else read it; enforcing it by reading the source is stronger than asking,
because the convention is exactly what an urgent change forgets. The failure it prevents is not
exotic: a consumer that forgets `'loading'` must read as OFF makes a tab flicker, or lets a page
fetch before the answer arrives.

**Hidden means REMOVED, never `hidden` and never disabled.** A visually-hidden control is still
in the accessibility tree, still focusable and still announced — so `display: none` would leave
a screen-reader user able to reach a feature the environment says is not there. `FeatureGate`
renders no wrapper element at all, and the Share-table kind toggle renders **no toggle** rather
than a single-option radio group, which is a control that asks a question with one answer and
implies the other option exists somewhere.

**A gated route keeps its path and swaps its ELEMENT.** It must still match, or a disabled
feature falls through to `*` and tells a user with a perfectly correct link that their URL is
wrong. `FeatureUnavailablePage` says "not available in this environment" — a property of the
deployment, not of them — names no reason and offers no appeal route, because a flag is
presentation and inventing one would imply a permission model that does not exist.

**`FeatureRoute` renders `LoadingState` while the flags resolve, and that is not a contradiction
of "render nothing while loading".** The rule is right for a tab and wrong for a whole viewport:
an empty frame reads as a broken page where an absent tab reads as a tab that was never there.
What actually matters is that **the page does not MOUNT** — every gated page fetches on mount,
and on `/data-quality/:space/:requestId` an optimistic render would make a disabled feature an
existence oracle for someone else's report (SPEC-113's rule, inherited).

**`components/` still imports no feature.** `PrimaryNav` and `AppNavDrawer` take an
`isPathEnabled` **predicate**, supplied by `Header` — the one place that knows both the auth
state and the flags. Required, never defaulted: a default would make an unwired caller ship every
tab while looking correct. Both nav surfaces get the SAME predicate, because a tab hidden in the
topbar and present in the mobile hamburger is a feature that is still one tap away.

**`?space=` with shared workspaces off is NOT READ, not resolved-and-refused.** `useFileSpace`
gained `ignoreSpaceParam`; routing it through the existing `fellBack` path would raise "That
shared space is no longer available", which is a false statement about a space that is fine and
that returns the moment the flag flips back. `useConnections` still resolves normally — a flag
may not touch a service (SPEC-162 FR-006).

**Shared databases in the Query schema rail joined the contract (a deliberate extension).**
Leaving `teamspace` browsable while the spaces list and `/connections` are gone reads as a bug
rather than a policy. **Filtered at the VIEW, never at the service:** `useConnections` still
fetches every space, and a saved query naming a hidden database still RUNS. Hiding a surface is
not revoking access, and the grants are untouched.

**A REACH-RECIPE THAT RE-IMPLEMENTS THE GATE PROVES NOTHING, and two of them did.** The rows for
the Files spaces rail and the Query rail's shared databases originally rendered test-local host
components carrying their own `useFeature(...) ? … : null`. Measured in review: deleting BOTH
real gates left all 1843 tests green. Recipes now render the real page, and the same mutation
fails exactly those two rows. The rule generalises — a recipe may drive the app but may never
restate the condition under test.

**The off-half must be asserted AFTER settling, never inside `waitFor`.** `useFeature` reports
`false` while the flags resolve, so a retry loop's first attempt lands at the one moment every
surface is legitimately absent — and an ungated surface that merely renders asynchronously
passes. Each recipe carries an `anchor` (something present regardless of the flag) and absence
is asserted once. The same review found the paired sloppiness: `Go to Dashboard` was matched by
`/^Go to /`, which also matches the "Go to Query" the page correctly renders with Files off.

**`useFeatureFlags` distinguishes THREE auth states, not two.** Still-resolving is `'loading'`;
**settled with no user is `'fallback'`**, because a session with no credentials genuinely has
the compiled-in defaults in force. Collapsing the two made the documented no-AWS local workflow
a permanent spinner behind every gated route — `FeatureRoute` never left its neutral state.
Going the other way (treating still-resolving as fallback) would show every gated surface and
take it away a tick later, which is the flicker FR-007 exists to prevent.

**Hiding a surface is not hiding a WRITE PATH, and the first pass missed that.** With shared
workspaces off, the spaces rail was gone but the move/copy destination picker still offered a
space selector and the data-quality start dialog still listed shared spaces — so a user could
still paste a file into `marketing_data`. Both are now filtered at the view and registered. A
row is "a way in", not "a button".

**Test-harness consequence, and it bit before it was understood.** Gating made every gated
surface wait on a fetch, so `renderWithProviders` now seeds the flags all-on by default
(`seedFeatureFlags`, opt-out) — the same answer production reaches when the document is
unreadable. **`setQueryDefaults` must run before `setQueryData`**: the test client uses
`gcTime: 0`, so an observer-less seed is evicted the instant it is written, and every gated
control that mounts LATER — inside a drawer the test has to click open — starts from a cold
pending query and reads as flagged off. It passed every first-paint assertion and failed only
behind a click.

## History

### 2026-08-10

- **Settled:** SPEC-163.
