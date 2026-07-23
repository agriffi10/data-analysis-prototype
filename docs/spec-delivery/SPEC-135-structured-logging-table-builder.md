# Completed Spec — SPEC-135: Instrument the Table-Builder Control Plane

## What was completed?

Five verbs join the pipe as `service="table-builder"`, registered with the SPEC-134 harness. No
behaviour change. Two PRs: infra, then code. **First spec to spend the harness rather than build
one.**

## FR-003 — the silent-create failure becomes a query

Three facts, logged, turn the plane's defining incident from a discovery into a `WHERE` clause:

| Fact | Verb |
|---|---|
| Which **database** the DDL targeted | validate-authorize |
| Whether the table existed beforehand, as an **explicit boolean** | check-table-absent |
| What **Athena actually said** | execute-ddl |

The pre-condition and the post-condition of a table build are the *same check*, which is what
makes "the DDL claimed success and the table is not there" a statable sentence rather than a
suspicion.

**`StateChangeReason` is logged verbatim, alongside the stable token rather than replaced by it.**
That raw text is exactly what would have named the missing `CREATE_TABLE` grant; paraphrasing it
into a token would have thrown away the diagnosis. It is service text about a *statement* —
schema, never a row.

## FR-004 — the poll narrates transitions, in `cpcommon`

`cpcommon.athena`'s loop runs **inside one invocation**, so an event per iteration multiplies
within a single span — the same amplification as data-quality's 30-second poll, in a smaller box.
Only transitions and the terminal state emit; an exhausted poll budget gets its **own error**,
because a `CREATE` slow enough to hit the cap is a real signal and is otherwise indistinguishable
from the Lambda being killed.

Instrumented in `cpcommon` rather than table-builder's thin wrapper, deliberately: the loop is
shared with data-quality's DDL paths, and putting it in the wrapper would mean instrumenting the
same loop twice with two chances to diverge.

## The harness found a modelling bug in itself

Matching verb modules by **filename prefix** swept in `table-builder-execute-ddl/athena_run.py` —
a helper beside the verb it serves — and then demanded that helper carry a traced handler.

A verb module is one that **defines a top-level `handler`**. That is the whole definition, so the
harness now matches on it directly; `module_prefix` is gone from every descriptor. The fix made
SPEC-136 and SPEC-137 *cheaper* to register, not harder.

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1381 passed / 2 skipped at merge.

**Eight mutations, all observed to fail — one survived the first round.** Making the Athena loop
narrate every poll changed nothing, because FR-004's test did not exist yet. It now drives 20
identical polls and asserts exactly **one** transition event.
