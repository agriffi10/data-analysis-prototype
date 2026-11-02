---
type: Decision
title: "What did not move, and why"
description: "The extraction moved the domain, not its consumers: `SchemaBrowser`, `DatabaseNode` and `QueryResultsTable` stay in `features/query/`, and the pure `formatBytes` lives in `lib/format.ts`."
---

`SchemaBrowser`, `DatabaseNode`, `QueryResultsTable` and every dialog stay: the Data Explorer's
picker and grid are different components with different requirements, and SPEC-155's precedent is to
move the *domain*, not every consumer. The display page-size constants stay too —
`MAX_RESULTS_PAGE_SIZE` is a SPEC-087 workspace preference, not a property of Athena. `formatBytes`
went to `lib/format.ts` rather than into `catalog/`: it is a pure formatter with no catalog domain,
and both features render the same scanned-bytes figure.

## History

### 2026-08-13

- **Settled:** entered the register.
