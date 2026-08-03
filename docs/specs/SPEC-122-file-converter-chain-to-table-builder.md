# Spec: File Converter — "Create table from the converted files" (chain to Table Builder)

**ID:** SPEC-122
**Status:** Cancelled
**Last Updated:** 2026-07-13
**Depends On:** SPEC-115→121 (the file-converter arc must work end to end first), SPEC-066→072 (Table Builder — this spec extends its request contract), SPEC-058 (notifications)

> **Read `docs/file-converter-architecture.md` §8.1 first.** This is an **optional, additive** capability on top of a working converter. It is deliberately the **last** spec in the arc: nothing else depends on it, and it can be dropped without touching anything already built.

## Overview

Today the workflow ends with a notification saying "your Parquet is at `alice/sales_parquet/`", and the user must then go to the Files browser and run Table Builder against that folder by hand. This spec closes the loop: a **"Create a table from the converted files"** checkbox in the convert dialog. Tick it, name the table, and when the conversion succeeds the pipeline **enqueues a Table Builder request on the user's behalf**.

**Table building stays in Table Builder.** The converter does not create tables, does not generate DDL, and does not touch the catalog for this purpose. It enqueues a message on Table Builder's queue and gets out of the way — so there is exactly one implementation of "create a table from a folder," and it is the one that already ships.

### The security problem this spec has to solve, and how

Table Builder's `validate-authorize` derives the username from a Cognito **ID token** in the message body and **never** trusts a body-supplied actor (`lambdas/table-builder-validate-authorize/validate_authorize.py`). A Lambda cannot mint a user's token. So a chained enqueue needs the converter to assert an identity — which means Table Builder must, for this one path, trust an asserted actor.

**That trust must be unreachable from the browser.** If a user could hand-craft a trusted-shaped message, they could make Table Builder create a table in **another user's database over another user's data** — privilege escalation, not an annoyance.

**The existing notifications pipeline is NOT a safe model to copy, and it is worth saying why.** `lambdas/notifications-writer/notifications_writer.py::_resolve_username` takes `username` straight from the body for `create` actions with no verification, and the **portal role holds `sqs:SendMessage` on that same queue** (`infra/modules/notifications/policies/portal-role-notifications.json.tftpl`). A browser can therefore write a notification into any other user's inbox today. That is a real, shipped hole (low severity — message injection), and it is tracked separately. **Do not reproduce it here**, where the blast radius is far larger.

So the trust boundary is **infrastructural, not textual**:

- Table Builder gains a **second, internal FIFO queue** that **only the file-converter execution role** can write to. The portal role has **no grant on it**, so the browser physically cannot reach it.
- A **second EventBridge Pipe** reads that queue into the **same** Table Builder Step Function, and its **input transformer stamps the trust marker**. The marker is set by infrastructure, not by the sender, so a body cannot smuggle it.
- The **public** Pipe's transformer explicitly sets the marker to `null`, so a body-supplied marker on the public queue is overwritten and can never be honoured.

## Scope

### In Scope

- **Table Builder**: an internal FIFO request queue + DLQ; a second Pipe into the existing state machine; a **trusted-producer path** in `validate-authorize`, reachable only via that Pipe.
- **File converter**: an optional `tableBuild` block on the request envelope; a new `enqueue-table-build` verb behind a `Choice`, on the **success path only**; `sqs:SendMessage` on the internal queue ARN only.
- **UI**: the checkbox, a table-name field, and — for a partitioned source — Table Builder's **existing partition-keys editor**, reused not rebuilt.
- Validation: the table name; and that declared partition keys **match the layout `inspect-source` actually detected**.
- Notification wording: the converter's success message says a table build was queued and names the table.

### Out of Scope

- **Fixing the notifications spoofing hole.** Named above because it is the reason this spec is shaped the way it is, but it is a separate, shipped bug in a different pipeline and gets its own spec.
- Any change to how Table Builder generates DDL, infers schema, or projects partitions. This spec **enqueues**; it does not reimplement.
- Chaining from data quality, or chaining conversion from a quality check. One chain, one direction.
- A combined notification. The converter notifies that the build was queued; Table Builder notifies the outcome. **Two notifications is the honest result** and requires no change to either producer.
- Retrying a failed table build automatically. The converted files exist; the user re-runs Table Builder from the Files browser.

---

## Functional Requirements

### FR-001: Table Builder's internal queue and its Pipe

