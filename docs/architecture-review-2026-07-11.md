# Review: `data-quality-architecture.md` + `file-converter-architecture.md`

**Reviewed:** 2026-07-11 · **Reviewer:** fresh-context validation pass against the repo at `1d9256d`
**Status of the docs under review:** both Proposed, untracked, pending approval.
**Verdict:** **Do not approve as written.** The orchestration shape is right and consistent with precedent, but there are **3 correctness bugs that would ship**, **2 structural designs that cannot work at the stated scale**, and **1 data-loss hazard**. Roughly 8 of the 11 proposed specs survive largely intact; the two "do the actual work" specs (SPEC-110, SPEC-115) need redesigning before they're written.

Everything below is grounded in the code, quoted with `file:line`. Where I say "no precedent," I mean I looked and there isn't one.

---

## 0. What the docs get right

Worth saying plainly, because most of this review is criticism. These are verified correct against the code:

- **The pipeline shape.** FIFO SQS + DLQ → EventBridge Pipe (`batch_size = 1`, `FIRE_AND_FORGET`) → Standard Step Function → single-task verb Lambdas on one shared execution role. That is exactly what `infra/modules/table-builder/pipe.tf:14-31` and `infra/modules/table-share/` do. The "reuse the pattern, not the resources" reasoning and the `lambdas.md` §1 citation against folding these into an existing orchestrator are both on target.
- **The auth model.** ID token in the body, verified offline against JWKS with PyJWT, actor derived from the `cognito:username` claim, never from the body (`tbcommon/auth.py:15-39`). Correctly described.
- **Table Builder's limitations that file-converter exists to remove.** CSV-all-string (`table-builder-architecture.md` §4, `infer_schema.py:85`) and single-sample-file schema inference (§10, `infer_schema.py:118`) are real, documented, and correctly cited. The premise of the file-converter pipeline is sound.
- **Spec numbers 107–117 are all free.** `docs/specs/INDEX.md` runs 001→106 with no gaps. No collision.
- **Two layers on one function is precedented** (infer-schema carries polars + tbcommon, `deploy-lambdas.yml:296`), so file-converter's `fccommon` + polars(+Excel) shape is fine in principle.
- **The notification contract.** Best-effort emit, friendly SPEC-106 wording, `MessageGroupId` = recipient username (`tbcommon/notify.py:110-134`, `tbcommon/messages.py`). Correctly described.

---

## 1. BLOCKERS — correctness bugs that would ship

### 1.1 `MessageGroupId` = the S3 location will exceed SQS's 128-character limit

**Severity: high. Both docs.** `data-quality-architecture.md:39` ("`MessageGroupId` = the target location (bucket+prefix)") and `file-converter-architecture.md:37` ("`MessageGroupId` = the destination location").

SQS caps `MessageGroupId` at **128 characters**. A bucket name (up to 63) plus a `/` plus an S3 prefix (keys go to 1024 characters) blows that with a user who is a couple of folders deep. The send fails, and it fails *in the browser*, at enqueue time, for exactly the users with the deepest folder structures — i.e. the ones most likely to need these features.

The docs present this as mirroring precedent. It doesn't. **Every existing producer uses a short, bounded identifier:**

| Producer | `MessageGroupId` | Bound |
|---|---|---|
| table-builder (`tableBuild.service.ts:49`) | `req.space.database` | ≤63 — `CATALOG_IDENTIFIER_RE` (`tbcommon/config.py:40`) |
| table-share (`tableShare.service.ts:65`) | `` `${database}.${table}` `` | ≤127 by construction — one char under the cap |
| shared-space (`sharedSpaces.service.ts:19`) | the constant `'shared-space'` | 12 |

Nothing in the codebase hashes or truncates a group id, so there is no precedent to inherit for a fix either.

**Recommended fix.** Use a **SHA-256 hex digest of the canonical location** as the group id (64 chars, fixed). The hashing primitive already exists — `tableShare.service.ts:22-30` does exactly this for its *dedup* id via `crypto.subtle.digest`. Serialization semantics are preserved (same location ⇒ same digest ⇒ same group), and the id stops being human-readable in the console, which is an acceptable trade. State this explicitly in both docs rather than leaving it to implementation.

### 1.2 The data-quality doc contradicts itself on `.txt`, and both docs mis-cite Table Builder's extension handling

