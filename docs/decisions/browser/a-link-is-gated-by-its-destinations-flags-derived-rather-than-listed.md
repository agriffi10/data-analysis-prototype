---
type: Decision
title: "A link is gated by its destination's flags, derived rather than listed (2026-09-25)"
description: "A control navigating into another feature asks `useCanFollowLink()`, whose `linkFlags` derives the destination's flags from the registry and the space the URL names, never from a hand-written list."
---

**A control that navigates into ANOTHER feature asks about the destination, not its own screen.**
`linkFlags(link, username)` returns every flag a destination needs — the route's own, read from the
registry's nav rows through `NAV_PATH_FLAGS`, and `sharedWorkspaces` when the URL names a space that
is not the viewer's personal one — and `useCanFollowLink()` answers whether all of them are on. The
notification row, "View source files" on the Query rail, the save-results toast's "View in Files",
the report's "Open folder" and the data-quality runs list all ask it.

**Why derived.** The notification row used to gate on a hand-written list of prefixes, and it
missed a producer twice: first a file-send link into `/files`, then the table builder's
`/query?refreshTable=…`, which stayed a live anchor into the unavailable page with `query` off. The
registry walk could not see either, because it only walks rows someone registered. Three in-app
controls had the same gap, found by an audit rather than a test. Deriving the route half from the
registry means a new producer or a new route is covered without anyone remembering it.

**A space is named four ways, and each route spells "personal" its own way.** `?space=` on
`/files` is a connection id (`personal`); on `/explore` it is `personal` or the username; the
refresh link names a database, where the personal one is the username; the report route's path
segment is the username. `linkFlags` holds one reader per route, each mirroring the reader that
route already uses, because a single rule would be right for one and quietly wrong for the others.
Parsing the link also retired a rule the producers carried: `?space=` no longer has to come first
for the gate to see it.

**A shared space's report is gated at the route too.** With `sharedWorkspaces` off,
`/data-quality/<shared>/<id>` renders the unavailable page and mounts nothing that reads, rather
than the report's own "not available" banner, which would say the report may have been deleted —
false about a report that returns the moment the flag does.

**Not built: a sweep for new literal paths.** Considered as a tripwire for the next control that
navigates without asking. A plain matcher over path literals hits comments, route declarations and
the registry itself far more than navigations, and narrowing it to call sites misses every link
built into a variable first — so it would have caught three of the six instances found and none of
the notification ones, which is where the class kept recurring. The derived notification gate
closes that half; the in-app half rests on the registry walk, and on registering a control when
it is added.

## History

### 2026-09-25

- **Settled:** entered the register.
