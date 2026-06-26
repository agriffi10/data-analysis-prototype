# ── shared-spaces module variables (SPEC-050) ────────────────────────────────
# Bounded-context module for Bucket 2 (the shared-space bucket) and the async
# provisioning control plane (SQS → EventBridge Pipe → Step Function → Lambda).
# Resource names are computed in the root module (like the user-space / admin
# buckets) and passed in, so naming lives in one place and base's deploy policy
# can be scoped to the same ARNs without a dependency cycle.
#
# SPEC-050 is FOUNDATION ONLY — the plumbing, no access model and no action
# semantics. Cross-module ARNs are CONSTRUCTED STRINGS (passed from root locals),
# never another module's output, so they are known at plan time (architecture.md
# "unknown ARN in list" trap) and this module plans standalone.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-shared-space-provisioner)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Pipes / Step Functions / Lambda / Glue / log-group ARNs in the orchestrator and deploy-time policies."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the orchestrator role's Glue catalog/database/table, Cognito User Pool, Lambda, and log-group ARNs."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Computed by the root module (default {project_name}-prod-shared-space). Globally unique."
  type        = string
}

variable "athena_admin_bucket_name" {
  description = "Name of the existing analytics admin bucket (SPEC-032). The registry lives under its shared-spaces/ prefix; the orchestrator role is scoped to that prefix only. No new bucket is created here."
  type        = string
}

variable "app_url" {
  description = "Public URL of the deployed app. Added to the shared-space bucket CORS allowed-origins alongside local dev; empty = localhost only."
  type        = string
  default     = ""
}