**Severity: high (a spec written from this would encode a false requirement). Both docs, line 17.**

`data-quality-architecture.md:17` says a `.txt` file "is rejected the same way it would be by Table Builder." But **§4 of the same doc (line 53) lists `.txt` → csv as a *supported* input**, and the doc's headline supported-inputs list is "CSV/TXT." Both cannot be true.

And Table Builder does not do what's claimed. `lambdas/table-builder-inspect-source/inspect_source.py:22-28`:

```python
_EXT_FORMAT = {
    ".parquet": "parquet",
    ".csv": "csv",
    ".json": "json",
    ".ndjson": "json",
    ".jsonl": "json",
}
```

**There is no `.txt` and no `.xlsx`.** A `.txt` data file in Table Builder dies as `unsupported_format` (`inspect_source.py:113`) — it is not "classified as CSV and then rejected on content," it is rejected on *extension*. So the analogy in both docs is wrong in both directions.

Both docs also pin extension classification to **table-builder-architecture.md §4**. §4 never mentions extensions — the word "extension" appears exactly once in that entire document, in **§10**. The behaviour is real but lives in code (SPEC-068 / `inspect_source.py`), not in §4.

**Recommended fix.** (a) Drop the `(§4)` pin; cite SPEC-068 / `inspect_source.py` instead. (b) Delete the "rejected the same way as Table Builder" sentence from both docs — it is not true, and the two new pipelines are *deliberately* extending the extension map with `.txt` and `.xlsx`, which is a **new decision that should be stated as one**, not smuggled in as inherited behaviour. (c) State plainly: these two pipelines accept a strictly larger extension set than Table Builder, and a content/extension mismatch is undetected in all three.

### 1.3 The data-quality report path uses a `requestId` that isn't in the request

**Severity: medium (trivially fixable, but it means the envelope is under-specified).**

`data-quality-architecture.md:65` names the report `{space}/_data-quality-reports/{requestId}-{sourceName}.json`. The request envelope in its own §2 diagram (line 24) is `{ actor(idToken), space{kind,bucket,prefix}, location }` — **no `requestId`**. Table Builder's envelope has one (`tableBuild.service.ts:36`); Table Share's does not (`tableShare.service.ts:52-57`). Add it to the envelope explicitly in SPEC-108, and note that it is also what the notification dedup id is built from (`tbcommon/notify.py:30-32`).

---

## 2. DATA-LOSS HAZARD — the reserved-prefix blocklist is incomplete

**Severity: highest in this review. `file-converter-architecture.md:44`.**

The converter's destination-validation blocklist is `athenaresults/`, `shared_tables/`, `_data-quality-reports/`. **It is missing `user_settings/` and the root `DO_NOT_DELETE.txt` marker.**

Why this is not a nitpick: the user-space IAM policy denies **`s3:DeleteObject`** on `user_settings/*` (`analytics/policies/portal-role-analytics.json.tftpl:67-72`) but leaves **`s3:PutObject` wide open**. So a converter execution role scoped to "write anywhere in the actor's own space" can overwrite:

- `user_settings/notifications.json` — the notifications inbox. The writer Lambda is the sole writer and does read-modify-write; a Parquet blob there makes the array unparseable. The SPA degrades gracefully (`notifications.service.ts:61,65` logs and treats it as empty), so **every unread notification is silently and permanently lost** — and the user **cannot delete the corrupt file to self-heal, because delete is IAM-denied.** That is an unrecoverable state reachable by a user typing a destination path into a form.
- `user_settings/shared-connections.json` — same trap; the Connections UI cache is destroyed.
- `user_settings/saved-queries.json`, `user_settings/query-history.json` — same.
- The root `DO_NOT_DELETE.txt` marker — overwritable (only *delete* is denied).

The doc's own "non-empty destination = conflict" guard does not save you: it is described as a *prefix-emptiness* check, and on a fresh account `{username}/user_settings/` is empty before the first notification is written.

**Recommended fix (three parts, all needed):**

