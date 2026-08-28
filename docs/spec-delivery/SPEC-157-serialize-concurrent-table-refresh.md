# Completed Spec — SPEC-157: Serialize Concurrent Table Refresh

## What was completed?

The concurrent-refresh race SPEC-149 left open is closed by a per-table lock outside Glue. No
user-facing feature; two new user-visible *failure* messages.

- **`tbcommon/table_lock.py`** — `lock_key` / `acquire` / `release` over conditional `PutObject`.
  Claims under `IfNoneMatch` when absent and `IfMatch` when free or stale; a lost precondition is a
  refusal, never a retry. Reuses `cpcommon.cas.is_precondition` but **not** `cas_mutate`, whose
  contract is to retry on exactly the failure that means "someone else holds it".
- **`table-builder-acquire-refresh-lock`** and **`table-builder-release-refresh-lock`** — the two
  verbs, plus a `StampExecution` Pass and the two release states in the ASL.
- **`TimeoutSeconds: 3600`** on the machine, and `STALE_LOCK_SECONDS = 4500` derived from it.
- **`cpcommon.glue.update_time`** — the freshness stamp both sides of FR-005 render through.
- IAM: `s3:GetObject` + `s3:PutObject` on `${admin_bucket_arn}/locks/table-builder/*`, nothing else.

### Deliberate deviations

- **Three ASL states, not two.** ASL gives a state one `Next`, and the two release points continue
  to different terminal states. Both invoke the same verb.
- **The release states sit on paths the CREATE branch shares** and no-op for creates. A `Choice`
  guarding the insertion points would evaluate a possibly-absent `$.lock`, which raises the
  uncatchable `States.Runtime`; deciding in Python means no JSONPath ever touches a maybe-absent key.
- **`TimeoutSeconds` is an ASL field, not a resource argument.** `aws_sfn_state_machine` has none —
  `tofu validate` rejects it. FR-004 AC1's wording implied otherwise.
- **The test lives at the layer root**, not in `tbcommon/` as the spec's file tree showed:
  `deploy-lambdas.yml` copies that package wholesale into the published layer.
- **FR-008 AC4's `simulate-custom-policy` is owed, not skipped** — it needs the deployed role.
- **FR-001's CAS precedent moved.** The spec named `dqcommon.index_store` and `log_sweep`; SPEC-156
  folded both onto `cpcommon.cas` two days after this spec was authored.

## What changed from earlier specs?

- **SPEC-149's "reduced, not closed" is superseded** — marked in place in `decisions/` and
  `ARCS.md`. What it says about Glue having no compare-and-set is still true and is why the lock
  exists.
- **`apply-refresh` gained a freshness guard in front of its `UpdateTable`**, and its retry-safety
  property had to be preserved explicitly: a Lambda or Glue fault can fire *after* the update
  commits, so the retry re-reads a table whose stamp this run moved. The guard judges on the
  columns as well as the stamp, so a run is never blamed for its own write.
- **`load-table-definition`** now threads `observedUpdateTime`.
- **Two guards were under-measuring and were fixed rather than updated.**
  `test_table_builder_env.py` parsed the function map only as far as `execute-ddl`, so SPEC-152's
  `notify-failure` had been outside the cold-start guard since it landed. The state-machine tests
  pinned single hops and are now reachability walks.

## Docs sweep

- **Help & guides:** one bullet added to *When a table can't be refreshed* — one refresh at a time
  per table, a second is refused and changes nothing. That is the only user-visible surface this
  spec touches; the two new notification bodies are rendered by the existing failure path.
- **No component-inventory row.** The inventory covers `apps/portal/src/` only; there is no area
  file for the Lambda layers, and `tbcommon/table_lock.py` and `cpcommon.glue.update_time` are
  layer modules. Their homes are recorded here and in `decisions/`.

## Verification

`ruff check lambdas/`, `python3 -m pytest lambdas/` (2179 passed, coverage 96.9% against the 95
floor), `tofu -chdir=infra validate` and `fmt -check -recursive` all clean.

Three fresh-context reviews, one per phase, each followed by mutation testing to confirm the fixes
bite. They found nine defects between them, including two the author's own reasoning had argued
were impossible: the holder identifying the message rather than the execution, and the freshness
guard failing a run that had already succeeded.

**FR-008 AC4 is DISCHARGED (2026-08-09, post-apply)** against the deployed
`dat-prod-table-builder-execution-role`, each assertion with a control beside it:

| Action | Resource | Result |
|---|---|---|
| `s3:PutObject` | `…-athena-admin/locks/table-builder/alice/sales.json` | **allowed** |
| `s3:GetObject` | same | **allowed** |
| `s3:DeleteObject` | same | **explicitDeny** |
| `s3:PutObject` | `…-athena-admin/shared-spaces/x.json` | **implicitDeny** |
| `s3:GetObject` | same (the control) | **allowed** |

The last row is why the control matters: an `implicitDeny` alone reads the same whether the action
is ungranted or the ARN matched no statement at all. `GetObject` succeeding on the identical ARN
shows the resource is in the policy's space, so the write denial is real.

**Still owed — one check, and it is not optional:**

1. **FR-009 AC4, the live check.** Submit two refreshes of one table in quick succession from the
   UI. One succeeds; the other produces the `refresh_already_running` notification, and both runs
   are visible in `logs/service=table-builder/`. **Nothing that runs today proves two real
   executions serialize** — the unit tests simulate contention with a pinned read.
Expect a red first refresh in the window between `Deploy Infrastructure` and `Deploy Lambdas`: the
two new functions exist with placeholder zips until the code lands. The request is refused with a
notification, not lost, and it self-heals.
