# Completed Spec — SPEC-129: Logs Queue → FIFO, One Object Per Service-Day

## What shipped

- **Sweep cadence 5 → 10 minutes.**
- **`logs/service={service}/year=YYYY/month=MM/day=DD/data.jsonl`** — one object per service-day,
  each sweep **appending** to it. **Renamed 2026-09-27**: the basename is now
  `{service}_logs_YYYY_MM_DD.jsonl`, and partitions written before keep `data.jsonl`
  (`docs/decisions/control-planes.md`).
- **FIFO logs queue** (`dat-prod-logs.fifo`) with `message_group_id` = the **service** — **reversed
  2026-09-11**: a group per service was the sweep's ceiling, and the queue is now grouped per event
  (`docs/decisions/control-planes.md`, *The logs queue is grouped per event*).
- `log-foundry` 0.4.0 → **0.5.0** (log-forge SPEC-016 added FIFO support to `SQSSink`).

## What changed from SPEC-127/128

These are the reversals, recorded here because a later reader will find the earlier reasoning
first:

| SPEC-127 said | Now |
|---|---|
| FR-004: 5 minutes, because "a log you cannot see for ten minutes is not usable" | 10 minutes — each sweep is now a read-modify-write of a growing object, so cadence buys more than freshness costs |
| FR-002: the queue is **standard**, because `SQSSink` sends no `MessageGroupId` | FIFO — 0.5.0 removed the constraint |
| FR-005: one object per `(service, dt, hh)`, unique key per sweep | One object per `(service, year, month, day)`, appended |
| FR-006: the sweep role "writes logs; **it reads nothing**" | `s3:GetObject` on `logs/*` — appending requires reading. Scoped to the same prefix as the write |

`month=` is in the key deliberately. `year=YYYY/day=DD` as first sketched puts every 15th of the
month in one partition, silently interleaving twelve calendar dates in one appended file — raised
before building, resolved by user decision (2026-07-23).

## The risk the append introduces, and what holds it

S3 has no append, so this is read-modify-write — a way to lose data the old unique-key design did
not have. Two overlapping sweeps would both read the same object and the second `PUT` would erase
the first's events, with no error anywhere.

- Every write is conditional: `If-None-Match: *` to create, `If-Match: <etag>` to extend.
- A precondition failure **re-reads and re-applies**, bounded by `MAX_CAS_ATTEMPTS`. Same shape as
  `dqcommon.index_store` (SPEC-123).
- Exhausting the cap leaves the messages **queued**, never deleted.
- A failed **read** is treated as "absent, no etag", so the write conflicts rather than silently
  replacing a day of logs.
- Memory 256 → 512 MB; `LARGE_OBJECT_WARN_BYTES` warns when a day's object gets big enough for
  the rewrite cost to matter.

**No `content_based_deduplication`** on the queue, and that is load-bearing: `log-foundry` mints a
UUID `MessageDeduplicationId` per event, so messages are already unique — enabling content-based
dedup would make SQS silently drop a *genuine* duplicate event inside its 5-minute window.

## Verification

Local: `pytest lambdas/` 1137 passed, `ruff` clean, `tofu validate`/`fmt` clean. The test fake
implements **real** conditional-put semantics with a changing ETag — one that ignored preconditions
would make the CAS loop green either way. Mutations: append→overwrite fails 2 tests; removing both
conditional-put guards fails the read-failure-overwrites test.

**Live (2026-07-23):**

| Check | Result |
|---|---|
| Schedule | `rate(10 minutes)` |
| Sweep config | 512 MB, `LOGS_QUEUE_URL` = `…/dat-prod-logs.fifo` |
| Queue | `FifoQueue=true`, `ContentBasedDeduplication=false`, visibility 360s |
| Cold start after the env + layer change | clean, no `FunctionError` |
| Layout | `logs/service=observability/year=2026/month=07/day=23/data.jsonl` |
| **Append** | 2 → 4 events across two sweeps, **4 distinct `log_id`s**, earlier pair intact |
| **Group ids** | `group=observability` and `group=data-quality`, each with a distinct dedup id |

## One deploy trap this surfaced

The `Deploy Lambdas` run failed on this merge with
`ResourceConflictException: An update is in progress for resource: …data-quality-byte-scan`.

`Deploy Infrastructure` and `Deploy Lambdas` run **in parallel** on the same push. This change
rewrote all nine data-quality functions' env vars (the new queue URL) while Deploy Lambdas was
calling `UpdateFunctionConfiguration` to attach layers. A re-run of the failed job succeeded once
the apply had finished — nothing was wrong with the code.

It will recur on any spec that changes Lambda **env** (infra) and Lambda **code** in one push.
Recorded in `architecture.md` → Known Constraints.
