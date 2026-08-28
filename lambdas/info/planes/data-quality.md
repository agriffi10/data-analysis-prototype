# Data quality — control plane

Profiles a table and writes a report: row counts, null rates, distinct counts, and the one check a
SQL engine cannot do — a byte scan for ragged rows. "Check data quality" on a file or folder, over
CSV/TXT, JSON/NDJSON and Parquet, classified by **extension**. There is no Excel support — convert to
Parquet first. It is **diagnostic only** and never writes to the source.

**The work is Athena's, not Lambda's.** Real sources reach 250 GB, and a Lambda byte-pass would take
hours against a 900-second ceiling, where Athena computes the exact checks in minutes. The accepted
cost is that the execution role holds Glue, Athena and Lake Formation (TBAC create; admin for
Describe only) — the same blast radius as table-builder, deliberately surrendered for exactness.
Sampling and Fargate-in-a-VPC were both rejected, and Fargate remains the recorded escape hatch.

## The machine

`infra/modules/data-quality/state-machine.asl.json.tftpl`

`ValidateAuthorize → InspectSource → CreateTempTables → StartProfileQuery → WaitForQuery ⇄
CheckQuery → ByteScan → AssembleReport → DropTempTables`

`DropTempTablesOnFailure` is the other arm — **cleanup is reached on every path**. That is safe
because it touches Glue only: the role holds **no `s3:DeleteObject` anywhere**, plus an explicit
`Deny s3:PutObject` on `*/user_settings/*` and `*/DO_NOT_DELETE.txt`, since an overwrite of
`notifications.json` would be unrecoverable.

**The Athena poll lives in the state machine** (`Wait(30s)` → check-query → `Choice`), not inside a
Lambda. That is this plane's key structural difference, and Standard executions are what remove the
time ceiling. What remains is the **account-level Athena DML quota — 30 minutes by default, 240 by
support ticket** — which is the real ceiling on the feature.

`inspect-source` writes a **manifest to S3** and probes every file's header and schema; it carries
the polars layer, because Athena needs an explicit column list for Parquet and JSON.

The dedicated workgroup leaves `bytes_scanned_cutoff_per_query` **unset**, because the portal
workgroup's 10 GiB cutoff would fail every real check; the result location is set per query.
`StartQueryExecution` carries `ClientRequestToken = requestId`, so a retry cannot start a second
query. Temp tables are named `dq_tmp_{hex32}` — hyphens would parse as subtraction.

**Queueing:** `MessageGroupId` is a SHA-256 of the canonical location, because raw S3 keys can exceed
SQS's 128-character cap; `MessageDeduplicationId` is the `requestId`.

## The checks

**Exact:** per-column type consistency via `TRY_CAST` (skipped for Parquet, and the report says so,
because the format enforces types); null and blank ratios; row counts per file (`"$path"`) and in
total; JSON key drift using the **Hive** JSON SerDe, never OpenX — OpenX yields nondeterministic
nulls and the whole story rests on "null means missing key". **Duplicates run as a separate query**,
a full shuffle and the most expensive thing Athena does, and they degrade to `not_computed` on
resource exhaustion rather than failing the check. `DQ_MAX_COLUMNS` (200) guards Athena's
262,144-byte query-string cap.

**Approximate**, and labelled as such in both the report and the notification: ragged rows via a
single-column raw-line temp table (`\001` delimiter — quoted delimiters and embedded newlines
over-report); invalid UTF-8 via `byte-scan`, bounded **per request** by `DQ_SCAN_TOTAL_BYTES` (2 GiB,
divided across the manifest) with the coverage percentage stated. Compressed text is not splittable,
so a large `.gz` is rejected with guidance.

## The report, and how it is found

`{space}/_data-quality-reports/{requestId}/report.json`. The key is a pure function of `requestId`,
so a replay overwrites byte-identically. The folder is hidden in the browser, and the notification
deep-links to `/data-quality/:space/:requestId`.

The `/data-quality` dashboard reads a per-space `index.json` appended under ETag CAS, capped at 200
entries with every failure swallowed — the durability order is report, then notification, then index
— and it can start new checks.

**Cost, honestly:** roughly $5 per TB scanned across multiple scans (profile, raw-line, duplicates),
so about $2.50–3.75 for a 250 GB check, with **no scan guardrail** and nothing capping runs per user.
Revisit before real users arrive.

## The fences

- **The notification IS the completion channel**, and it must carry the report link, because the
  reports folder is hidden.
- **The runs index is appended under ETag CAS.** S3 lists lexicographically, so a UUID key gives no
  chronology — the index is what supplies it.
- **A route that renders a report must not become an existence oracle.** The report view takes its
  space **from the route, never derived**, and an unreachable space renders denied while issuing
  **no S3 request at all**.
- **`StartProfileQuery` submits the three checks and waits for none of them** — the wait is the
  machine's, not the verb's.
- **Results are read only at `SUCCEEDED`** (see table-builder — the same 400).

## The layer — `data-quality-common/dqcommon/`

| Module | Holds |
|---|---|
| `config` | domain configuration |
| `index_store` | the per-space runs index, one small entry per completed check |
| `manifest` | reading the source manifest `inspect-source` wrote |
| `messages` | user-facing wording and reason codes |
| `notify` | best-effort outcome notifications |
| `report` | the report shape, its exact-versus-approximate tagging, and the top-issues wording |
| `results` | where the temp-table verbs' DDL writes, beside the request's report |
| `sql` | Athena SQL generation for the checks |

`data-quality-polars/` is a second layer with no source of ours — polars, installed from its
`requirements.txt`, for the byte scan. The bounded reader that feeds it is
`cpcommon.bounded_read`, which exists so the probe does not need polars' cloud reader.

The verbs are listed in [`../INDEX.md`](../INDEX.md).