1. Blocklist becomes `athenaresults/`, `user_settings/`, `shared_tables/`, `_data-quality-reports/`, **plus** an explicit guard on the root `DO_NOT_DELETE.txt` object. Applies to the data-quality report destination too, not just the converter.
2. The execution roles carry an explicit **`Deny s3:PutObject` on `*/user_settings/*` and `*/DO_NOT_DELETE.txt`** in both buckets. Belt and braces — a validation bug shouldn't be able to reach the inbox. There is a precedent for a cross-bucket deny statement: `table-share/policies/execution.json.tftpl:59-68` denies `s3:DeleteObject` across all three buckets.
3. Note in the doc that the deny is what makes the guarantee, not the validation.

---

## 3. STRUCTURAL — the two "do the work" verbs cannot work as designed

This is the part that needs a real decision from you, not an edit.

### 3.1 `scan-quality` and `convert-to-parquet` are the first Lambdas in this codebase to pull file bytes through the function — and they're each specified as a *single* invocation over a *whole folder*

Here is the actual execution budget in this repo. Every verb Lambda, from Terraform:

| Function | timeout | memory | what it touches |
|---|---|---|---|
| table-builder-validate-authorize | 15s | 256 MB | metadata |
| table-builder-check-table-absent | 15s | 256 MB | Glue metadata |
| table-builder-inspect-source | 60s | 512 MB | S3 listing only |
| table-builder-infer-schema | 120s | 1024 MB | **one sample file**, footer/header only |
| table-builder-execute-ddl | 300s | 512 MB | Athena |
| table-share-copy-objects | **900s** | 1024 MB | **server-side copy — zero bytes through the function** |
| shared-space verbs (×8) | 60s | 128 MB (default) | registry JSON |

(`infra/modules/table-builder/locals.tf:33-37`, `infra/modules/table-share/locals.tf:36-40`)

**No existing verb reads bulk data.** The heaviest one, `copy-objects`, moves 20 GiB in 900s precisely *because* the bytes never enter the Lambda (`table_share_copy_objects.py:8-9`), and its 1000-object / 20 GiB caps (`tscommon/config.py:44-45`) were sized so that fits.

Both new verbs break that invariant. `scan-quality` must *decode every byte* of every file; `convert-to-parquet` must *read, reconcile, and rewrite* every byte. Both are specified as one Lambda over an entire folder. Lambda's hard ceiling is **900s**, and these docs explicitly say the target files are "expected to be big."

This is not a tuning problem. A single invocation over an unbounded folder of large files has **no size at which it reliably completes** — it will work in testing and time out in production on the first real dataset, after burning 15 minutes of compute, with the failure arriving as a notification rather than anything actionable.

**Recommended redesign — a per-file `Map`, which is already precedented.** Table Share's state machine has exactly this: `"Type": "Map"`, `"MaxConcurrency": 5`, `Mode: INLINE`, with a per-item `Catch` that fails *that item* and lets siblings continue (`table-share/state-machine.asl.json.tftpl:67-216`). Apply the same shape:

- **file-converter:** `validate-authorize → inspect-source (probe every file's schema) → reconcile-schema (pure, cheap, no I/O) → Map(file){ convert-one-file } → finalize`. Per-invocation work is now bounded by the **largest single file**, not the folder. Schema reconciliation still happens once, globally, before the Map — which is the whole point of the pipeline and is preserved.
- **data-quality:** `validate-authorize → inspect-source → Map(file){ scan-one-file } → assemble-report`. Cross-file column agreement (the one genuinely cross-file check) becomes a cheap reduce in `assemble-report` over per-file column lists.

Then add a **hard per-file size cap** and a **folder object-count cap**, mirroring `SHARE_MAX_OBJECTS = 1000` / `SHARE_MAX_TOTAL_BYTES = 20 GiB`, enforced in `inspect-source` with a terminal `source_too_large`. Note table-builder's `inspect-source` has **no caps at all** (it gets away with it by reading one file), so the caps must come from Table Share's precedent, not Table Builder's.

### 3.2 The 256 KB Step Function payload limit will break `inspect-source`'s output

`file-converter-architecture.md:102` has `inspect-source` emit `{format, files[], schemas[]}` as SFN state. With a 1000-object folder, a per-file list plus a per-file schema is comfortably over **Step Functions' 256 KB state-payload limit**. The execution fails with `States.DataLimitExceeded` — a failure mode with no notification path, because it kills the state machine outside any Catch that produced a friendly reason.

Same risk for data-quality's per-file findings collecting through a Map.