#### Description

The trust boundary. Everything else in this spec rests on the browser being **unable to send** to this queue.

#### Acceptance Criteria:

- [ ] A **FIFO internal request queue + FIFO DLQ** exist in `infra/modules/table-builder/`, distinct from the existing public request queue.
- [ ] `sqs:SendMessage` on it is granted to the **file-converter execution role only**. The **portal role has no grant on it**, and a plan assertion confirms the portal role's rendered policy contains no reference to the internal queue ARN.
- [ ] A **second EventBridge Pipe** reads the internal queue and starts the **same** Table Builder Step Function (`batch_size = 1`, fire-and-forget), mirroring the existing Pipe.
- [ ] **Both Pipes emit the same input-transformer event shape:** `{ "trustedProducer": null | "file-converter", "body": "<original SQS body string>" }` — the internal Pipe stamps `"file-converter"`, the **existing public Pipe explicitly stamps `null`**. A comment records why the public Pipe cannot simply pass the body through: without an explicit `null`, a browser could put `trustedProducer` in the message body and have it honoured. The marker must be **infrastructure-stamped, never body-supplied**.
- [ ] **`validate-authorize` reads the marker EXCLUSIVELY from the top-level transformer output.** A `trustedProducer` key inside the JSON `body` is **ignored on both paths** — a test asserts it for each Pipe.
- [ ] A test enqueues a message on the **public** queue whose body contains `"trustedProducer": "file-converter"` and asserts the state machine sees `null` at the top level — the smuggling attempt fails.
- [ ] **The cross-module wiring flows through root `main.tf` locals/variables** — table-builder grants `sqs:SendMessage` to the converter's role; the converter needs the internal queue URL — **never** a direct module-output↔module-input pair in both directions (a module cycle). Same discipline as the LF-admins constructed string (SPEC-118 FR-005).

### FR-002: Table Builder's trusted-producer path

#### Acceptance Criteria:

- [ ] `validate-authorize` accepts an actor from the body **only** when `trustedProducer` is present (and therefore Pipe-stamped). Otherwise it requires and verifies an ID token exactly as it does today — **the existing browser path is unchanged**.
- [ ] A message carrying **both** `trustedProducer` and `idToken` is a terminal `unauthorized`. A comment records why: an ambiguous envelope is the shape an attacker would construct, and rejecting it costs nothing.
- [ ] A trusted message with a missing or non-string `actor` is a terminal `unauthorized`.
- [ ] **The trusted path does not skip authorization.** The asserted actor is still checked against the space exactly as a token-derived actor is: personal ⇒ the database must equal the actor and the prefix must be inside their own space; shared ⇒ the registry record must be `active` and the actor must be in `members`. A trusted producer asserts *identity*, never *entitlement*. A test asserts a trusted message naming a space the actor does not belong to is rejected.
- [ ] The browser path is **behaviourally unchanged**: same terminals, same validated output for every existing fixture. The existing table-builder test suite is updated **only** for the new event envelope (the Pipe transformer now wraps the body — FR-001), nothing else.

### FR-003: The converter's request envelope and its validation

#### Acceptance Criteria:

- [ ] The SPEC-116 envelope gains an optional `tableBuild: { tableName, partitionKeys } | null`. Absent or null means the conversion behaves exactly as it does today.
- [ ] `validate-authorize` validates `tableName` against Table Builder's existing catalog-identifier rules and rejects an invalid one with a terminal **`invalid_table_name`** naming the rule — *before* a 30-minute conversion runs, not after.
- [ ] The regex is **duplicated into `fccommon.config`**, with a **pointer test asserting it equals Table Builder's `CATALOG_IDENTIFIER_RE`** (`tbcommon/config.py:40`) so the two cannot drift. It is deliberately **not** moved into `cpcommon` — SPEC-107 is a pure move, and this spec must not smuggle a new shared symbol into it.
- [ ] `inspect-source` compares the partition keys **it detected** against those **declared** in `tableBuild.partitionKeys`. A mismatch (declared keys the source does not have, or a partitioned source with no declared keys) is a terminal **`partition_keys_mismatch`** naming the difference.
- [ ] A comment records why the check lives in `inspect-source` and not `validate-authorize`: the source's real partition layout is not known until the listing happens.

### FR-004: `enqueue-table-build` — success path only, and enqueued exactly once

#### Acceptance Criteria:

