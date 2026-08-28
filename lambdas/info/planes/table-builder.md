# Table builder — control plane

Creates a Glue/Athena table over a folder of files, and refreshes an existing one in place. Two
modes through one machine, routed by `RouteByMode`.

Table creation is **TBAC**: the Lake Formation admin does *not* grant `CREATE_TABLE`. A
`portal-managed` LF-Tag plus one tag-policy grant per execution role does.

## The machine

`infra/modules/table-builder/state-machine.asl.json.tftpl`

**Create:** `ValidateAuthorize → RouteByMode → CheckTableAbsent → InspectSource → InferSchema →
ExecuteDdl → ReleaseRefreshLock`

**Refresh:** `ValidateAuthorize → RouteByMode → AcquireRefreshLock → LoadTableDefinition →
InspectSource → InferSchema → DiffSchema → RouteByChange → ApplyRefresh → ReleaseRefreshLock`

`ReleaseRefreshLockOnFailure` is the other arm — **the release runs on every terminal path, create
included**.

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