**Recommended fix.** Pass an **S3 pointer** (a manifest object written by `inspect-source`, e.g. `{space}/_data-quality-reports/{requestId}/manifest.json`) between states rather than inline arrays, and have the Map iterate over a bounded index. Alternatively cap the object count low enough that the payload provably fits — but a pointer is the honest fix and costs one PutObject.

### 3.3 Neither writer verb is replay-safe, and one of them can silently corrupt data

**There is no request-id idempotency check in any verb in this codebase.** I looked. `requestId` is threaded through table-builder but its *only* consumer is the notification dedup id (`tbcommon/notify.py:30-32`). Existing replay-safety comes entirely from **natural idempotence**:

- `CREATE EXTERNAL TABLE IF NOT EXISTS` (`execute_ddl.py:46`)
- Glue `GetTable` → `EntityNotFoundException` pre-check (`check_table_absent.py:44-52`)
- S3 `PutObject` with **`If-None-Match: *`** for create-once (`shared-space-common/registry.py:109`)
- re-copying the same S3 keys is harmless (`table_share_copy_objects.py:7-9`)

Both new pipelines end in a verb that **writes new S3 objects with no conditional primitive**. An SFN retry or an SQS redelivery re-runs it. For data-quality that's benign (the report is overwritten with an identical report). **For file-converter it is not benign:** if output filenames carry any nondeterminism (a UUID, a timestamp, a polars-assigned part number), a replay writes a *second* set of Parquet files alongside the first. Table Builder is then pointed at that folder, and **the resulting table silently double-counts every row.** Wrong numbers, no error, no notification, discovered by a human noticing revenue doubled.

`lambdas.md` §3 already asks for this ("carry a stable `requestId`/dedupe key… treat a replay of an already-terminal request as a no-op success"), and the existing code only partly satisfies it.

**Recommended fix.** Output keys must be a **pure deterministic function of the source key** (e.g. `sales/2024/part-0.csv` → `sales_parquet/2024/part-0.parquet`), so a replay overwrites byte-identically and is a true no-op. State that as a decision in the doc, and add `If-None-Match: *` where create-once semantics are wanted. This also happens to be what makes §5's "preserve relative layout" implementable.

### 3.4 A converter destination inside an existing table's `LOCATION` silently poisons that table

The default destination (`{parent}/{folderName}_parquet/`) is a sibling, so the common case is safe. But the doc says the destination is **user-overridable**, and nothing in the proposed validation checks whether it lands under an existing Glue table's `LOCATION`.

Athena reads **everything** under a table's `LOCATION`. Writing new Parquet into a live table's prefix means the next query either fails on a schema mismatch or — worse — **succeeds and returns silently-wrong unioned rows**. Partition-projection tables (which is all of them here, per `table-builder-architecture.md`) will project straight into new `key=value/` directories with no `MSCK`, so a stray write reaches query results with zero operator action.

Detecting this properly requires Glue `GetTables` on the actor's database — **which reintroduces the Glue + Lake Formation grant that §6 proudly says this pipeline doesn't need.** That is the central tension in the "no catalog access at all" claim, and the doc should name it rather than leave it unstated.

**Three honest options, pick one in the doc:**

- **(a) Constrain the destination.** Converter output may only land under a reserved namespace (e.g. `_converted/…`), never an arbitrary user-chosen path. Keeps the zero-catalog role; costs flexibility. **My recommendation** — it's the only one that preserves the doc's headline simplification.
- **(b) Pay the catalog cost.** Add Glue read + an LF grant to the execution role so `validate-authorize` can reject a destination under a live `LOCATION`. Cheapest for the user, most expensive for the blast radius, and it makes §6's central claim false.
- **(c) Accept and document.** Allow it, warn in the UI. I'd argue against — the failure is silent and produces wrong numbers.

---

## 4. FACTUAL corrections (cheap edits)

