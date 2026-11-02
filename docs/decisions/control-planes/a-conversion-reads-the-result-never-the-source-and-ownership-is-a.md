---
type: Decision
title: "A conversion reads the RESULT, never the source, and ownership is a question about a path (SPEC-221)"
description: "**A conversion's input is the EXECUTION'S RESULT OBJECT, never the source table, and it may keep a SUBSET of that object's columns**, named by position and refused at four depths — the API bounds the list's length, validate-authorize its shape, describe-results each position against the result, and the converter re-checks before it indexes, because a negative position writes the LAST column and reports success. An execution is the actor's **iff Athena wrote it under `cpcommon.results.user_results_prefix`** — the one builder the API starts every query with, so a guessed id names nothing the actor cannot already read. A plane refusing protected destinations mirrors its role's **any-depth** Deny rather than the browser's root-anchored picker: an IAM wildcard matches `/`, so a validator anchored at the root accepts a key IAM then refuses at the write."
---

Saving a query's results as Parquet, JSON or Excel means producing a new file from a result set of
unbounded size, which needs polars and must never run inside a request. **A CSV joined them once a
request could ask for a SUBSET of the result's columns** (SPEC-239): the CSV Athena wrote is still
copied whenever the file wanted is that object, and only a file the copy cannot produce — some of
the columns, or the same columns in another order — is built here. Three ways were put to the
user; **he chose a control plane** over building the file in the browser (two dependencies and a
row ceiling the tab's memory sets) and over re-running the query as an Athena `UNLOAD` (a second
bill, several files under names Athena chooses, and no Excel at all).

**The input is the execution's result object.** The tables a query reads are mostly Parquet, some
CSV, some JSON, and it changes nothing: Athena writes every result set as one CSV object under the
actor's own results prefix, so the converter reads one shape whatever was queried, no second query
starts and nothing is billed. **No intermediate file is made** — that CSV exists whether or not
this plane runs, because it *is* the query's result. The path that avoids it is `UNLOAD`, and it
is the one that writes several files.

**A lazy frame over the SOURCE files was considered and rejected** (2026-09-05, user decision) on
four grounds this repo had already measured — no source files behind a view or a saved query,
polars' lazy S3 scan downloading whole objects in Lambda, fidelity lost to re-implementing Trino's
own comparison semantics, and the plane becoming a second authority on table access. The reasoning
is written once, in [`ARCS.md`](../../specs/ARCS.md#results-conversion-arc-spec-221--222--223), with
what the result path costs and what the honest remedy would be if it ever mattered.

**Ownership is a question about a path, and that is what makes a guessed execution id harmless.**
An execution is the actor's iff its recorded `OutputLocation` begins with the prefix the API starts
every one of that user's queries with — so `cpcommon.results.user_results_prefix` is one builder
called by both, and a test holds the API's `output_location` byte-identical to it. It is a
**different fact** from `results_location`, which is where a plane's own DDL writes, and the two
are deliberately not merged. An id Athena does not know and an execution written anywhere else
refuse with the **same** code and the same sentence, so the refusal cannot answer "does this
execution exist?" for a caller trying ids. Two things the reviews added: the derived key is refused
if it carries a dot segment, because `startswith` passes a location that then escapes the prefix;
and a non-string space kind is refused rather than raising `TypeError` out of the membership test.

**The write grant is not here.** ~~This plane ships read-only — no `s3:PutObject` Allow
anywhere~~ — **superseded by SPEC-222**, which added `s3:PutObject` and
`s3:AbortMultipartUpload` on the two space buckets beside the verb that writes, exactly as this
paragraph anticipated. What stands is the ORDER, and it is the part worth keeping: the plane
carried the explicit **Deny** on every protected folder in both space buckets from its
first apply — the three `cpcommon.app_managed` declares plus this plane's own non-moving four. Measured against the deployed role: `explicitDeny` for a write under `athenaresults/`,
`archive/`, `shared_tables/` and `user_settings/`, `implicitDeny` for an ordinary path. So the Deny
is discriminating before there is anything for it to override, which is the order that makes a
validator defect unable to write into a receipt folder the day the Allow arrives.

A plane refusing protected destinations mirrors its role's any-depth Deny rather than the browser's root-anchored picker: an IAM wildcard matches `/`, so a validator anchored at the root accepts a key IAM then refuses at the write.

## History

### 2026-09-05

- **Settled:** SPEC-221.
