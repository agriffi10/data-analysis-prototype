# Completed Spec — SPEC-132: Narrate the Data-Quality Control Plane

## What was completed?

All nine verbs now say what they *found*, not only that they ran. **No change to what any verb
does** — validation, authorization, SQL, the manifest, the report, the notification and the state
machine are untouched. Shipped as two PRs (front half, then back half + guards).

| Verb | Narrative | Steps |
|---|---|---|
| validate-authorize | actor, space, **own vs shared**, normalized location, report prefix | `authorize`, `validate-destination` |
| inspect-source | prefix, objects, bytes, format, **column names**, partition-key names, capped, manifest key | `list-objects`, `resolve-format`, `probe-columns`, `detect-partitions`, `write-manifest` † |
| create-temp-tables | database, table, **raw table (null vs named)**, columns, format | `run-ddl` (≤2) |
| start-profile-query | queries started, **which optional ones were applicable** | `start-queries` |
| check-query | **transitions only** — settle, degrade, timeout | `describe-queries` (1/poll) |
| byte-scan | files, bytes, invalid count, **offsets**, coverage | `scan` (whole scan) |
| assemble-report | report key, verdict, `row_count`, findings | `find-result`, `read-results`, `write-report` |
| drop-temp-tables | tables dropped/failed **by name**, skipped | `drop-table` (≤2) |
| notify-failure | outcome, whether a link was minted, missing-`requestId` warning | none |

† **Renamed since (no spec — a papercut fix): the step is now `write-inspection-manifest`.** The old
name was also the whole verb `archive-write-manifest`'s root span, so a single `function` value
returned an invocation's total duration and this write's together. The step moved rather than the
verb because a verb's span name is also its directory suffix, its `locals.tf` key and its state
machine's wiring, while this step's name was read by nothing else. Full entry:
`docs/decisions/control-planes.md` → *Where a child span may go, and the four places it may not*.

Plus two coverage guards in `test_instrumentation_coverage.py`: every verb must narrate (AST, so a
docstring mention cannot satisfy it), and no emitter may pass a contents-shaped field name.

## The two amplification hazards

**`check-query` narrates transitions, never polls.** It runs from a 30-second `Wait` loop for as
long as the profiling query does, so one event per poll is fifty per run saying "still running" —
and the `span.start`/`span.end` pair already records that a poll happened. Only a settle emits;
`QUEUED → RUNNING` says nothing; a settled block is never described again. Pinned by a 20-poll test
asserting **zero** narrative events.

**`byte-scan` logs offsets and never the bytes at them.** The highest-risk emitter in the plane:
the verb's purpose is holding a user's raw bytes and the instinct is to log the sequence that
failed to decode. That sequence *is* the file. A test plants a recognisable payload behind invalid
UTF-8 and asserts the offsets land and the content does not.

Every step wraps a **whole loop** (`_probe_all`, `_scan_all`, `_describe_all`), never a per-file or
per-query function.

## The FR-003 `detail` audit — the deliverable, not the reassurance

Every `TerminalError` raise site across the nine verbs was read. **One** builds `detail` by
interpolating parsed file content:

- **`inspect-source` `_probe_columns`'s catch-all** — `f"could not read the schema of {key}: {exc}"`
  where `exc` is a polars parse error, and polars quotes the offending cell
  (`could not parse 'ACME, Inc' as dtype i64`).

That verb therefore logs **no `detail` at all**, for every terminal rather than a denylist of
reasons — a denylist is what the next reason gets added without. Every other site interpolates
locations, buckets, prefixes, counts, space kinds, column names or literals, and logs `detail`
normally. `check-query` logs Athena's `StateChangeReason`, which FR-004 explicitly permits.

Failures are narrated **once per verb** rather than at each raise site (`validate-authorize` alone
has eleven): a line added by hand beside a raise is one the twelfth raise is added without — the
argument SPEC-128 FR-001 already made for stamping `request_id` in the decorator.

## `error.stack` may carry file contents — ACCEPTED (user decision, 2026-07-23)

`log-foundry`'s `end_event` attaches `traceback.format_exception(...)` to **every failed span,
unconditionally**, and that walks the `__cause__` chain. So the same polars message reaches
`error.stack` on the span.end of both the step and the handler **regardless of what the emitter
does**. Suppressing `detail` does not help; nor would fixing the raise site, since `raise … from
exc` is what puts the cause's text there.

Surfaced by this spec (it predates it — every traced verb has done it since SPEC-128 — and it
spreads to the whole fleet with SPEC-134→137) and escalated. **The decision was to accept it, not
strip it:** `logs/` is admin-only, and a stack is diagnostic metadata an admin debugging a failed
run needs. So the absolute no-file-contents rule is understood to bind a **field a verb chooses to
emit** — the thing the `detail` audit and the denylist tripwire cover — and not an automatic
traceback. The rule text in `cpcommon/observability.py`'s docstring and in `decisions/` now says
so explicitly, so the exemption reads as a decision rather than a leak nobody noticed.

The characterisation test was **renamed and kept** (`test_ACCEPTED_the_span_error_stack_may_carry_
file_contents`), not deleted: it is now a tripwire that **fails if `log-foundry` starts stripping
stacks** — at which point the decision to accept them should be revisited in the open, rather than
the behaviour changing silently under a store retained forever.

## Three spec corrections

1. **FR-004's denylist bans the field name `rows`; the Data Model listed `rows: int`.** The guard
   caught this repo's own `assemble-report` field on its first real run. The denylist wins and the
   count is `row_count` — a tripwire is valuable because it is dumb and strict, and a field whose
   safety needs an argument is one whose name should say so instead.
2. **FR-002's table names `probe-columns` and `scan` as steps while the same FR forbids a step on a
   per-file function.** Extracting the loop satisfies both.
3. **The Data Model's `check-query` volume omitted FR-002's own `describe-queries` step** — 4
   boundary events per poll, not 2, and ~250 events per run rather than ~150. The step stays one
   per invocation rather than one per query for exactly that reason.

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1256 passed / 2 skipped. Each verb's happy path is
asserted through a capturing sink (`conftest.py`'s shared `captured_events`), not merely that it
returned.

**Twelve mutations, all observed to fail — and the first round found a real hole.** One survived:
reporting a tolerated drop failure as ERROR rather than WARNING. `drop-temp-tables` had been
instrumented with no test pinning the level that decides whether a *successful* run reads as
failed. Test added, mutation re-run, killed. The rest: `check-query` narrating every poll,
re-emitting a settled query, a degradation at ERROR, a quota kill collapsed into a generic failure,
a describe span per query; `byte-scan` logging the bad bytes; a per-file step in `byte-scan` and
`inspect-source`; `inspect-source` logging `detail`; `assemble-report` logging a result row;
`notify-failure` inventing a `request_id`.

**Phase 4 (live) is NOT done** — a real check started from the UI, confirming one run's nine traces
carry the narrative, join on `request_id`, and that a successful run contains no `error` events.
Deferred to the user by agreement. That same run is what SPEC-128 FR-002 and SPEC-129's append
still owe at real volume.
