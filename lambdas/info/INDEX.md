# Lambdas — index by control plane

Every function under `lambdas/`, grouped by the control plane it belongs to. This is a **lookup**:
find the verb, open the one directory. It is not a description of how a plane works — that is the
plane's own page under [`planes/`](planes/), which carries the state graph, the layer split and the
traps.

The directory layout is **flat and prefixed** (`file-ops-copy-objects/`, not `file-ops/copy-objects/`)
because each verb is packaged and deployed as its own function; the prefix is the only grouping the
filesystem has, and this index is the only place that grouping is written down.

**Every plane has the same shape** — FIFO SQS → EventBridge Pipe → Step Functions → single-task verb
Lambdas, one execution role per plane, and its own DLQ. Shared code comes from the fleet's one
container image; the `cpcommon`-plus-domain split is a code boundary, not a packaging one.
Read [`planes/`](planes/) for the one you are changing; the shared pattern and the fences that apply
to all of them are in [`infra/info/control-plane-shape.md`](../../infra/info/control-plane-shape.md) and the Fences that open
[`docs/decisions/control-planes.md`](../../docs/decisions/control-planes.md).

## Where the code is

| | Path | Holds |
|---|---|---|
| Verb Lambdas | `lambdas/<plane>-<verb>/` | one handler, its tests, and nothing else |
| Shared layer | `lambdas/control-plane-common/cpcommon/` | the algorithms every plane runs — auth, CAS, locks, transfer, errors, observability. Its module map and long-form reasoning: [`shared-layer.md`](shared-layer.md) |
| Domain layers | `lambdas/<plane>-common/` | that plane's tables, wording and domain rules |
| API | `lambdas/api/` | the HTTP API's router, routes and `apicommon` |

How code reaches any of them: [`deployment.md`](deployment.md).

`cpcommon` owns the **algorithm**; a domain layer owns its **wording**. Do not merge the domain
layers, and do not import one from another. They were once packaged and attached separately, so an
import across them silently merged two layers; **one image made that separation a code decision
rather than a packaging one**, and it stands on its own terms. What the image makes live is the
reverse hazard — one task root, where a duplicate top-level name wins fleet-wide. Rules: [`best-practices/lambdas/lambdas.md`](best-practices/lambdas/lambdas.md).

## Control planes

### API

Orchestration, layer and traps: [`planes/api.md`](planes/api.md). Domain layer: `api/apicommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `api/` | `handler.py` | Entry point for the portal API: one span per request, and a name on the wire for every fault. |

### Shared spaces

Orchestration, layer and traps: [`planes/shared-spaces.md`](planes/shared-spaces.md). Domain layer: `shared-space-common/`.

| Lambda | Handler | What it does |
|---|---|---|
| `shared-space-acknowledge-membership/` | `acknowledge_membership.py` | acknowledge-membership verb: a member confirms they have picked up the space. |
| `shared-space-backfill-ever-active/` | `backfill_ever_active.py` | one-shot, not a verb: stamps the durable ever-active fact on records that predate it. Invoked from its own workflow. |
| `shared-space-add-members/` | `add_members.py` | add-members verb: adds each valid username to the space. |
| `shared-space-create/` | `create_space.py` | create-space verb: provisions a new shared space owned by the actor. |
| `shared-space-delete/` | `delete_space.py` | delete-space verb: the owner ends everyone's access, and destroys the space only if it was never usable. |
| `shared-space-forget/` | `forget_space.py` | forget verb: a durable "clear this entry from my list"; tears down only a space that was never usable. |
| `shared-space-leave/` | `leave.py` | leave verb: a member revokes only their own access. |
| `shared-space-notify-failure/` | `ss_notify_failure.py` | shared-space notify-failure — the terminal failure notification of last resort. |
| `shared-space-remove-members/` | `remove_members.py` | remove-members verb: removes each member from the space. |
| `shared-space-transfer-ownership/` | `transfer_ownership.py` | transfer-ownership verb: the owner hands the space to an existing member and stays on as one. |
| `shared-space-transfer-reader/` | `transfer_reader.py` | not a verb and not on the orchestrator role: a scheduled reader that turns an operator's CSV into requests on this plane's own queue. |
| `shared-space-validate/` | `validate.py` | validate-authorize — the Step Function's first task, run once before any verb. |

### Table builder

Orchestration, layer and traps: [`planes/table-builder.md`](planes/table-builder.md). Domain layer: `table-builder-common/tbcommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `table-builder-acquire-refresh-lock/` | `acquire_refresh_lock.py` | acquire-refresh-lock — the refresh branch's first task, and the serialization Glue lacks. |
| `table-builder-apply-refresh/` | `apply_refresh.py` | apply-refresh — the refresh branch's terminal task. |
| `table-builder-check-table-absent/` | `check_table_absent.py` | check-table-absent — the table-builder Step Function's second task. |
| `table-builder-diff-schema/` | `diff_schema.py` | diff-schema — the refresh branch's classifier. |
| `table-builder-execute-ddl/` | `execute_ddl.py` | execute-ddl — the table-builder Step Function's fifth and final task. |
| `table-builder-infer-schema/` | `infer_schema.py` | infer-schema — the table-builder Step Function's fourth task. |
| `table-builder-inspect-source/` | `inspect_source.py` | inspect-source — the table-builder Step Function's third task. |
| `table-builder-load-table-definition/` | `load_table_definition.py` | load-table-definition — the refresh branch's entry task. |
| `table-builder-notify-failure/` | `tb_notify_failure.py` | table-builder notify-failure — the terminal failure notification of last resort. |
| `table-builder-release-refresh-lock/` | `release_refresh_lock.py` | release-refresh-lock — the counterpart that runs on EVERY terminal path, create included. |
| `table-builder-validate-authorize/` | `validate_authorize.py` | validate-authorize — the table-builder Step Function's first task. |

