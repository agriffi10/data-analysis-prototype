---
type: Decision
title: "`no-restricted-imports` matches the SOURCE STRING, so a sibling rule needs relative patterns"
description: "`no-restricted-imports` matches the source string, so the sibling-feature clause needs relative patterns (`'../query/**'`) and is proven by committing a violation each way; tests are not exempt."
---

The SPEC-155 rule forbids `components/`, `lib/` and `hooks/` importing `**/features/**`, and it works
because those layers sit *above* `features/` and must name it: `'../features/query/queryKeys'`. The
sibling clause written the same way — `'**/features/query/**'`, `'**/features/data-explorer/**'` —
resolved onto exactly the right files and **caught nothing**, because one feature reaches another as
`'../query/queryKeys'`, which contains no `features/` segment at all. The load-bearing patterns are
the relative ones (`'../query'`, `'../query/**'`, `'../../query'`, `'../../query/**'`, and the same
four for `data-explorer`); the `**/features/…` globs stay for any path written the long way.

This is why FR-006 required the rule be **verified by committing a violation in each direction and
observing the failure**, not by reading the config. A rule that resolves onto the right files, prints
a correct `--print-config` and is written in the same shape as a working one is not a rule that
fires. `features/data-explorer/` is named in the rule before it exists, so the first file created
there lands under a guard already known to work.

**Tests are not exempt from this clause**, unlike the shared-layer rule above it. That exemption
exists because integration-style tests mount real features by design (react.md §21) — but a Query
test importing the Data Explorer is the coupling itself, not a mount of the tree under test.

## History

### 2026-08-13

- **Settled:** entered the register.
