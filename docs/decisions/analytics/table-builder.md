---
type: Decision
title: "Table Builder (SPEC-066→072)"
description: "Table Builder is a dedicated async plane on one execution role: partition keys are user-declared and served by projection, never auto-detected or loaded with `MSCK`, and CSV columns are all-string rather than inferred."
---

"Create a Glue/Athena table from a folder of files" via a **dedicated** async control plane (its own FIFO SQS → EventBridge Pipe → **linear** Step Function → five single-task verb Lambdas `validate-authorize → check-table-absent → inspect-source → infer-schema → execute-ddl`) sharing **one execution role** (all five verbs; consolidated from the SPEC-066 per-verb roles — user decision, mirroring shared-spaces) + `tbcommon` and polars, which were CI-built **layers** until SPEC-213 and now come from the fleet's one container image. **Partitions:** keys are **user-declared in the modal in granularity order** (Hive `key=value/`, never auto-detected), exposed via **Athena partition projection** (no `MSCK REPAIR`); per-key type+range collected in the modal. **CSV is not type-inferred** (all-string, OpenCSVSerde); Parquet/JSON infer + parse dates. **The shared execution role creates tables via the `portal-managed` LF-Tag (TBAC), NOT via LF-admin status** (SPEC-070/111 correction — LF *admin* alone does NOT grant CREATE_TABLE; target DBs are dynamic per-user/per-shared-space so are tagged at provision time and the role is granted on the tag + a static per-bucket DATA_LOCATION_ACCESS; see the Control-plane TBAC decision below; IAM otherwise scoped, delete denied). Any **unexpected (non-Terminal/non-Transient) verb error notifies the actor** via `tbcommon.notify.notifies_on_failure` (no more silent failures); SFN terminal states record `{…, status: created|failed, reason}` (the outcome SPEC-072 notifies from). Decision record: `lambdas/info/planes/table-builder.md`. Do NOT build MSCK-based partition loading or auto-detect partition keys.

## History

### 2026-06-27

- **Settled:** SPEC-066→072.