### Table share

Orchestration, layer and traps: [`planes/table-share.md`](planes/table-share.md). Domain layer: `table-share-common/tscommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `table-share-build-transfer-manifest/` | `table_share_build_transfer_manifest.py` | build-transfer-manifest — the Distributed Map's dataset. |
| `table-share-check-target-absent/` | `table_share_check_target_absent.py` | check-target-absent — the recipient Map's conflict guard. |
| `table-share-collect-transfer-results/` | `table_share_collect_transfer_results.py` | collect-transfer-results — turns a Map Run's export back into per-recipient outcomes. |
| `table-share-copy-objects/` | `table_share_copy_objects.py` | copy-objects — the Distributed Map's batch copier. |
| `table-share-create-table/` | `table_share_create_table.py` | create-table — the recipient Map's final verb. |
| `table-share-inspect-source/` | `table_share_inspect_source.py` | inspect-source — resolves the source table into a copy plan. |
| `table-share-notify-failure/` | `ts_notify_failure.py` | table-share notify-failure — the terminal failure notification of last resort. |
| `table-share-validate-authorize/` | `table_share_validate_authorize.py` | validate-authorize — the table-share Step Function's first task. |

### Data quality

Orchestration, layer and traps: [`planes/data-quality.md`](planes/data-quality.md). Domain layer: `data-quality-common/dqcommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `data-quality-assemble-report/` | `dq_assemble_report.py` | data-quality assemble-report — joins everything into the report. |
| `data-quality-byte-scan/` | `dq_byte_scan.py` | data-quality byte-scan — the one check a SQL engine cannot do. |
| `data-quality-check-query/` | `dq_check_query.py` | data-quality check-query — one describe per query, with no waiting. |
| `data-quality-create-temp-tables/` | `dq_create_temp_tables.py` | data-quality create-temp-tables — builds the throwaway tables Athena profiles through. |
| `data-quality-drop-temp-tables/` | `dq_drop_temp_tables.py` | data-quality drop-temp-tables — cleanup, reached on every path. |
| `data-quality-inspect-source/` | `dq_inspect_source.py` | data-quality inspect-source — the control plane's second verb. |
| `data-quality-notify-failure/` | `dq_notify_failure.py` | data-quality notify-failure — the terminal failure notification of last resort. |
| `data-quality-start-profile-query/` | `dq_start_profile_query.py` | data-quality start-profile-query — submits the three checks and waits for none of them. |
| `data-quality-validate-authorize/` | `dq_validate_authorize.py` | data-quality validate-authorize — the control plane's security boundary. |

### File send

