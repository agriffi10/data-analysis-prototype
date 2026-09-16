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

`inspect-source` writes a **manifest to S3** and probes every file's header and schema; it reads
Parquet footers with polars, because Athena needs an explicit column list for Parquet and JSON.

**A check cannot target the space root** (`location_is_space_root`, in `validate-authorize`). The
temp table's `LOCATION` is the target folder and Athena reads one recursively, so a check at the top
of a space counts `system_settings/athenaresults/`, archive receipts and `shared_tables/` as the
user's data — and succeeds while doing it. The listing skips those sub-trees and that is not the
fix: the manifest is what the verb knows about, the location is what Athena reads. A single FILE
at the root is still accepted, because every query it starts carries a `"$path"` predicate.

The dedicated workgroup leaves `bytes_scanned_cutoff_per_query` **unset**, because the portal
workgroup's 10 GiB cutoff would fail every real check; the result location is set per query.
Each `StartQueryExecution` carries its own `ClientRequestToken` — the request id with its hyphens
stripped, plus a per-query suffix (`-profile`, `-ragged`, `-dupes`) — so a retry re-attaches to the
original execution and the three concurrent queries do not collide on one token. The suffix is the
load-bearing half: one token shared by three submissions would make the ragged and duplicates
queries re-attach to the profile execution instead of running.
Temp tables are named `dq_tmp_{hex32}` — hyphens would parse as subtraction.

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
- **Three refusals at the temp table, not one, because they ask for three different repairs.** A
  column name Athena cannot use (`invalid_column_names`, edit a header), a `key=value` folder whose
  key cannot be one (`invalid_partition_names`, rename a folder), and a CSV column named after a
  partition that is not at the end of the header (`partition_column_not_last`, move or drop the
  column). The third exists because the typed table leaves such a column out and a CSV is read by
  POSITION, so the report would describe every later column against its neighbour's field — worse
  than no report, since the user acts on it.
- **A column named after a partition gets no per-column figures, in any format.** The typed table
  leaves it out, and a query naming it anyway does not fail: Athena lowercases the name and binds
  it to the partition column, so the report showed the folder's value under the user's column
  name. The profile, the duplicates grouping and the report all read `sql.profiled_columns`, the
  DDL builder's own `ddl.body_columns`, and the aliases are numbered over that one list — filtering
  on one side only, or after numbering, moves every later column's figures onto its neighbour, and
  a missing cell reads as a clean zero. The column is **absent, not skipped**: there is no figure
  to mark, and the incomplete banner would point at nothing. Cross-file agreement and the ragged
  comparison still count it, because they read the file.
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

`data-quality-polars/` holds a `requirements.txt` and no source of ours — polars, installed into
the image for the byte scan. It is named in `assemble.NOT_SHARED` for exactly that reason: it is
neither a function nor shared code, and a directory that is neither has to say so. The bounded reader that feeds it is
`cpcommon.bounded_read`, which exists so the probe does not need polars' cloud reader.

The verbs are listed in [`../INDEX.md`](../INDEX.md).

---

## Why the numbers are what they are

Long-form reasoning that outgrew a docstring: sizing evidence, rejected designs and the
traps. Read the entry for what you are changing.

### `dqcommon/config.py` — sizing the byte-scan budget

**Why the budget is per REQUEST, never per file.** An earlier version bounded it per file:
256 MiB × up to 1000 files ≈ 276 GB through one 1024 MB Lambda in 300 s ≈ **920 MB/s
sustained**, against a real-world ~60–100 MB/s. It would have passed on a three-file fixture and
timed out in production — the exact error class this arc's re-architecture exists to eliminate.

**`DQ_SCAN_MIN_SAMPLE_BYTES` — the second disaster, which the byte budget does not prevent.**
Bytes are not the only cost; **requests** are. A flat 1 head + 20 ranged reads per file is
**21,000 sequential GetObjects** on a 1000-file manifest. At ~30 ms round-trip each that is
~630 s against the function's 300 s ceiling, while reading only the 2 GiB the byte budget
permits. It would have timed out on exactly the large folders the budget rewrite was meant to
save, for a completely different reason.

So a file's share only buys a ranged read when that read is worth a round trip. Measured across
the range (share = 2 GiB / fileCount, head = half of it):

| files | samples | GETs | time |
|---|---|---|---|
| 1 | 20 | 21 | ~36 s |
| 12 | 20 | 252 | ~43 s |
| 100 | 2 | 300 | ~44 s |
| 1000 | 0 | 1000 | ~65 s — 21,000 GETs / ~630 s without the floor |

Both costs are now bounded: never more than `DQ_SCAN_TOTAL_BYTES`, and never more than ~1000
requests. At 1000 files no sample clears the floor, so a file's 2 MiB share buys only its head
window — `head = int(share * DQ_SCAN_HEAD_FRACTION)` = **1 MiB**, and the 1 MiB remainder is
under `DQ_SCAN_MIN_SAMPLE_BYTES`, so it buys no ranged read at all. That is the right trade: one
contiguous 1 MiB read beats 21 scattered 100 KiB ones for finding a corrupt export, and the
report says the coverage is sampled either way.
