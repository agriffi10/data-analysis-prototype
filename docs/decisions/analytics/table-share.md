---
type: Decision
title: "Table Share (SPEC-088→094)"
description: "Table Share copies a table's files into each recipient's `shared_tables/{table}/` and clones its Glue definition there, pushed without consent; do not re-infer the schema, overwrite a recipient's table, or propose S3 Batch Operations."
---

**COMPLETE:** "share a table across databases" — from the Query schema rail, copy a table's data files into recipient spaces under `shared_tables/{table}/` and create a clone table in each recipient DB (personal users and/or shared spaces). Its own **dedicated** async control plane (FIFO SQS+DLQ → Pipe → Standard SFN with a recipient `Map`, single-task Lambdas + `tscommon` (a **layer** until SPEC-213; now in the fleet image), **one shared execution role** — creates tables via the `portal-managed` LF-Tag, not LF-admin status; SPEC-070/111 correction). SFN: validate-authorize (actor must have **source** access — personal=own DB, shared=active member) → inspect-source (**clone the source Glue table definition**, not re-infer; reject views/catalog-partitioned/non-external; cap object count+size) → Map(recipient): check-target-absent (fail-that-recipient on conflict, no overwrite) → copy-objects (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → create-table (repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Push** (no consent; recipient notified); **any shared space is a valid target** (sender needn't be a member — source access still gated); v1 sources = flat or projection-partitioned base external tables. UI = schema-rail per-table **"Share table"** (`features/table-share/` dialog + `useTableShare`, SPEC-093); **outcomes = SPEC-058 notifications** (sender per-recipient success/failure + whole-request failure; on success the recipient user / space **owner** is also told — `tscommon.notify`/`messages`, best-effort, `sqs:SendMessage` on the notifications queue only, SPEC-094). ~~New browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`.~~ **— superseded by SPEC-200:** the browser holds no grant; a share is a `POST /v1/enqueue/table-share` to the API, whose execution role writes the queue. Decision record: `lambdas/info/planes/table-share.md`. Do NOT build a consent/accept flow, schema re-inference, or catalog-partition-metadata copy in v1.

> **Amended (SPEC-160, 2026-08-10) — S3 Batch Operations is REJECTED, not deferred.** The original fence read "do NOT build … S3 Batch Ops … in v1", which recorded it as the scale path to reach for later. It is not one. Its Copy operation **cannot rewrite a key**: `TargetKeyPrefix` prepends to the *full* source key, so a job can only ever produce `bob/shared_tables/sales/alice/tables/sales/year=2024/part-0.parquet` — the sender's own prefix layout echoed inside the recipient's space, with the clone's `LOCATION` pointed at a path naming the sender's directory structure. It also caps objects at **5 GB**, where `tscommon.copy` already handles more via `UploadPartCopy`, and one job writes to exactly one destination bucket while recipients span two. The scale path is a **top-level Step Functions Distributed Map** over a flat `(recipient × object)` JSONL manifest in the admin bucket, running the existing copy code unchanged (SPEC-160), with the engine on `cpcommon.transfer` because the send-files plane (SPEC-164→167) is its second caller. **Do not re-propose Batch Ops** — the refusal is a property of the API, not of the current implementation.

## History

### 2026-08-10

- **Changed:** S3 Batch Operations moved from deferred to rejected; the scale path is a Step Functions Distributed Map over a flat manifest.

### 2026-07-04

- **Settled:** SPEC-088→094.
