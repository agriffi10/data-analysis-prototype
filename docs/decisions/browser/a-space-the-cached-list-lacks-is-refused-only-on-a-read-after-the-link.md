---
type: Decision
title: "A `?space=` the cached list lacks is refused only on a read after the link (2026-09-15)"
description: "A space link the cached list lacks waits, through `useSpaceLinkPending`, for one read settled after the link before it is refused; presence is trusted at once, and a POP is not a follow. **The refusal is a verdict on a read after the link, never on `isLoading`**, which clears on any cached list, however old — every cold-load test passes while a just-joined space is refused; a link consumer calls `useSpaceLinkPending`."
---

A Files link naming a space missing from the cached connections list fell back at once, under
"That shared space is no longer available", whenever no read of the list was due. That covered a
list inside its 30-second `staleTime`, as when a notification is followed moments after joining,
and a link followed on a Files page already open, which does not remount and so owes no read.
Nothing read the list again, so the false notice stood until a manual Refresh.

**A miss now waits for one read that settles after the link, and asks for it when none is due**
(Andrew's ruling, over leaving it as it was). The link is `pending` meanwhile, showing "Loading
files…" and no browser, and then opens the space or falls back with a notice that is now true. The
cost is one extra read of the user's connections list for each link to a space that is really gone
or not yet usable, plus one round trip of loading before its notice. Presence is still trusted at
once, since only an absence is refused on the list's word. Offline, such a link waits on "Loading
files…" until the connection returns and the read runs, as a cold load already did, where a cached
list used to refuse it at once.

**The wait is anchored at the link, and measured by count.** `useConnections` exposes TanStack's
own update counters, the pair behind `isFetchedAfterMount`, as `listReadsSettled`. `useSpaceLinkPending`
notes the count whenever a link is followed, noting it again during render. A link is the
navigation as well as the `?space=` value: while the notice shows, the address still names the
space, so following the same link again changes only the navigation, and keyed by the value alone
that second follow was refused on the first follow's read. **A POP is not a follow**, and the
exclusion is load-bearing: an in-page anchor — the shell's own skip link — is a same-document
navigation whose entry carries no history state, so the key falls back to "default" and every such
click would re-arm the wait, unmounting the browser and spending a read on the keyboard users the
bypass link exists for. That was measured in Chromium and is driven in the test, because jsdom
follows no in-page anchor on a click. The mount-anchored predicate this replaced cannot see a link
that arrives after mount at all: keep the count but never re-anchor it, and the two tests that
follow a link on an open page go red. A failed read counts too, so a failure ends the wait
rather than loading for ever. The
re-read passes `cancelRefetch: false`, so the read owed on mount answers the link rather than being
cancelled and sent again, and the stale-list row counts reads to hold that.

**Extended to the other two links (2026-09-16, Andrew's ruling).** The Data Explorer's `?space=` and a
Data Quality report's `:space` resolved against the same list and waited only on `isLoading`, so both
refused a just-joined space the same way. The report's refusal was reachable through a completion
notification followed in a second tab. The Explorer's was reachable only through Back and Forward,
since its one link source, the Query rail, builds from the same list. The anchor now lives in one
hook, `useSpaceLinkPending`, which each surface calls with whether its own resolution found the space,
so the POP rule is written once rather than three times. The Explorer keys the wait on its resolver's
`denied`, which keeps the flag rule in the resolver alone: with shared workspaces off `?space=` is
never read, so nothing is refused or waited on. **The Data Quality runs page is left alone.** It
follows no link and refuses nothing; a list without a just-joined space leaves that space's runs out
until the next read, the same staleness the Files sidebar and the Query rail have, and making it wait
would spend a read on every visit.

## History

### 2026-09-16

- **Changed:** Extended from Files to the Data Explorer's `?space=` and a Data Quality report's `:space`, with the anchor moved into one hook.

### 2026-09-15

- **Settled:** entered the register.
