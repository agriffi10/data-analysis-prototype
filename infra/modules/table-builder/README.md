# `table-builder` — the create-and-refresh-a-table control plane

The standard control-plane shape — see [`../../info/control-plane-shape.md`](../../info/control-plane-shape.md)
for the files, roles and traps every plane shares. What follows is what is distinct here.

**Two branches over one shared spine**, routed by mode: create, and refresh-in-place.

`validate-authorize → {check-table-absent | load-table-definition} → inspect-source → infer-schema →
{execute-ddl | diff-schema → apply-refresh} → release-refresh-lock`

The Lambda side, including the refresh's own fences, is
[`lambdas/info/planes/table-builder.md`](../../../lambdas/info/planes/table-builder.md).

## `glue:DeleteTable` was here and is deleted

The refresh no longer drops and recreates the table; it replaces the definition **in place**, so **no
verb on this plane deletes a table any more**.

The old argument was that a drop is safe because these tables are `EXTERNAL` — true, and beside the
point. The stronger statement is that the refresh path deletes nothing at all, and **a permission the
code cannot use is one a future bug can still reach**. A test greps the table-builder modules to keep
it that way.

**The explicit `Deny s3:DeleteObject` (Sid `NoDataObjectDelete`) is untouched.** It never depended on
the drop: it is what makes "this plane cannot destroy a user's data" enforceable rather than merely
intended, and it outlives the mechanism that prompted it.

**Lake Formation needs no change for the in-place update**, and the absence is recorded so the next
reader does not go looking for a missing grant: the `portal-managed` tag-policy grants already give
every control-plane execution role **ALTER** — the LF permission `UpdateTable` requires — at table
level, alongside DROP at both levels (`modules/analytics/lakeformation.tf`, `control_plane_tag_table`).

## The execution role is also this plane's Lake Formation admin

Wired from root through the analytics `data_lake_settings`. That is what makes `check-table-absent`'s
`GetTable` and `execute-ddl`'s `CREATE` resolve in the **dynamic** per-user and per-shared-space
target databases, which cannot be statically LF-granted.

Glue and table ARNs are therefore scoped to the account catalog's `database/*` + `table/*/*` — **Lake
Formation is what actually gates which database a table lands in**, not the IAM resource scope.

Its ARN is a **constructed string** for cycle-free LF-admin wiring from root.

## `MessageGroupId` is the target database

Two concurrent "create table X" requests against the **same** database serialize strictly
one-at-a-time; creates in **different** databases run in parallel. The duplicate-name race is closed
by `check-table-absent` plus `CREATE … IF NOT EXISTS`.

## `TimeoutSeconds = 3600`, and it is a prerequisite of the refresh lock

A Standard execution may otherwise run for a **year**, which makes "this lock is stale" unjustifiable
at any age. So the bound is not tidy-up — **it is what makes the lock's steal threshold meaningful**.

Derived from the worst case: every Task retries 3 times over 2/4/8-second intervals, so a state costs
`4 × timeout + 14` seconds. The refresh path sums to ~2400 s (validate 74, acquire 74,
load-definition 74, inspect-source 254, infer-schema 494, diff-schema 74, apply-refresh 1214, release
74, notify 74) and the create path to ~2260 s, so 3600 clears both and adding it cannot fail an
ordinary create's Athena polling.

**`tbcommon/table_lock.py` mirrors the number as `MACHINE_TIMEOUT_SECONDS`** and derives its steal
threshold from it. `test_table_lock_timeout.py` holds the two equal **and recomputes the create-path
budget**, so raising a verb's timeout fails there rather than in production.

## The verb map, and what a new entry does and does not touch

`locals.table_builder_functions` is keyed by the function **suffix**, which is simultaneously the
`lambdas/table-builder-<suffix>/` directory and the `deploy-lambdas.yml` matrix name.

Adding an entry:

- **`lambda.tf` needs no edit** — it is entirely `for_each` over this map, so the function, its log
  group and its placeholder zip all follow.
- **`stepfunction.tf` does need one** — its `templatefile()` call passes an explicit per-function map.
- **The deploy role needs none** — `modules/base`'s grant scopes to `{project}-*-table-builder-*`,
  which already covers a new function and its log group.

`acquire-refresh-lock` and `release-refresh-lock` are one conditional S3 read and one conditional
write each — no Glue, no Athena — so both take the smallest shape here. **Their 15 s timeout is an
input to the state machine's `TimeoutSeconds` derivation and to `tbcommon/table_lock.py`; raising
either without the other is caught by `test_table_lock_timeout.py`.**

`table_builder_verb_env` is empty, and that is the point: everything the domain layer's config
requires lives in the **common** env instead. The Cognito pair and the workgroup moved there for
exactly that reason after the 2026-07-05 cold-start break.

## The polars layer

CI builds and publishes it (`deploy-lambdas.yml`) and attaches it to `infer-schema` via
`update-function-configuration` — the artifact is too large to vendor into Terraform, the same
CI-owned pattern as the domain layers. It is named here for the deploy-role wildcard's benefit and
**referenced for documentation and parity only**.

## Logs are scoped by wildcard, deliberately

The shared execution role writes to **every** verb's log group, so its policy scopes to
`/aws/lambda/{project}-{env}-table-builder-*` — one statement covering every function log group,
rather than a per-verb ARN.
