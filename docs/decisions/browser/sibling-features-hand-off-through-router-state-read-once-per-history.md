---
type: Decision
title: "Sibling features hand off through router state, read once per history entry (SPEC-242)"
description: "**Sibling features cross by router state, never by import.** `features/query/` and `features/data-explorer/` may not import each other, so a gesture on one that opens the other navigates with a hand-off whose builder and reader live in `lib/routeHandoff.ts` — one module per shape, and never the URL, which history and logs keep. The receiver reads it once per history entry (`location.key`: `StrictMode` runs the effect twice) and replaces the entry with no state whatever happened, so a reload or Back acts on nothing. **A `<StrictMode>` handed to a test as the element under test doubles nothing** — React double-runs effects only under the StrictMode it places — so `renderWithProviders({strictMode})` renders it as the root; a guard proven under the nested one is unproven."
---

`features/query/` and `features/data-explorer/` are fenced apart by lint, tests and `import type`
included, and *Explore in Data Explorer* is the first gesture that has to cross from one to the
other (SPEC-243's *Open in Query* is the second, the other way). The crossing is a navigation
carrying **router state**, and the shape of that state lives in `lib/routeHandoff.ts`: a builder the
sender calls, a reader the receiver calls, and one module owning every hand-off so the two sides
cannot drift. The reader refuses anything it did not build, by an own property (`Object.hasOwn`),
since history state can be anything a previous entry left there.

**Never the URL.** A statement can be long and can quote the user's own data, and a URL is kept in
history, in logs and in whatever the user pastes it into. The deep link to a table
(`/explore?space=&db=&table=`) is a different case: it names catalog objects, and it is meant to be
shared.

**Read once, keyed by the history entry.** `AppRoot` renders under `StrictMode`, so the receiving
effect runs twice on mount; a ref holding the `location.key` it last consumed is what opens one tab
rather than two. The entry is then replaced with the same path and search and **no state** — also
when the tab limit refused the tab, as the deep link drops its parameters either way — so a reload
or Back neither opens a second tab nor raises the limit dialog again. A mount with no hand-off state
replaces nothing. While an accepted hand-off is still in the entry, the page runs nothing for the
tab restored from the session, by the rule it already applies to an unsettled link.

**A link on the same entry goes first.** The deep link and the hand-off each replace the entry, and
both effects run in one flush, so the hand-off's replace — built from the render's `location` —
put back the parameters the link's had just dropped, and a reload opened the linked table again.
The hand-off now waits while a link is loading, refused or about to open, and the link's `clear()`
carries the entry's state across its own replace, so the hand-off is read on the entry that replace
produces. No sender combines the two today; the next one might.

**The StrictMode test was vacuous until the harness changed.** The first version passed with the
`location.key` guard deleted. A `<StrictMode>` handed to `render` beneath a provider wrapper runs
every effect once: React double-invokes effects only for a subtree whose placed root is, or sits
inside, a `StrictMode` — measured with a counting effect, one run nested and two at the root.
`renderWithProviders` gained `strictMode`, which renders `StrictMode` above the providers as the
root, and the guard's deletion now reddens.

**One lint suppression, and why.** The hand-off effect calls an effect event that opens a tab or
raises the limit dialog — the same state the deep link's effect sets. React Compiler's
`set-state-in-effect` flags one and not the other, and which it flagged turned on incidental features
of the event body, not on the state it sets. The line carries `eslint-disable-next-line` with that
reason rather than a reshaping written to slip past the analysis.

**Rejected.** A shared module both features import — the lint fence exists so that neither feature
grows a dependency on the other, and a shared hand-off *shape* in `lib/` gives the crossing without
it. `sessionStorage` — it outlives the navigation, so a stale hand-off would open on the next visit.

## History

### 2026-09-21

- **Settled:** SPEC-242.