- [ ] A new single-task Lambda `enqueue-table-build` runs **after `finalize`**, behind a `Choice` on `tableBuild != null`. When the flag is absent the state is skipped entirely.
- [ ] The function follows the arc's Lambda conventions: **explicit sizing (30 s / 256 MB)**, a **14-day log group**, the **`cpcommon` + `fccommon`** layers, and its zip wired into `deploy-lambdas.yml`.
- [ ] It is on the **success path only**. A failed or incomplete conversion **never** enqueues a table build. A test forces a mid-`UNLOAD` failure and asserts no message reaches the internal queue.
- [ ] The message is `{ requestId, actor, space: { kind, bucket, prefix, database }, tableName, partitionKeys }` — where `prefix` is the **conversion destination** (the folder Table Builder will build over) and `actor` is the username the converter derived from the **verified** token at the start of the request.
- [ ] **The chained request's `requestId` is a deterministic derivative of the converter's — UUIDv5 of the converter's `requestId`.** A comment records both things this buys: (a) Table Builder's notification dedup ids (`{requestId}:{step}`) **cannot collide with the converter's own** within the FIFO dedup window, because the two pipelines never share a requestId; (b) the id is stable across retries, which is what the dedup criterion below rests on. A test asserts the derivation is stable and differs from the converter's `requestId`.
- [ ] It carries **no ID token**. A comment records why: forwarding a bearer token would leave it in Step Functions execution history for the length of a conversion, and a long conversion can outlive it.
- [ ] `MessageGroupId` = `space.database`, matching Table Builder's existing scheme (`tableBuild.service.ts:50`).
- [ ] `MessageDeduplicationId` is a **deterministic function of the converter's `requestId`** (the UUIDv5 derivative above), so a Step Functions `Retry` of this verb cannot enqueue a second build. A test retries the verb and asserts exactly one message lands.
- [ ] The converter's execution role gains `sqs:SendMessage` on the **internal queue ARN only** — no other queue, no other action. It gains **no** new Glue, S3, or Athena permission.
- [ ] A failure to enqueue is **not** best-effort: unlike a notification, a silently-dropped table build would leave the user waiting for something that will never arrive. It is a terminal `table_build_enqueue_failed`, and the notification says the conversion succeeded but the table build did not start.

### FR-005: The UI — checkbox, table name, and the reused partition editor

#### Acceptance Criteria:

- [ ] The convert dialog (SPEC-120) gains a **"Create a table from the converted files"** checkbox, unchecked by default.
- [ ] Ticking it reveals a **table-name** field, validated client-side against the same rules the server enforces (FR-003), with an inline error and a disabled confirm button on failure.
- [ ] When the selected source has Hive-style `key=value/` folders, ticking the checkbox also reveals **Table Builder's existing partition-keys editor** (`features/table-builder/`, SPEC-071) to collect a type and range per key. **The component is reused, not reimplemented.** A comment records that a second partition editor would drift from the first.
- [ ] The dialog explains, in one line, that the table is created **after** the conversion finishes and that the user will be notified twice — once when the files are ready, once when the table is.
- [ ] Everything is reachable and usable at the mobile breakpoint (SPEC-095), `vitest-axe` reports no violations in the checked and unchecked states (SPEC-045), and every error is rendered through `toUserMessage` (SPEC-106).

### FR-006: Notifications

#### Acceptance Criteria:

- [ ] The converter's **success** notification (SPEC-121 FR-001) additionally states that a table build has been **queued** and names the table — so the user knows to expect a second message.
- [ ] Table Builder's existing notifications (SPEC-072) report the build's outcome unchanged. **No change to Table Builder's notification code.**
- [ ] `invalid_table_name`, `partition_keys_mismatch` and `table_build_enqueue_failed` are registered through the `cpcommon.messages` domain hook (SPEC-107 FR-005) and appear in SPEC-121's exhaustive reason set. An unregistered code is a hard error at import.
- [ ] `table_build_enqueue_failed` makes clear that **the files converted successfully** and only the table build failed to start — the user's data is fine, and they can build the table by hand.

---

## Data Model

```ts
// apps/portal/src/features/file-converter/fileConverter.types.ts  (extended)

export type ConverterTableBuild = {
  tableName: string;
  /** Empty for an unpartitioned source. Shape reused from the table-builder feature. */
  partitionKeys: PartitionKeyDeclaration[];
};

export type FileConversionRequest = {
  requestId: string;
  space: ConverterSpace;
  source: string;
  destination: string;
  tableBuild?: ConverterTableBuild | null;   // NEW — null/absent = convert only
};
```

