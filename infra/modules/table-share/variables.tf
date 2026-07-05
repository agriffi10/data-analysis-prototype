# ── table-share module variables (SPEC-088) ──────────────────────────────────
# Bounded-context module for the "share a table across databases" control plane: a
# DEDICATED FIFO SQS → EventBridge Pipe → Step Function pipeline that orchestrates
# five single-task verb Lambdas (validate-authorize → inspect-source → Map(recipients):
# check-target-absent → copy-objects → create-table) on ONE shared execution role.
# Mirrors the table-builder control plane PATTERN (not its resources); decision
# record: docs/table-share-architecture.md.
#
# SPEC-088 is FOUNDATION ONLY — plumbing + Lambda stubs, no request contract and no
# action semantics (those land in SPEC-089→092). Cross-module ARNs are CONSTRUCTED
# STRINGS (passed from root locals), never another module's output, so they are known
# at plan time (architecture.md "unknown ARN in list" trap) and this module plans
# standalone.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-table-share-copy-objects)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Pipes / Step Functions / Lambda / log-group ARNs in the module's policies."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the shared execution role's log-group ARNs and the constructed function ARNs."
  type        = string
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries)."
  type        = number
  default     = 3
}

# ── SPEC-089: request contract + validate-authorize ──────────────────────────

variable "portal_role_name" {
  description = "SPEC-089: name of the shared portal role (SPEC-011) this module attaches the browser's sqs:SendMessage (table-share queue only) inline policy to, by name — mirrors the table-builder/notifications modules."
  type        = string
}

variable "user_pool_id" {
  description = "SPEC-089: Cognito User Pool ID — passed to validate-authorize (env COGNITO_USER_POOL_ID) for offline ID-token verification, and used to build the pool ARN scoping the execution role's recipient-existence checks (AdminGetUser/ListUsers)."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "SPEC-089: Cognito SPA app client ID — the ID-token audience validate-authorize checks (env COGNITO_APP_CLIENT_ID)."
  type        = string
  default     = ""
}

variable "admin_bucket_name" {
  description = "SPEC-089: name of the existing analytics admin bucket (SPEC-032). The shared-spaces registry read for source authorization + recipient-space existence lives here. No bucket is created here."
  type        = string
  default     = ""
}

# ── SPEC-090: source resolution + copy plan ───────────────────────────────────

variable "user_space_bucket_name" {
  description = "SPEC-090: name of the user-space bucket (Bucket 1, SPEC-013). A personal source table's LOCATION resolves here; inspect-source lists it and the copy verbs read/write it (SPEC-091). No bucket is created here."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "SPEC-090: name of the shared-space bucket (Bucket 2, SPEC-050). A shared source/recipient's LOCATION resolves here; inspect-source lists it and the copy verbs read/write it (SPEC-091). No bucket is created here."
  type        = string
  default     = ""
}

# ── SPEC-092: recipient table creation (create-table) ─────────────────────────

variable "athena_workgroup" {
  description = "SPEC-092: name of the shared analytics workgroup (SPEC-032) create-table runs the recipient CREATE EXTERNAL TABLE in — the same LF-enforced path the table-builder and app queries use. Scopes the execution role's athena:* grant and feeds the verbs' ATHENA_WORKGROUP env."
  type        = string
  default     = ""
}
