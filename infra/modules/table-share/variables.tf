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