```jsonc
// The message enqueue-table-build sends to Table Builder's INTERNAL queue.
// Note: no idToken. The Pipe stamps `trustedProducer`; the body cannot.
{
  "requestId": "…",                       // UUIDv5 of the CONVERTER's requestId (FR-004) — never the same id,
                                          // so {requestId}:{step} notification dedup can't collide across pipelines
  "actor": "alice",                       // derived from a VERIFIED token by the converter
  "space": { "kind": "personal", "bucket": "…", "prefix": "alice/sales_parquet/", "database": "alice" },
  "tableName": "sales",
  "partitionKeys": [{ "name": "region", "type": "string", "values": ["us", "eu"] }]
}
```

```jsonc
// What BOTH Table Builder Pipes hand the state machine (FR-001). The marker is
// top-level and infrastructure-stamped; validate-authorize reads it ONLY from here —
// a "trustedProducer" inside `body` is ignored on both paths.
{ "trustedProducer": null /* public */ | "file-converter" /* internal */,
  "body": "<original SQS body string>" }
```

## File & Folder Structure

```
infra/modules/table-builder/
├── sqs.tf                       # + internal FIFO queue + DLQ
├── pipe.tf                      # + second Pipe (internal → same SFN); trustedProducer stamped here
│                                #   and explicitly NULLED on the public Pipe
└── policies/                    # + sqs:SendMessage for the file-converter role on the internal queue only
lambdas/table-builder-validate-authorize/validate_authorize.py   # + the trusted path (FR-002)
lambdas/file-converter-enqueue-table-build/enqueue_table_build.py   (+ tests)
infra/modules/file-converter/
├── state-machine.asl.json.tftpl # + Choice(tableBuild) → EnqueueTableBuild, after Finalize
├── lambda.tf                    # + the verb (30 s / 256 MB, cpcommon+fccommon, 14-day logs)
│                                #   + TABLE_BUILD_INTERNAL_QUEUE_URL
└── policies/execution.json.tftpl # + sqs:SendMessage on the internal queue ARN only
infra/main.tf                     # the cross-module wiring: queue URL/ARN + role ARN pass through
                                  # root locals/variables, never module-output↔module-input both ways
.github/workflows/deploy-lambdas.yml                              # + the enqueue-table-build zip
apps/portal/src/features/file-converter/ConvertToParquetDialog.tsx   # + checkbox, name, reused partition editor
```

## Implementation Phases

### Phase 1: The trust boundary (Table Builder side)

- The internal queue + DLQ; the second Pipe with its `trustedProducer` stamp; the public Pipe's explicit `null`; the trusted path in `validate-authorize`.
- **Tests first on the attacks:** a body-supplied `trustedProducer` is ignored on **both** Pipes (the marker is read only from the top-level transformer output); an envelope with both markers is rejected; a trusted message naming a space the actor doesn't belong to is rejected; the browser path is **behaviourally unchanged** (same terminals, same validated output for every existing fixture — the suite is updated only for the new event envelope).

### Phase 2: The converter side

- The envelope extension; `invalid_table_name` in `validate-authorize` (regex duplicated into `fccommon.config` + the pointer test against `CATALOG_IDENTIFIER_RE`); `partition_keys_mismatch` in `inspect-source`; the `enqueue-table-build` verb (30 s / 256 MB, cpcommon+fccommon) behind its `Choice`, on the success path only, with the **UUIDv5-derived `requestId`** and deterministic dedup; the `sqs:SendMessage` grant through root locals.
- Test that a failed conversion enqueues nothing, and that a retried verb enqueues exactly once.

### Phase 3: UI, notifications, completion ritual

- The checkbox, the table-name field, the **reused** partition-keys editor; responsive + a11y.
- The converter's success message names the queued table; the three new reason codes registered.
- End-to-end: convert a partitioned CSV folder with the box ticked, and assert the Parquet lands, a table build is enqueued exactly once, Table Builder creates a correctly-typed partitioned table over the output, and the user receives **two** notifications.
- Completion ritual, including the SPEC-074 help sweep and a one-line Key Decisions entry noting Table Builder's new trusted-producer path and the internal queue.
