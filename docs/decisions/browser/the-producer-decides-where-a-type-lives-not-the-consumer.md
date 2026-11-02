---
type: Decision
title: "The producer decides where a type lives, not the consumer"
description: "Where a producer sits in a lower layer than its consumer, the type lives with the producer, as `DatabaseSchema` does in `catalog.types.ts`."
---

`useSchema.ts` moved carrying an import of `DatabaseSchema` from `sqlCompletions.ts`, which stays
behind — FR-001's "no catalog module imports from `features/query/`" broken by the first file moved.
`DatabaseSchema` is `{database: string; tables: GlueTableSummary[]}`: it had been declared beside the
completion provider that consumes it rather than the hook that produces it, and nobody had reason to
think of it as domain until the layers were separated. It is in `catalog.types.ts` now. Where a
producer sits in a lower layer than its consumer, the type belongs with the producer.

## History

### 2026-08-13

- **Settled:** entered the register.
