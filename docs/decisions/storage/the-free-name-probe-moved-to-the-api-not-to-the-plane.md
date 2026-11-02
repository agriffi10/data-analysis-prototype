---
type: Decision
title: "The free-name probe moved to the API, not to the plane (SPEC-198, amends SPEC-187)"
description: "**The free-name probe moved to the API, not to the plane** — 999 round trips would be strictly worse than the loop it replaced. `numberedName` lives in Python only, and **exhaustion is now distinguishable from failure** (409 + `attempts`), which it was not."
---

`firstFreeName` walked `(1)` … `(999)` with a `HeadObject` per candidate, inside the browser. Behind
the API each probe becomes a browser → API → S3 round trip, which is **strictly worse than what it
replaced** — so the walk is one route, `POST /v1/objects/free-name`, declared `idempotent: true`
(the route SPEC-197 FR-008 names as the reason idempotency is declared rather than derived from the
method: a POST that resolves a free name is a read).

**`numberedName` moved to Python and the TypeScript copy is deleted.** Two implementations of a
naming rule look identical until one of them changes.

**Exhaustion and failure are now distinguishable, and they were not.** The old loop returned `null`
both when 999 names were taken and when a probe errored, and the caller rendered one sentence for
either. The route answers **409 `Conflict`** with `params: {attempts}` on exhaustion; anything else
carries its own code.

> **This amends two written records in place.** `ARCS.md`'s residual note and SPEC-187's table row
> both say *the probe stays in the browser*. It left the browser for the **API**, not for the plane —
> the distinction matters, because the plane would have made a same-folder copy asynchronous.

## History

### 2026-08-29

- **Settled:** SPEC-198, amends SPEC-187.
