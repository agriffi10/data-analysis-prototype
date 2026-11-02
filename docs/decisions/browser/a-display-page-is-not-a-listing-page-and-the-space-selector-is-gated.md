---
type: Decision
title: "A display page is not a listing page, and the space selector is gated (SPEC-174)"
description: "**A display page is not a listing page.** A pager over filtered rows keeps fetching while the listing is truncated — and **stops on error**, because a failed fetch leaves \"has more\" true, which is the fill's own trigger: without the guard one failure spins forever. **The space selector is gated at the view** on `sharedWorkspaces`: with it off, it offers the personal space alone."
---

**Decision (2026-08-11).** The saved-queries surfaces page over **filtered rows**, never over S3
keys, and the two counts do not track each other. SPEC-173's store returns only the top-level
`.sql` files of a folder it deliberately left ordinary, so one `ListObjectsV2` page of 25 keys can
yield 25 rows, three, or **zero while more pages remain**. Paging the listing directly would render
a folder of two hundred CSVs and one saved query as an empty list with a "Load more" the user has
to guess the meaning of.

`useSavedQueriesPager` therefore **keeps fetching while the listing is truncated and it holds fewer
rows than the page in view needs.** Two bounds make that safe and neither is optional: the
listing's own end (`hasNextPage` goes false), and **an error stops the fill** — a failed
`fetchNextPage` leaves `hasNextPage` true and `isFetchingNextPage` false, which is exactly the
condition the effect fires on, so without the error guard one failure spins forever.

While it fills, the surface reads as **loading**. `isFilling` (no rows yet, pages remain) is a third
state beside `isEmpty` (listing exhausted, no rows) and the first-page load, because the two
alternatives are both wrong: an empty state that a fetch is about to contradict, and a pager
reading `0–0 of 0+`. The label carries `Z+` while pages remain for the same reason — S3 reports no
total, and `24` and `at least 24` are different claims.

**The window advances past the loaded rows and the clamp holds the view.** Next sets the index
beyond what exists; `safeIndex` clamps it to the last real page while the fill runs, and the new
page lands when its rows arrive. That one mechanism also covers a delete emptying the last page,
which is why FR-005's "move to the new last page" needed no code of its own.

**The selector is gated, deviating from FR-001's "exactly the spaces `useQuerySpaces()` returns".**
With `sharedWorkspaces` off it offers **the personal space alone** (listed under the username). SPEC-163 already filters the connections
list and the schema rail on that flag; a dropdown still naming a colleague's space, moments after
every other shared-workspace surface disappeared, reads as a bug rather than a policy. The filter
is applied in `QueryWorkspace` — at the **view**, never in `useQuerySpaces` and never in a service
(SPEC-162 FR-006) — and it needed no new fallback: `useSavedQuerySpace` takes its spaces as a
**parameter** and already resolves an id naming nothing offered to personal, so a revoked
membership and a flag turning off travel the same path. It is a **new registry row** (*Shared
spaces in the saved-queries selector*), not a widening of *Shared databases in the schema rail*:
that row gates the connections the rail browses, this one gates a control reading a different hook,
and SPEC-163's rule is one surface per row. Its reach-recipe opens the **real drawer** on the
**real workspace**.

## History

### 2026-08-11

- **Settled:** SPEC-174.
