# Completed Spec — SPEC-161: Table Share at Scale — Raised Caps, Wide Definitions & Long Runs

## What was completed?

SPEC-160 built the engine; this spec moved the ceilings that were written for the Lambda it
replaced. A table of several hundred part files well over 20 GiB, with a hundred commented columns,
now shares — where before it was refused twice over, both times for reasons that had stopped being
true. Nothing about the request contract, the push semantics or the notifications changed.

- **The caps.** `SHARE_MAX_OBJECTS` 1,000 → **20,000**, `SHARE_MAX_TOTAL_BYTES` 20 GiB → **1 TiB**,
  and a new **`SHARE_MAX_TRANSFER_ITEMS` (20,000)** on `recipients × objects`.
  `SHARE_MAX_RECIPIENTS` stays 50, pinned by a test rather than by absence. Each docstring names the
  limit that sized it.
- **The definition travels by pointer.** `inspect-source` writes
  `{admin_bucket}/table-share/{hash}/definition.json` and emits `definitionKey`; `create-table`
  fetches it. `tscommon.copy_plan` gained `definition_key` / `write_definition` / `load_definition`,
  keeping every admin-bucket key this plane writes in one module. **No IAM change** —
  `CopyPlanReadWrite` already covered `PutObject`/`GetObject` on `table-share/*`.
- **`SHARE_MAX_DEFINITION_BYTES` 32 KiB → 128 KiB**, re-expressed as an object-size sanity check.
  What sizes it now is Athena's query-string quota, **262,144 bytes and not adjustable** (verified
  against the live service-quotas page), because the definition renders into one
  `CREATE EXTERNAL TABLE`.
- **A top-level `TimeoutSeconds` of 10,800**, from a named local, so a wedged run terminates into
  `NotifyFailure` rather than running to Step Functions' one-year default.
- **The retired refusal wording is gone** from `lambdas/`, with a fleet-wide sweep holding it out.

## The `TimeoutSeconds` arithmetic

The bound is the byte cap, since the copy is the only stage whose duration scales.

| term | value | where from |
|---|---|---|
| in-flight server-side copies | **160** | `MAP_MAX_CONCURRENCY` (20) × `COPY_CONCURRENCY` (8) |
| 1 TiB at 20 MB/s per stream | **~6 min** | 3.2 GB/s aggregate |
| 1 TiB at a pessimistic 5 MB/s | **~22 min** | 800 MB/s aggregate |
| the guard and finish Maps | bounded | 50 recipients at `MaxConcurrency` 5, `create-table` 300 s |
| **`TimeoutSeconds`** | **10,800 s (3 h)** | ~8× the pessimistic worst case |

It is deliberately not longer. The timeout is how quickly a wedged share becomes a notification, so
the margin is bought against the sender's silence rather than being free.

**Retention clears it by 240×.** `admin_results_retention_days` is 30 (720 h) against a 3 h run
ceiling, so `expire-table-share-copy-plans` cannot expire a live run's manifest underneath it. A
test computes that ratio from both files.

## What FR-004 required was adding nothing

All three artifacts — manifest, `definition.json`, the `ResultWriter` export — sit under
`table-share/` **by construction**, because `tscommon.copy_plan` owns every key this plane writes.
So the existing rule covers them: no new rule, no new rule id, and the
`admin_lifecycle_rules_are_prefix_scoped` check untouched. Three tests now assert the absence — the
retention margin, that exactly one `table-share/` rule exists, and that the execution role's
`s3:DeleteObject` deny still covers the admin bucket (read from the **raw** template, because the
stubbed policy collapses every ARN placeholder to one literal and could not tell the admin bucket
from a space bucket).

## Deliberate deviations

- **The two manifest verbs were re-sized**, which the spec does not name: `build-transfer-manifest`
  and `collect-transfer-results` go 60 s/512 MB → **300 s/2048 MB**. They *are* the binding
  constraint on `SHARE_MAX_TRANSFER_ITEMS` — at S3's worst-case 1024-byte keys, 20,000 items is a
  ~46 MB manifest and an export carrying every batch's input back again. Memory is also the CPU
  dial, so it buys the timeout as much as the headroom. A test computes the worst-case volume from
  the cap and the same worst-case item the batch sizing uses, so raising the cap without re-sizing
  the verbs fails.
- **The item cap counts *requested* recipients, not guard-accepted ones.** Refusing on the upper
  bound is predictable from what the sender asked for; refusing on the accepted count would make an
  identical request succeed or fail depending on who already happened to hold a table of that name.
  It also fails before the guard, so an over-cap share costs no Glue reads and no listings.
- **A new reason code, `definition_unreadable`**, rather than reusing `create_failed`. FR-002 AC5
  wants a clear reason, and the failure is genuinely a different thing from a DDL that ran and
  failed.
- **`architecture.md` and `ARCS.md` were edited, which Phase 5 said not to do.** That instruction
  comes from FR-005's last criterion, and reading it in context it is scoped to the *refusal
  wording* — those docs were already corrected for the Batch Ops fence on 2026-08-10, so re-editing
  them **for that** would mean one had been missed. It does not cover FR-001, which supersedes a
  different fact. Left alone, `architecture.md` would still read *"The caps still stand"* and
  `ARCS.md` would still describe 161 in the future tense. Both got a short in-place superseded
  marker, per the standing completion ritual; neither mentions Batch Ops.

## Two things worth carrying

- **The payload-limit model now proves the pointer rather than assuming it.**
  `test_the_whole_map_state_stays_under_the_payload_limit` adds a worst-allowed definition back to
  the modelled state and measures the result: the guard peak goes from ~34% of the 256 KB limit to
  ~84%. Not a breach at 128 KiB — and that is the finding in both directions. Inline, the cap had to
  choose between the payload and the user, and the old 32 KiB value kept the state safe only by
  refusing a 100-column commented table.
- **The retired-phrase sweep caught one of this spec's own test docstrings**, which quoted the
  phrase while explaining its removal. Reworded rather than exempted. No existing test asserted the
  old wording — the suites assert `exc.reason` and the user sentence, neither of which ever carried
  it — so a grep is the only thing standing between a stale operator-facing detail and the next
  operator to read a failed run.

## Owed

- **The live check** — the runnable script is in `docs/testing/table-share-e2e.md` → *SPEC-161*:
  the >20 GiB several-hundred-object share, the deliberate over-cap refusal naming the count and the
  cap, and a `GetTable` read-back confirming a 100-column commented definition survived the pointer.
- **Nothing user-facing to document.** `helpContent.ts` names no cap numbers and no size limits, so
  the SPEC-074 sweep is a genuine no-op here, not a skip.