Orchestration, layer and traps: [`planes/file-send.md`](planes/file-send.md). Domain layer: `file-send-common/fscommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `file-send-build-transfer-manifest/` | `file_send_build_transfer_manifest.py` | build-transfer-manifest — the Distributed Map's dataset. |
| `file-send-check-target-absent/` | `file_send_check_target_absent.py` | check-target-absent — the per-recipient conflict guard. |
| `file-send-collect-transfer-results/` | `file_send_collect_transfer_results.py` | collect-transfer-results — turns a Map Run's export back into per-recipient outcomes. |
| `file-send-copy-objects/` | `file_send_copy_objects.py` | copy-objects — the Distributed Map's batch copier. |
| `file-send-inspect-source/` | `file_send_inspect_source.py` | inspect-source — resolves the validated selection into a copy plan. |
| `file-send-notify/` | `file_send_notify.py` | notify — the plane's only outcome producer. |
| `file-send-notify-failure/` | `fs_notify_failure.py` | file-send notify-failure — the terminal failure notification of last resort. |
| `file-send-validate-authorize/` | `file_send_validate_authorize.py` | validate-authorize — the file-send Step Function's first task. |

### Archive

Orchestration, layer and traps: [`planes/archive.md`](planes/archive.md). Domain layer: `archive-common/arcommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `archive-build-restore-manifest/` | `archive_build_restore_manifest.py` | build-restore-manifest — the dataset BOTH of the restore's Distributed Maps read. |
| `archive-build-transfer-manifest/` | `archive_build_transfer_manifest.py` | build-transfer-manifest — the Distributed Map's dataset. |
| `archive-check-destination-clear/` | `archive_check_destination_clear.py` | check-destination-clear — the absolute collision guard, and the last state before a bill. |
| `archive-collect-transfer-results/` | `archive_collect_transfer_results.py` | collect-transfer-results — the commit gate's verdict, and the only place it is decided. |
| `archive-copy-objects/` | `archive_copy_objects.py` | copy-objects — the Distributed Map's batch copier. |
| `archive-delete-archived/` | `archive_delete_archived.py` | delete-archived — the vault swept after a restore, and the one deletion that may fail quietly. |
| `archive-delete-source/` | `archive_delete_source.py` | delete-source — the only verb in this portal that deletes a user's data. |
| `archive-initiate-restore/` | `archive_initiate_restore.py` | initiate-restore — the Distributed Map child that asks Glacier for the bytes back. |
| `archive-inspect-archive/` | `archive_inspect_archive.py` | inspect-archive — what a restore would write back, and where. |
| `archive-inspect-source/` | `archive_inspect_source.py` | inspect-source — resolves the validated selection into the copy plan. |
| `archive-notify/` | `archive_notify.py` | notify — the plane's only SUCCESS producer, for both of its modes. |
| `archive-notify-failure/` | `ar_notify_failure.py` | archive notify-failure — the terminal failure notification of last resort. |
| `archive-poll-restore/` | `archive_poll_restore.py` | poll-restore — the only wait loop in this repo, and the one thing GLACIER makes unavoidable. |
| `archive-rollback/` | `archive_rollback.py` | rollback — removes a partial archive copy, then fails the run. |
| `archive-update-receipt/` | `archive_update_receipt.py` | update-receipt — the archive's receipt, rewritten to say what the restore did. |
| `archive-validate-authorize/` | `archive_validate_authorize.py` | validate-authorize — the archive Step Function's first task, for BOTH of its modes. |
| `archive-write-manifest/` | `archive_write_manifest.py` | write-manifest — the integrity record, written before anything is deleted. |
| `archive-write-receipt/` | `archive_write_receipt.py` | write-receipt — the last state, and the only artifact of an archive the user can see. |

### File operations

