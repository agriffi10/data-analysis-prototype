# Spec: File Converter — `finalize` + Terminal States

**ID:** SPEC-119
**Status:** Cancelled
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon`), SPEC-115 (foundation), SPEC-116 (authorization), SPEC-117 (the target schema), SPEC-118 (the `UNLOAD` path — `finalize` verifies its output)

> **Read `docs/file-converter-architecture.md` §5.3 first.**
> **Scope note:** this spec was originally "The Excel Path (`convert-excel`) + `finalize`". The Excel path was **removed from scope entirely by user decision 2026-07-13** — `.xlsx` is a terminal `unsupported_format` at inspection (SPEC-117 FR-001) — leaving `finalize` and the terminal states.

## Overview

One verb plus the machine's endgame. **`finalize`** decides whether the request actually succeeded; the terminal states shape what SPEC-121's notification is built from.

**Why `finalize` matters.** A conversion that half-succeeded is worse than one that failed. `UNLOAD` chooses its own output file names (SPEC-118 FR-003), so completeness can never be checked by predicting keys — `finalize` verifies against the **`UNLOAD` data manifest**, which names every object the engine wrote, and refuses to report success over an incomplete destination. It also surfaces the one thing a *successful* conversion can still get quietly wrong: a column that fell back to text because two files disagreed irreconcilably.

## Scope

### In Scope

- **`finalize`**: verify every object listed in the **`UNLOAD` data manifest** exists; emit the summary payload SPEC-121's notification is built from — including **string-fallback columns**.
- SFN success/failure terminal states (`RecordSuccess` / `RecordFailure`).

### Out of Scope

- **Excel (`.xlsx`) conversion — deferred entirely, user decision 2026-07-13.** There is no `convert-excel` verb, no deterministic-output-key machinery, and no Excel branch for `finalize` to verify.
- The `UNLOAD` path itself — SPEC-118.
- Compaction, repartitioning, or sorting of the output.
- Notifications — SPEC-121 (this spec emits the payload). UI — SPEC-120.

---

## Functional Requirements

### FR-001: `finalize` — completeness, verified against the `UNLOAD` manifest

#### Acceptance Criteria:

- [ ] `finalize` runs after the polling loop reports `SUCCEEDED`, before `DropTempTable` (SPEC-115 FR-001).
- [ ] **Completeness is verified against the `UNLOAD` data manifest — NOT by counting objects in the destination prefix, and NOT by predicting output names** (they are engine-chosen and opaque, SPEC-118 FR-003). `UNLOAD` writes a manifest listing **every object it created**; `finalize` reads it and asserts each listed object exists.
- [ ] **The manifest lives in the QUERY-RESULTS location, not the output location** — its path comes from `GetQueryExecution`'s **`Statistics.DataManifestLocation`** (which is why SPEC-118 threads it into the state, and why SPEC-116 grants read on the Athena results prefix). A comment records this explicitly: looking for the manifest under the *destination* finds nothing, and the obvious fix — "just check the destination isn't empty" — is the weaker check this criterion replaces.
- [ ] A comment records why the manifest is strictly better than an object count: **"non-empty" cannot distinguish a complete conversion from a half-written one.** A failed `UNLOAD` leaves partial output that the pipeline **cannot delete** (SPEC-118 FR-004), so a non-emptiness check would happily report success over exactly the wreckage the arc is trying not to hand the user.
- [ ] Any manifest-listed object that is missing is a terminal **`incomplete_result`** — the request does **not** report success.
- [ ] A test forces a missing output object after a "successful" query and asserts a terminal `incomplete_result`, not a success.

### FR-002: `finalize` — the summary payload, including string fallbacks

#### Acceptance Criteria:

- [ ] It emits a small summary payload for SPEC-121: `{ requestId, actor, source, destination, format, objectCount, stringFallbacks: [{ column, conflictingTypes }] }`. `objectCount` is the manifest's object count.
- [ ] **String fallbacks are carried through** from SPEC-117's target schema. A comment records why this is not optional: a conversion can **succeed** while quietly turning a column into text, the table built over it will be perfectly valid, and the **notification is the only moment the user can learn about it**.
- [ ] A clean conversion emits an empty `stringFallbacks` list — never a missing field.

### FR-003: Terminal states

#### Acceptance Criteria:

- [ ] `RecordSuccess` shapes `{ requestId, actor, source, destination, objectCount, stringFallbacks }`; `RecordFailure` shapes `{ requestId, actor, source, destination, status: "failed", reason }` — **the destination is carried on failure too**, because SPEC-121's failure notification must name the path where partial output may remain (SPEC-118 FR-004).
- [ ] Both are `Pass` states → `Succeed`/`Fail`, matching the existing machines (`table-builder/state-machine.asl.json.tftpl:190-202`). **Nothing durable is written to S3 by a terminal state** — the converted output is the artefact. A comment says so, so no future UI is built expecting a failure object in S3.
- [ ] Both paths still route through **`DropTempTable`** (SPEC-118 FR-004) — which must tolerate being reached before any table was created. A comment records that it **removes no S3 object on any path**: the pipeline holds no delete permission at all (SPEC-116 FR-006), so partial output is left for the user and the empty-destination rule is the retry interlock.

---

## Data Model

```
# Output names are engine-chosen and opaque (SPEC-118 FR-003)
output:      alice/sales_parquet/region=us/<athena-generated>.parquet

# …which is why finalize verifies against the UNLOAD DATA MANIFEST, listed at
# GetQueryExecution → Statistics.DataManifestLocation, in the QUERY-RESULTS location
# (NOT the output location). It names every object the engine wrote; "the destination
# is non-empty" cannot tell a complete conversion from a half-written one — and name
# prediction is impossible by design.
manifest:    s3://…/athenaresults/<queryExecutionId>-manifest.csv
```

```jsonc
// The summary payload finalize emits (consumed by SPEC-121)
{
  "requestId": "…",
  "actor": "alice",
  "source": "alice/sales/",
  "destination": "alice/sales_parquet/",
  "format": "csv",
  "objectCount": 12,
  "stringFallbacks": [
    { "column": "note", "conflictingTypes": ["DATE", "BIGINT"] }
  ]
}
```

## File & Folder Structure

```
lambdas/file-converter-finalize/finalize.py             (+ tests)
infra/modules/file-converter/state-machine.asl.json.tftpl   # Finalize, RecordSuccess/RecordFailure
```

## Implementation Phases

### Phase 1: `finalize`

- Completeness against the **`UNLOAD` data manifest** (read from `Statistics.DataManifestLocation`, in the query-results location); the summary payload with string fallbacks; the `incomplete_result` failure.
- Tests: **a manifest-listed object that is missing produces `incomplete_result`, not a success**; a manifest whose objects all exist produces success; a clean conversion emits an empty `stringFallbacks` list.

### Phase 2: Terminals + end-to-end

- The SFN terminal states, still routing through **`DropTempTable`** (Glue-only), with the **destination carried on the failure shape** so SPEC-121 can name the path.
- End-to-end: convert a CSV folder whose files disagree on a column type — assert the Parquet output is correctly typed and the summary names the string-fallback column. Completion ritual.
