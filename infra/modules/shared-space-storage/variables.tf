variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-shared-space-create)."
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

variable "spa_origin" {
  description = "Origin serving the container SPA (https://host), allowlisted for CORS so a presigned URL minted by the API can be redeemed from it. Empty contributes no entry — compact() drops it rather than sending S3 an empty origin."
  type        = string
  default     = ""
}

variable "portal_role_name" {
  description = "Name of the shared portal role this module attaches the membership inline policy (slots + sqs:SendMessage + shared delete-denies) to, by name — mirrors how the analytics module attaches its portal policy."
  type        = string
}

variable "max_shared_memberships" {
  description = "Number of membership slots — drives the portal-role policy's ten templated S3/Glue statements scoped to the shared_space_k principal tag. Single source is the root variable of the same name."
  type        = number
  default     = 10
}

variable "control_plane_execution_role_arns" {
  description = "ARNs of the shared control-plane execution roles (table-builder / table-share / data-quality) granted DATA_LOCATION_ACCESS on the shared bucket so they can CREATE tables over shared-space prefixes. LF-Tags cover DB/table resources but not S3 locations, so the location grant is here while the `portal-managed` tag + tag-policy grants live in the analytics module. Constructed strings from root; empty keeps the module standalone-plannable."
  type        = list(string)
  default     = []
}