| # | Where | Problem | Fix |
|---|---|---|---|
| 4.1 | dq:17, fc:17 | Extension classification cited to table-builder-architecture **§4**; §4 never mentions extensions | Cite SPEC-068 / `inspect_source.py` |
| 4.2 | dq:46, fc:43 | "the actor must be an **active member**" | Ambiguous, and a reader who knows SPEC-073 will read it wrong. `is_active_member` (`tbcommon/registry.py:24-26`) means *the space's* `status == "active"` **and** actor ∈ `members`. It has nothing to do with SPEC-073's per-member Pending/Active chip — and a **Pending member passes it**, because SPEC-073 is explicit that "access is already granted at add time" (SPEC-073, Out of Scope). Reword to "the space is `active` and the actor is in its `members` list (not SPEC-073's display-only join chip)" |
| 4.3 | dq:32, fc:30 | "a Catch routes any step's terminal failure to a **recorded**-failure state" | The existing `RecordFailure` states are `Type: "Pass"` → `Fail` (`table-builder/state-machine.asl.json.tftpl:190-202`). **Nothing is persisted to S3.** The "record" is the SFN execution history. Fine — but say so, so nobody builds a UI expecting a durable failure object |
| 4.4 | fc:92 | Bucket named literally as `dat-prod-shared-space` | It's **derived**: `"${var.project_name}-prod-shared-space"` (`infra/main.tf:50`). Currently correct, structurally wrong. Say `local.shared_space_bucket_name` |
| 4.5 | dq:85 | dqcommon needs "no polars, **no Excel-engine dependency**" | **Self-contradiction.** §5 (line 61) requires opening `.xlsx` workbooks and detecting formula-error cells and merged cells. That needs an Excel reader (openpyxl or calamine). Either drop Excel from data-quality v1 or admit the dependency |
| 4.6 | fc:82 | Excel/layer size "needs checking against the 250 MB ceiling" | Understated. The 250 MB unzipped ceiling is **shared across all attached layers *plus* the function code** — and the existing CI guard measures **one layer directory in isolation** (`deploy-lambdas.yml:121-128`). `fccommon` (PyJWT[crypto] pulls in `cryptography`) + polars + fastexcel is all counted together, and **CI would not catch a combined overflow.** The guard needs extending, and that's in-scope work for SPEC-112 |
| 4.7 | dq:87, fc:91 | "Deploy-role IAM expanded" as a one-liner | It's the one part that can actually **break an apply**. Table Share needed its own **separate customer-managed policy** because the deploy role's inline-policy 6,144-char budget is exhausted (`base/iam.tf:134-136`), 8 statements incl. a non-resource-scopable `states:ValidateStateMachineDefinition` on `"*"`, and — critically — the grant had to land in a **prior PR** before the module's resources (`base/iam.tf:145-146`, the deploy-perms-before-resources rule). **SPEC-107 and SPEC-112 must each be split into two PRs** or the first apply fails |
| 4.8 | dq:86, fc:90 | `VITE_*_QUEUE_URL` "exported" | Each new queue costs **four** edits, one of which is not IaC: `outputs.tf`, `.env.example`, `deploy-app.yml` build env, **and a manually-set GitHub repo variable**. This is a documented footgun (`.env.example:61-62` literally calls it "the VITE_* deploy gotcha"). Name it in both docs |

---

## 5. GAPS — decisions the docs don't make but a spec-writer will need

