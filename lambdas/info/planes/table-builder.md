# Table builder — control plane

Creates a Glue/Athena **external table** over a folder of files, and refreshes an existing one in
place. "Create table from this folder" in the file browser, targeting the database the space maps to.
Data columns are **inferred**; partition keys are **user-declared** in the modal. Two modes through
one machine, routed by `RouteByMode`.

Table creation is **TBAC**: the Lake Formation admin does *not* grant `CREATE_TABLE`. A
`portal-managed` LF-Tag plus one tag-policy grant per execution role does.

## The machine

`infra/modules/table-builder/state-machine.asl.json.tftpl`

**Create:** `ValidateAuthorize → RouteByMode → CheckTableAbsent → InspectSource → InferSchema →
RouteTailByMode → ExecuteDdl → ReleaseRefreshLock`

**Refresh:** `ValidateAuthorize → RouteByMode → AcquireRefreshLock → LoadTableDefinition →
InspectSource → InferSchema → RouteTailByMode → DiffSchema → RouteByChange → ApplyRefresh →
ReleaseRefreshLock`

**There are TWO routers, not one.** `RouteByMode` picks the head — which verb establishes the state —
and `RouteTailByMode` picks the tail, where the create and refresh paths split again after the shared
`InspectSource → InferSchema` spine.

`ReleaseRefreshLockOnFailure` is the other arm — **the release runs on every terminal path, create
included**.

Two branches over one shared spine. The `mode` field on the envelope (`"create" | "refresh"`, absent
means create) selects the branch, and **inspect-source and infer-schema are shared and know nothing
about it**, because load-table-definition normalises the state into exactly what a create would have
handed them.

FIFO `MessageGroupId` is the **target database**, so same-database creates *and* refreshes serialize.
The duplicate-name race is closed by check-table-absent plus `IF NOT EXISTS`.

## What it accepts

**Formats:** Parquet, CSV and JSON/NDJSON — one consistent format per folder. ORC is out, because
there is no native polars reader.

**CSV is not type-inferred** — every column is `string`, names come from the header, and a header
plus comma separator is assumed, via OpenCSVSerde. Parquet and JSON infer types and parse dates.

**JSON must be NDJSON**, one object per line, which is what Athena's SerDe needs anyway. Its schema
comes from **one sample file**, so fields present only in other files are silently dropped. A
multi-file schema union is deferred. Both limits are user-guide material.

**A JSON string column is typed `date` or `timestamp` only when every sampled value parses as one,
in a shape Athena reads.** Athena's OpenX reader fails in two different ways. It is *lenient* with
a well-shaped impossible value and rolls it over silently, with no error and no NULL:
`2024-13-45` reads back as 2025-02-14, `0000-00-00` as -0001-11-30, and an hour of 25 as the next
day. It *refuses* other values and fails every query that reads the column with `BAD_DATA`:
non-ASCII digits such as Arabic-Indic, a zone or missing seconds after a space separator, a tenth
fraction digit, an offset minute past 59, or an offset wider than ±18:00. What it reads as the same
instant is a space separator with seconds and no zone, or a `T` separator with optional seconds
and an optional `Z` or offset, which it converts to UTC; a fraction is truncated to milliseconds,
Athena's timestamp precision. Only the sample is checked, so a bad value past it, or in another file,
still rolls over or fails. To re-measure, build a two-row NDJSON table through the portal with one
column per shape, then query one column at a time, since a bad value fails only the queries that
read its column.

**Partitions are user-declared keys plus Athena partition projection, never `MSCK REPAIR`.** Keys are
declared in granularity order, each with a projection type and range — `integer`, `date`, or
`enum`-string, not `injected` — and `inspect-source` validates that the declared `key=value/` segments
exist. The table is queryable the instant `CREATE` succeeds, and later partitions are picked up
automatically. A value outside a declared range is silently excluded; the modal copy warns.

**Authorization:** for a personal target, the database equals the actor's username. For a shared one,
the actor is an active member — *any* member may create, not the owner only. The table location must
resolve inside the target space, and the name must be catalog-safe (`CATALOG_IDENTIFIER_RE`).

**Notifications:** a single recipient, the actor, with per-step failure reasons and a success message.

## How the DDL is issued