Orchestration, layer and traps: [`planes/file-ops.md`](planes/file-ops.md). Domain layer: `file-ops-common/focommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `file-ops-acquire-lock/` | `file_ops_acquire_lock.py` | acquire-lock — claims the space (or spaces) this request operates on. |
| `file-ops-build-transfer-manifest/` | `file_ops_build_transfer_manifest.py` | build-transfer-manifest — the Distributed Map's dataset, and the last gate before bytes move. |
| `file-ops-check-destinations/` | `file_ops_check_destinations.py` | check-destinations — the per-item conflict guard, and the last state before anything is written. |
| `file-ops-collect-transfer-results/` | `file_ops_collect_transfer_results.py` | collect-transfer-results — turns a Map Run's export back into per-item outcomes and one gate. |
| `file-ops-copy-objects/` | `file_ops_copy_objects.py` | copy-objects — the Distributed Map's batch copier. |
| `file-ops-delete-source/` | `file_ops_delete_source.py` | delete-source — the only verb in this plane that removes a user's own files. |
| `file-ops-finalise-outcomes/` | `file_ops_finalise_outcomes.py` | finalise-outcomes — the state where a gate verdict becomes a statement about the user's data. |
| `file-ops-inspect-source/` | `file_ops_inspect_source.py` | inspect-source — resolves the validated selection into the copy plan. |
| `file-ops-notify/` | `file_ops_notify.py` | notify — the plane's only outcome producer, and the last state before ``Succeeded``. |
| `file-ops-notify-failure/` | `fo_notify_failure.py` | file-ops notify-failure — the terminal failure notification of last resort. |
| `file-ops-release-lock/` | `file_ops_release_lock.py` | release-lock — frees every space this request held. |
| `file-ops-validate-authorize/` | `file_ops_validate_authorize.py` | validate-authorize — the file-operations Step Function's first task. |

### Results conversion

Orchestration, layer and traps: [`planes/results-conversion.md`](planes/results-conversion.md). Domain layer: `results-conversion-common/rccommon/`.

| Lambda | Handler | What it does |
|---|---|---|
| `results-conversion-convert/` | `rc_convert.py` | convert — the typed read, the three writers, and the only write on this plane. |
| `results-conversion-describe-results/` | `rc_describe_results.py` | describe-results — the result set's columns, types and size, and the cap. |
| `results-conversion-notify/` | `rc_notify.py` | notify — the plane's one success message and its link to the folder. |
| `results-conversion-notify-failure/` | `rc_notify_failure.py` | results-conversion notify-failure — the terminal failure notification of last resort. |
| `results-conversion-validate-authorize/` | `rc_validate_authorize.py` | validate-authorize — the results-conversion Step Function's first task. |

## Standalone functions

Not part of a control plane: no Step Function, no request queue, no domain layer. Each is triggered
directly — by Cognito, by a schedule, or by its own queue. Triggers and traps:
[`planes/standalone.md`](planes/standalone.md).

| Lambda | Handler | What it does |
|---|---|---|
| `control-plane-dlq-drain/` | `dlq_drain.py` | Drains every control plane's request DLQ into the notification the user already reads. |
| `log-sweep/` | `log_sweep.py` | Sweeps the structured-logging queue into one NDJSON object per service per day. |
| `notifications-writer/` | `notifications_writer.py` | The notifications queue's single writer — the only thing that appends to a user's feed. |
| `feedback-writer/` | `feedback_writer.py` | The feedback queue's single writer — appends one submission to that day's document under compare-and-swap. Refuses to overwrite a document it cannot parse. |
| `post-confirmation/` | `post_confirmation.py` | Cognito post-confirmation trigger: provisions the new user's Glue database and prefix. |
| `pre-signup/` | `pre_signup.py` | Cognito pre-signup trigger: username validation and a disposable-email blocklist. |
| `user-directory-build/` | `build_directory.py` | Publishes the username directory: every personal workspace on the user-space bucket. |
## Shared code

The eight `*-common/` directories are what `lambdas/docker/assemble.py` copies onto `/opt/python`,
so every function can import all of them and the *plane* column says who each one is **for**, not
who can reach it. `data-quality-polars/` is the odd one out and is named in `assemble.NOT_SHARED`:
it holds a requirements file and no importable module of ours.

| Source | Package | Written for |
|---|---|---|
| `control-plane-common/` | `cpcommon` | every control-plane verb, and the API |
| `archive-common/` | `arcommon` | the archive plane |
| `data-quality-common/` | `dqcommon` | the data-quality plane |
| `data-quality-polars/` | *(pip only)* | the data-quality verbs that read bytes — polars, installed into the image from `requirements.txt`, no source of ours |
| `file-ops-common/` | `focommon` | the file-operations plane |
| `file-send-common/` | `fscommon` | the file-send plane |
| `shared-space-common/` | *(top-level modules)* | the shared-spaces plane |
| `table-builder-common/` | `tbcommon` | the table-builder plane |
| `table-share-common/` | `tscommon` | the table-share plane |

## Adding a verb

1. Create `lambdas/<plane>-<verb>/` with one handler module and its test file.
2. Add the state to that plane's `infra/modules/<plane>/state-machine.asl.json.tftpl`, and the
   function to its `lambda.tf` — see [`infra/info/INDEX.md`](../../infra/info/INDEX.md).
3. Add it to the deploy role — [`deployment.md`](deployment.md) → *Adding a
   function*, which is the one recipe for getting code onto a function.
4. Add a row to this index, and to the plane's page under [`planes/`](planes/) if the verb changes
   the flow rather than extending it.
5. Docstrings are mandatory and inline comments are forbidden — the standard is
   [`best-practices/python/python.md`](best-practices/python/python.md) §14.
