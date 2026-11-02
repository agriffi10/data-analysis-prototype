---
type: Decision
title: "Everything unbounded on the state travels by pointer — including the definition (SPEC-161, extending SPEC-090/160)"
description: "**Everything unbounded travels by pointer**, never on the state, and **a cap is not a substitute**. The exception is a value the system did not choose to put there: `$$.Execution.Input` is bounded by Step Functions admitting the execution and there is no pointer to it, because nothing wrote it anywhere a verb could fetch it. **Every plane's `RecordFailure` now carries that envelope**, which is what lets a failure that replaced the state name its own run — so the exception is load-bearing on eight states rather than theoretical. What stops it generalising is the cap SPEC-229 supplies: **every caller-controlled field on an enqueue request declares a bound**, and the four-link chain is measured against the 256 KiB state limit for every route rather than argued about. **Table share CLONES the source definition, never re-infers it**, and pushes without consent."
---

The rule the table-share plane arrived at over three specs, stated once: **anything on the Step Functions state whose size a user controls lives in the admin bucket and rides as a key.** The object list went first (PR #256, at 95% of the 256 KB payload), the transfer manifest was born that way (SPEC-160), and SPEC-161 finishes it with the **cloned table definition** — `{admin_bucket}/table-share/{hash}/definition.json`, written by `inspect-source`, fetched by `create-table`. `tscommon.copy_plan` owns all three key layouts, so the request digest has one home.

**A cap is not an alternative to a pointer, and this is the case that shows why.** The definition was bounded inline by `SHARE_MAX_DEFINITION_BYTES` at 32 KiB, and that number was doing two incompatible jobs: keeping the Map's state safe, and deciding how wide a table a user may share. A 100-column table with column comments serialises to roughly 32 KiB — an ordinary thing to want to share, sitting exactly on the boundary. Measured: with the definition inline at cap, the guard Map's peak state reaches **~55%** of the limit; with the pointer it is ~29%. The cap could protect the payload or serve the user, not both. **`test_the_whole_map_state_stays_under_the_payload_limit` now adds an at-cap definition back to the modelled state and asserts it fails the safety bar**, so the pointer is demonstrated to be load-bearing rather than assumed to be tidy.

`SHARE_MAX_DEFINITION_BYTES` survives at **64 KiB** as an object-size sanity check, and **what sizes it is now Athena, not Step Functions**: the definition renders into one `CREATE EXTERNAL TABLE`, and Athena's query-string quota is **262,144 bytes and not adjustable**. The rendered statement can be **twice** the serialised JSON — `ddl.literal` backslash-escapes, so a `'` costs one byte in the JSON and two in the DDL — and *where* those quotes sit decides the ratio: a table property or SerDe parameter carries ~9 bytes of JSON overhead and renders at nearly the full 2x, where a column comment carries ~40 and reaches only ~1.7x. At 128 KiB the property-shaped worst case measured **99.98%** of the quota; at 64 KiB it is 50%. Do not re-read it as a state bound, and do not raise it on the strength of a comment-shaped measurement.

**Three keys, two disciplines, and the split is about what the content depends on.** The plan and the definition are **pure functions of the request** — the digest covers the source database and table, so two overlapping executions write byte-identical content and either object is correct for either run **— superseded in part 2026-09-15: only while the source is unchanged between the two runs' reads of it ([the group id entry](a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on.md)) —**. The manifest is **execution-unique**, because its lines depend on which recipients the guard Map accepted, which is time- and destination-dependent (SPEC-160's entry has the full argument). Do not "make them consistent" by giving the definition an execution segment; it would multiply objects under a lifecycle rule for no gain.

**An unreadable definition fails THAT RECIPIENT, never the request, and never renders anyway.** `definition_unreadable` is terminal for the finish Map's item, and the reason the load refuses an object with no columns rather than passing it on is specific: an empty column list renders a `CREATE EXTERNAL TABLE` that **Athena accepts**, over the recipient's freshly-copied data — a table that reports success and returns nothing.

**No IAM changed.** `CopyPlanReadWrite` already grants `PutObject`/`GetObject` on `${admin_bucket_arn}/table-share/*`, which is the whole benefit of one prefix owning every artifact — and the same property is why FR-004 was discharged by adding **no lifecycle rule**. Detail: `spec-delivery/SPEC-161`.

**The exception to the pointer rule is a value the system did not choose to put there.** `$$.Execution.Input` is bounded by Step Functions admitting the execution and there is no pointer to it, because nothing wrote it anywhere a verb could fetch it.

Table share clones the source definition, never re-infers it, and pushes without consent.

## History

### 2026-09-15

- **Changed:** The plan and definition being correct for either overlapping run now holds only while the source is unchanged between the two runs' reads of it.

### 2026-08-10

- **Settled:** SPEC-161, extending SPEC-090/160.
