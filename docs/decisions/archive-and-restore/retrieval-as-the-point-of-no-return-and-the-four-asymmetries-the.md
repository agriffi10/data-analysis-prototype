---
type: Decision
title: "Retrieval as the point of no return, and the four asymmetries the restore introduces (SPEC-171)"
description: "Retrieval is where a restore becomes billed and uncancellable, so the guard runs twice, the two Maps tolerate opposite failure, the poll budget keeps headroom, and the gate protects the archive."
---

This heading grouped the decisions below when one file held the area. Each now has a file of its own:

- [The destination guard runs TWICE, because this spec turned a guarantee into a promise](the-destination-guard-runs-twice-because-this-spec-turned-a-guarantee.md)
- [The retrieval Map tolerates NO failure, and the copy tolerates every one](the-retrieval-map-tolerates-no-failure-and-the-copy-tolerates-every-one.md)
- [Completion is the `Restore` header, and an ABSENT header is a failure](completion-is-the-restore-header-and-an-absent-header-is-a-failure.md)
- [The retrieval budget has deliberate headroom, and the ceiling moved for the whole plane](the-retrieval-budget-has-deliberate-headroom-and-the-ceiling-moved-for.md)
- [The restore's gate is the commit gate's MIRROR IMAGE, not its twin](the-restores-gate-is-the-commit-gates-mirror-image-not-its-twin.md)
- [The receipt is rewritten, never re-rendered, and the counts come from the run](the-receipt-is-rewritten-never-re-rendered-and-the-counts-come-from-the.md)
- [The metadata fix: a latent bug on all three planes, surfaced by a round trip](the-metadata-fix-a-latent-bug-on-all-three-planes-surfaced-by-a-round.md)

## History

### 2026-08-10

- **Settled:** SPEC-171.