1. **`_data-quality-reports/` is visible in the Files UI.** The `_`-prefix convention is a **Python-side convention only** — the SPA has no `_`/`.` filter (`fileBrowser.service.ts:81-99`), and the only hidden folder is `user_settings` (`protectedFolders.ts:11`). Users will see the reports folder, and can move and delete it. Either add it to `HIDDEN_BROWSER_FOLDERS` (in scope for SPEC-111) or accept it — but decide.
2. **Worse: Table Builder would ingest the reports as source data.** `tbcommon/s3_listing.py:35` checks only the **basename** (`if base.startswith("_")`), so `alice/_data-quality-reports/rpt.json` is **not** ignored — the `_` is in a path *segment*, not the basename. `tscommon` already fixed this and says so ("Deliberately extends the table-builder's basename-only rule", `tscommon/s3_listing.py:32-37`). So the data-quality doc's choice of a `_`-prefixed folder is only safe against `tscommon`. **Fixing `tbcommon` to segment-level is a prerequisite** and belongs in the DQ arc as explicit scope.
3. **Duplicate-row detection by hash is a memory bomb.** `dq:59` says "Count duplicate rows by hash." A hash set over every row of a multi-GB file is unbounded memory in a Lambda. Needs a bounded structure (sampling, or a probabilistic counter) or an explicit row cap — and the report must then say *"duplicates within the scanned sample,"* not *"duplicates."*
4. **The hybrid-mode dependency is load-bearing and unstated.** Both docs present "no LF grants" as a *simplification*. It is actually a *consequence* of the user-space bucket being LF-registered in **hybrid** mode (`analytics/lakeformation.tf:60-66`), which `architecture.md:108-111` flags as something that must never be flipped to enforced. If anyone flips it, both pipelines break with an S3 `AccessDenied` from inside a Lambda. Cite the constraint as the *reason* the simplification is legal, so the coupling is discoverable.
5. **Four copies of the JWT verification code.** `tbcommon/auth.py` and `tscommon/auth.py` are already **byte-identical twins**. These docs add `dqcommon` and `fccommon`, making **four independent copies of the security-critical token-verification path**, plus four copies of `registry.py`, `s3_listing.py`, `notify.py`, and `messages.py`. "Reuse the pattern, not the resources" is the right principle for *infrastructure*; applying it to *security code* means a JWKS or claim-validation fix has to land in four places and will eventually land in three. **This is worth escalating as its own decision** — a shared base layer (or a published internal package the four layers depend on) before a third and fourth copy exist, not after.
6. **DLQ has no consumer or alarm.** Both docs provision a DLQ and never say what watches it. Neither do the existing modules, as far as I can tell — so this is a pre-existing gap the new pipelines inherit and widen. Worth one line.
7. **No reserved concurrency / cost control.** These are the first pipelines where a user can enqueue expensive compute. Nothing bounds how many conversions one user can start.
8. **The UI specs (SPEC-111, SPEC-116) don't mention the four things every UI spec in this repo now has to do:** responsive behaviour per SPEC-095 (`MobileActionBar`, the `tablet:`/`desktop:` breakpoints — a new toolbar action *must* land in the mobile action bar), a11y assertions per SPEC-045 (`vitest-axe`), error wording per SPEC-106 (`toUserMessage` — never render `error.message`), and the SPEC-074 **Help content sweep** required by the completion ritual. Add them to the arc table.

---

## 6. The alternative neither doc considers

Both docs assume a Lambda pipeline is the only way to do this. For **file-converter specifically**, this project already owns a distributed query engine that converts to Parquet natively: **Athena `CREATE TABLE AS SELECT` with `format = 'PARQUET'`**, with `CAST`s to fix types.

- **For:** no 900s ceiling, no memory ceiling, no bytes through Lambda, scales to datasets that will *never* fit the Lambda design, and reuses infrastructure that is already built, granted, and shipped. It writes Parquet with correct types to an S3 location — which is precisely the deliverable.
- **Against:** it needs a table over the *source* first (so Table Builder runs first, and its CSV-all-string behaviour means the CTAS carries explicit `CAST`s — arguably *fine*, since CTAS is where you'd want the typing decision anyway); it needs Glue + Athena + LF grants, so the "zero catalog access" simplification evaporates; CTAS controls output layout less precisely; and the workflow becomes "build table → convert" rather than "convert → build table," which inverts the UX story in §1.

I am **not** recommending you switch. The Lambda design has a genuinely better UX story (convert the messy file *before* it ever becomes a table) and a much smaller IAM footprint, and those are good reasons. But a decision record whose whole job is to say *why the feature looks the way it does* should record that CTAS was considered and rejected, and why — otherwise the first reviewer who thinks of it re-opens the whole arc.

---

## 7. Recommended next steps

1. **Fix the blockers** (§1) and the data-loss hazard (§2) — these are edits, not redesigns, and they're unambiguous.
2. **Decide the two structural questions** (§3.1 per-file Map, §3.4 destination constraint) — these change the spec arcs, so they must be settled before any spec is written. My recommendations: adopt the Map, and constrain converter output to a reserved namespace.
3. **Escalate the shared-auth-layer question** (§5.5) — it's the kind of decision that gets 10× more expensive after these two arcs ship.
4. Then re-issue both docs and I'll do a second pass against the revised versions.

The two arcs are worth building. The orchestration instinct is right, the reuse of the auth model is right, and the file-converter's premise (fix the data *before* it hits the catalog, rather than re-opening Table Builder's simplifications) is a genuinely good architectural call. It's the two verbs that do the actual data work that need another iteration.
