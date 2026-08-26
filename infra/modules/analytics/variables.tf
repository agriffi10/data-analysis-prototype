# ── analytics module variables ────────────────────────────────────
# Final resource names are computed in the root module (like user_space_bucket_name)
# and passed in, so naming lives in one place and base's deploy policy can be scoped
# to the same ARNs without a dependency cycle.

variable "workgroup_name" {
  description = "Name of the shared Athena workgroup all users query through (computed by the root module; default {project_name}-prod-portal-wg)."
  type        = string
}

variable "athena_admin_bucket_name" {
  description = "Name of the admin-only Athena results bucket — the workgroup's default/fallback output and future admin/audit store. No end-user access (computed by the root module; default {project_name}-prod-athena-admin)."
  type        = string
}

variable "admin_results_retention_days" {
  description = "Lifecycle expiry (days) for objects in the admin-only results bucket. Distinct from the user-facing {username}/athenaresults/ prefix, which is retained indefinitely by decision."
  type        = number
  default     = 30
}

variable "alb_access_log_prefix" {
  description = "Prefix in this bucket the SPA load balancer writes access logs under, without a trailing slash. Decided at root and passed to both this module and the one that points the balancer at it, so the expiry and the destination cannot disagree."
  type        = string
}

variable "alb_access_log_retention_days" {
  description = "Lifecycle expiry (days) for the SPA load balancer's access logs under alb-access-logs/. Its own knob rather than admin_results_retention_days: those objects are execution-scoped control-plane scratch read minutes after they are written, and these are the only record of a request that never reached a task."
  type        = number
  default     = 90
}

variable "query_scan_cutoff_bytes" {
  description = "Per-query data-scanned guardrail (bytes) on the workgroup. Default 10 GiB — a cost ceiling, not a correctness control; tune as needed."
  type        = number
  default     = 10737418240 # 10 GiB
}

# ── Phase 2: Lake Formation + portal-role policy inputs ──────────────────────

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (the LF registration role)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the Athena workgroup and Glue catalog ARNs in the portal-role policy."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the Glue catalog/database/table ARNs in the portal-role policy."
  type        = string
}

variable "user_space_bucket_arn" {
  description = "ARN of the user-space bucket. Registered as the LF location and scoped in the portal role's athenaresults/ results statements."
  type        = string
}

variable "portal_role_name" {
  description = "Name of the shared portal IAM role the analytics permission policy is attached to."
  type        = string
}

variable "portal_role_arn" {
  description = "ARN of the shared portal IAM role — the principal granted DATA_LOCATION_ACCESS on the registered user-space location."
  type        = string
}

variable "principal_tag_key" {
  description = "IAM principal-tag key carrying the username. Scopes the portal role's Glue database/table and athenaresults/ ARNs. Default 'username'."
  type        = string
  default     = "username"
}

variable "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role — added as a Lake Formation data-lake admin so the IaC can grant/revoke and register locations."
  type        = string
}

variable "lambda_provisioner_role_arn" {
  description = "ARN of the post-confirmation Lambda execution role, added as a Lake Formation admin so it can issue per-database grants. Optional — empty until the auth module fills it (compact() drops it), keeping this module deployable standalone."
  type        = string
  default     = ""
}

variable "shared_space_orchestrator_role_arn" {
  description = "ARN of the shared-space orchestrator role, added as a Lake Formation admin so it can GrantPermissions on shared DBs + DATA_LOCATION_ACCESS on the shared location. Constructed string from root (known at plan time → compact()-safe); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "table_builder_execution_role_arn" {
  description = "ARN of the table-builder shared execution role (all five verbs run under it), added as a Lake Formation admin so check-table-absent can Describe and execute-ddl can CREATE tables in the dynamic per-user + per-shared-space target databases (they can't be enumerated in static Terraform). Constructed string from root (known at plan time → compact()-safe); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "table_share_execution_role_arn" {
  description = "ARN of the table-share shared execution role (all five verbs run under it), added as a Lake Formation admin so check-target-absent can Describe and create-table can CREATE tables in the dynamic recipient databases (per-user + per-shared-space — not enumerable in static Terraform), and so inspect-source can read LF-gated source tables. Constructed string from root (known at plan time → compact()-safe); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "data_quality_execution_role_arn" {
  description = "ARN of the data-quality shared execution role (all nine verbs run under it), added as a Lake Formation admin so create-temp-tables can CREATE and drop-temp-tables can DELETE the throwaway dq_tmp_* external tables in the dynamic target databases (the actor's own for a personal check, the shared space's for a shared one — not enumerable in static Terraform). Constructed string from root (known at plan time → compact()-safe); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "verification_role_arn" {
  description = "ARN of the read-only verification role (modules/verification), granted DESCRIBE via the portal-managed LF-Tag so an owed catalog read-back (the Description/comment preservation, the foreign projection fixture) can finally be made. DESCRIBE ONLY and never DATA_LOCATION_ACCESS — it reads definitions, never data. Constructed string from root (known at plan time → compact()-safe); empty keeps this module standalone."
  type        = string
  default     = ""
}