Creates go through Athena `StartQueryExecution` (`CREATE EXTERNAL TABLE IF NOT EXISTS`), polled to
terminal — the same Lake-Formation-enforced path users already exercise, not the Glue `CreateTable`
API. **That is the create path only.**

The refresh apply issues **one `glue:UpdateTable`** as a read-modify-write on the live table. No
statements, no window in which the table is absent, and **no verb on this plane holds
`glue:DeleteTable`**.

## The fences

- **A refresh is judged by SHAPE, not by a marker** — never by the `portal.managed` property it also
  writes, which pre-existing tables lack and users can set.
- **Removing a column needs an opt-in, and the refusal IS the warning.**
- **The apply is a read-modify-write on the live table**, serialized by a per-table lock whose loser
  is **refused with a notification**, never queued.
- **A column name is user data.** Creates refuse empty, non-`[a-z0-9_]`, over-255 and fold-collision
  names. A *refresh* does not — or it would strand tables that predate the rule.
- **A table's `LOCATION` is read recursively**, so the space root is not a data folder.
- **Results are read only at `SUCCEEDED`.** `GetQueryResults` against a `QUEUED` execution is a 400
  whose name maps to nothing, and it reached users as a generic "contact the administrator".

## The layer — `table-builder-common/tbcommon/`

| Module | Holds |
|---|---|
| `config` | domain configuration, including the refresh definition cap |
| `glue` | the refresh freshness stamp; re-exports `cpcommon.glue.clone_definition` |
| `messages` | user-facing outcome wording |
| `notify` | best-effort outcome notifications |
| `results` | where the plane's Athena statements write their results |
| `table_lock` | the per-table refresh lock |

The schema inference itself is shared: `cpcommon.type_mapping` is the one polars→Hive mapping, and
`cpcommon.columns` holds the column-name rule.

The verbs are listed in [`../INDEX.md`](../INDEX.md).

---

## Why the numbers are what they are

Long-form reasoning that outgrew a docstring: sizing evidence, rejected designs and the
traps. Read the entry for what you are changing.

### `tbcommon/config.py` — sizing `REFRESH_MAX_DEFINITION_BYTES`

The refresh path's definition cap is **40 KiB**, and it is deliberately not tscommon's
`SHARE_MAX_DEFINITION_BYTES`. That 32 KiB was measured for table-share's 50-recipient Map,
where the definition is copied into every item; table-builder has no Map.

> **Note (SPEC-161).** The comparison above is now against a value that means something different:
> table-share's definition travels by pointer, so its 64 KiB bounds Athena's query string, not a
> state payload. The 40 KiB here is unaffected — table-builder's definition still rides on its own
> state, and this paragraph's reasoning about that is unchanged.

What rides on a refresh state instead is one definition plus what `infer-schema` then adds
to the **same** state — its own inferred columns and the generated DDL. **Columns therefore
ride three times** while table properties ride once, so the worst case is a definition spent
entirely on columns (an ordinary flat Parquet table), not a mixed one. Measured at that
composition by `test_load_table_definition.py`:

| cap | columns | whole state | % of 256 KB |
|---|---|---|---|
| 32 KiB | 713 | 92,331 | 35% |
| **40 KiB** | **891** | **115,293** | **44%** ← chosen |
| 48 KiB | 1,069 | 138,255 | 53% ← over half; rejected |

Breaching the 256 KB state-payload limit raises `States.DataLimitExceeded`, thrown **outside
every Catch** — no recorded outcome and no notification, on a request that already did all
its work. So an oversized table is refused up front as a whole-request terminal.

### `table-builder-apply-refresh` — what the in-place update does *not* retire

Stated rather than implied, because SPEC-144 FR-006 AC1 claimed a serialization guarantee
that did not exist.

The Pipe still invokes `StartExecution` as `FIRE_AND_FORGET`
(`infra/modules/table-builder/pipe.tf`), so two refreshes on one database still overlap, and
**Glue offers no compare-and-set to close it**: `UpdateTable`'s `VersionId` is documented only
as "the version ID at which to update the table contents", alongside `TransactionId` and
`ViewUpdateAction`, with no precondition-failure error.

What changes is the **severity**. The worst case degrades from "one run sees no table" to
last-write-wins between two definitions, and `ConcurrentModificationException` — which Glue
raises on genuine simultaneity — is retried. SPEC-157 owns closing the rest.
