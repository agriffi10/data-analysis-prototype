# Data quality — control plane

Profiles a table and writes a report: row counts, null rates, distinct counts, and the one check a
SQL engine cannot do — a byte scan for ragged rows.

## The machine

`infra/modules/data-quality/state-machine.asl.json.tftpl`

`ValidateAuthorize → InspectSource → CreateTempTables → StartProfileQuery → WaitForQuery ⇄
CheckQuery → ByteScan → AssembleReport → DropTempTables`

`DropTempTablesOnFailure` is the other arm — **cleanup is reached on every path**.

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
| `sql` | Athena SQL generation for the checks |

`data-quality-polars/` is a second layer with no source of ours — polars, installed from its
`requirements.txt`, for the byte scan. The bounded reader that feeds it is
`cpcommon.bounded_read`, which exists so the probe does not need polars' cloud reader.

The verbs are listed in [`../INDEX.md`](../INDEX.md).
