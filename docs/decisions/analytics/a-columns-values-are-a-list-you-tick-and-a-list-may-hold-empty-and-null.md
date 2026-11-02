---
type: Decision
title: "A column's values are a list you tick, and a list may hold (empty) and NULL (SPEC-249)"
description: "**Filter by value…** lists at most 1,000 values, most common first, narrowed by the other filters and never the column's own, in a billed listing started only by a gesture; search runs no query, and `in` carries NULL beside the list while `notIn` excludes NULL rows."
---

Outside reviewers comparing the Data Explorer with DBeaver asked for **Filter by value** to list a
column's values and let the user tick several, and Andrew approved it on 2026-09-28, twelve days
after cancelling the same feature as SPEC-241. The spec reused 241's reviewed decisions on the
query, the cost and the lifecycle, and added **is not one of**, NULL and (empty) as values, and the
rename of the Options item.

**The list is narrowed by the OTHER filters and the expression, never the column's own, and the
caller says what narrows it.** DBeaver lists the whole table's values (dbeaver/dbeaver#21416 asks
otherwise); the spreadsheet behaviour is the one users expect, and the column's own filter is left
out so a value it excludes can be ticked back. `renderColumnValuesSql` takes the narrowing as an
argument, because the AND/OR builder must pass none: inside an OR group, narrowing a condition's
values by its siblings hides the values the OR exists to reach.

**At most 1,000 values, most common first, with a total from `COUNT(*) OVER ()`.** The window was
proven on Athena before it was designed on — over 10,000,000 generated groups it ran in 4.0 s
against 3.1 s without it, and over 40,000,000 in 16.3 s, so its single-node count is not the
resource risk a reviewer suspected. **Search runs no query**: a billed scan per keystroke is the
cost this feature must not have, and a value past the 1,000 is typed with **Filter: is one of…**.

**A listing is billed work, started by a gesture and by nothing else.** It is cached under
`explorerKeys.execution`, so a catalog change drops it with the explorations over that table. But
`resetQueries` refetches every OBSERVED entry, so the start is a `fetchQuery` that nothing observes:
an eviction drops it, and only the next opening starts one. **Every requester waits on the
`runQuery` call itself, kept in an in-flight map by cache key and per query client, never on
`fetchQuery`'s promise.** An eviction during the start cancels the cache's copy while the call runs
on, and a second tab asking for the same statement joins the call rather than the cache; a key
remembers which start it waits on, so one an eviction forgot asks again, and the map outlives a
remount of the Explorer, which would otherwise pay for the start twice. The first build hung its bookkeeping
on the cache's promise and the query function; the diff review drove both escapes — a start that
failed after the cancel left its key "counting" forever, and a joining tab was never linked or
billed. The
provider sits above the source picker, since New tab unmounts the tab panel and would take a
running listing's watch with it. *Cancel* stops nothing: `stopQuery` would bill the part scanned
and leave nothing to show.

**NULL rides beside the list, and only `in` can carry it.** `c IN (…, NULL)` never matches a NULL
row, so `in` renders `(c IN (…) OR c IS NULL)`, and a list of only NULL renders `c IS NULL` while
staying a list, so both editors reopen it as one. `notIn` keeps SPEC-238's rule that it excludes
NULL rows; the picker shows that NULL entry ticked and locked. **Rejected:** changing `notIn` to
keep NULL rows unless listed — it would change every stored `notIn` filter and part with `<>`,
which follows the same SQL rule. The typed field keeps working by gaining **(empty)** and **NULL**
boxes rather than refusing such lists; without them, applying *Order and filter* untouched dropped
both, since it re-parses every list row.

**The typed items stay.** **Filter: is one of…** remains the way to paste a long list of known
values, beside **Filter by value…** rather than replaced by it.

## History

### 2026-09-28

- **Settled:** SPEC-249.
- **Changed:** Approved twelve days after the same feature was cancelled as SPEC-241, reusing its reviewed query, cost and lifecycle decisions.
