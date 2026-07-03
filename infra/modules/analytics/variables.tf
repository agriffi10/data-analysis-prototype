# ── analytics module variables (SPEC-032) ────────────────────────────────────
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
  description = "Lifecycle expiry (days) for objects in the admin-only results bucket. Distinct from the user-facing {username}/athenaresults/ prefix, which is retained indefinitely (SPEC-032 Open Questions)."
  type        = number
  default     = 30
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
  description = "ARN of the user-space bucket (SPEC-010). Registered as the LF location and scoped in the portal role's athenaresults/ results statements."
  type        = string
}

variable "portal_role_name" {
  description = "Name of the shared portal IAM role (SPEC-011) the analytics permission policy is attached to."
  type        = string
}

variable "portal_role_arn" {
  description = "ARN of the shared portal IAM role — the principal granted DATA_LOCATION_ACCESS on the registered user-space location."
  type        = string
}

variable "principal_tag_key" {
  description = "IAM principal-tag key carrying the username (SPEC-011). Scopes the portal role's Glue database/table and athenaresults/ ARNs. Default 'username'."
  type        = string
  default     = "username"
}

variable "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role — added as a Lake Formation data-lake admin so the IaC can grant/revoke and register locations."
  type        = string
}

variable "lambda_provisioner_role_arn" {
  description = "ARN of the SPEC-033 post-confirmation Lambda execution role, added as a Lake Formation admin so it can issue per-database grants. Optional — empty until SPEC-033 fills it (compact() drops it), keeping this module deployable standalone."
  type        = string
  default     = ""
}

variable "shared_space_orchestrator_role_arn" {
  description = "SPEC-056: ARN of the shared-space orchestrator role (SPEC-050), added as a Lake Formation admin so it can GrantPermissions on shared DBs + DATA_LOCATION_ACCESS on the shared location. Constructed string from root (known at plan time → compact()-safe); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "table_builder_execution_role_arn" {
  description = "SPEC-070: ARN of the table-builder shared execution role (all five verbs run under it), added as a Lake Formation admin so check-table-absent can Describe and execute-ddl can CREATE tables in the dynamic per-user + per-shared-space target databases (they can't be enumerated in static Terraform). Constructed string from root (known at plan time → compact()-safe); empty keeps this module standalone."
  type        = string
  default     = ""
}
