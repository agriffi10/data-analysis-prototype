variable "aws_region" {
  description = "AWS region for all resources (e.g. us-east-1)"
  type        = string
}

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
  default     = "dat"
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-user-pool)."
  type        = string
  default     = "prod"
}

variable "github_repo" {
  description = "GitHub repository in owner/name format (e.g. acme/s3-upload-portal). Scopes the GitHub Actions OIDC trust policy to this repo's main branch and pull requests."
  type        = string
}

variable "state_bucket" {
  description = "Name of the S3 bucket used for OpenTofu remote state (created by the bootstrap process, not managed by this IaC)."
  type        = string
}

variable "state_lock_table" {
  description = "Name of the DynamoDB table used for OpenTofu state locking (created by the bootstrap process, not managed by this IaC)."
  type        = string
}

variable "cognito_domain_prefix" {
  description = "Hosted UI domain prefix (must be globally unique across all AWS accounts). When empty, defaults to {project_name}-{environment}-portal."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Override for the user-space (Bucket 1) S3 name. When empty, defaults to {project_name}-prod-user-space. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "portal_role_name" {
  description = "Override for the shared portal IAM role name. When empty, defaults to {project_name}-portal-user-role."
  type        = string
  default     = ""
}

variable "workgroup_name" {
  description = "Override for the shared Athena workgroup name. When empty, defaults to {project_name}-prod-portal-wg."
  type        = string
  default     = ""
}

variable "athena_admin_bucket_name" {
  description = "Override for the admin-only Athena results bucket name. When empty, defaults to {project_name}-prod-athena-admin. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "Override for the shared-space (Bucket 2) S3 name. When empty, defaults to {project_name}-prod-shared-space. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "archive_bucket_name" {
  description = "Override for the archive (Bucket 5) S3 name. When empty, defaults to {project_name}-prod-archive. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "max_shared_memberships" {
  description = "Number of shared-space membership slots per user (Cognito custom attributes custom:shared_space_1..N + Identity-Pool principal tags shared_space_1..N + portal-role policy slots). Single source for the slot count across auth/data/shared-spaces. Bounded because a Cognito Identity Pool maps each claim to exactly one single-valued principal tag; raising it enlarges the portal-role policy (see docs/architecture.md, Authorization)."
  type        = number
  default     = 10

  # An empty repo variable renders as the empty string, which is not a number — but a zero or a
  # negative one plans clean and would leave the API stamping no membership tags at all, which
  # presents as the documented propagation delay rather than as a fault.
  validation {
    condition     = var.max_shared_memberships >= 1
    error_message = "max_shared_memberships must be at least 1. Zero would stamp no membership tags, which presents as the propagation delay rather than as a failure."
  }
}

variable "principal_tag_key" {
  description = "IAM principal-tag key carrying the username. Scopes the portal role's analytics Glue/results ARNs, and bounds the portal role's API trust statement. Default 'username' — the tag the API stamps from the verified claim."
  type        = string
  default     = "username"

  # Pinned to the literal, and the validation is the point rather than the default. This key is
  # hard-coded in two of the portal role's permission templates and in the Python identity
  # layer, none of which this variable reaches — so "one variable feeds both, therefore they
  # cannot drift" is false. An empty repo variable satisfies a required variable
  # AND overrides a default, so a TF_VAR override would silently produce sessions whose tags
  # match no policy statement: AccessDenied on every API path, the browser path still working,
  # and nothing naming the cause. Refuse it at plan instead. Changing this key means threading it
  # through those three sites first, and this line is the reminder.
  validation {
    condition     = var.principal_tag_key == "username"
    error_message = "principal_tag_key must be \"username\" while the portal-role permission templates hard-code it. Thread the variable through those first, then change this."
  }
}

# NOTE: the post-confirmation Lambda exec role ARN that module.analytics
# adds as a Lake Formation admin is now sourced directly from module.auth's output
# (see main.tf), so the former root `lambda_provisioner_role_arn` variable was
# removed. The analytics module keeps its own optional variable (default "") so it
# still plans standalone before auth exists.

variable "verification_principal_arns" {
  description = "IAM principals allowed to assume the read-only verification role (catalog read-backs + the archive audit record). Set as the TF_VAR_verification_principal_arns repo variable and applied by deploy-infra.yml — NOT in a local terraform.tfvars, which would require a local apply, and no human identity here can apply locally without tofu proposing to destroy the data buckets it cannot read. Empty (the default) means the role is not created at all; the CloudTrail trail ships either way, since it needs no principal."
  type        = list(string)
  default     = []
}

variable "vpc_cidr" {
  description = "CIDR block for the container platform's VPC. Split into two /20 public and two /20 private subnets, one pair per availability zone. The private ones have no default route: outbound reaches AWS through VPC endpoints and nothing else (infra/modules/network)."
  type        = string
  default     = "10.0.0.0/16"
}

variable "parent_domain" {
  description = "Registrable domain whose subdomains serve the SPA and the API (e.g. example.com). An environment fact, never a literal in a .tf file. Set as the TF_VAR_parent_domain repo variable and applied by deploy-infra.yml. NO DEFAULT ON PURPOSE."
  type        = string

  # An absent env var fails at plan on its own; an env var set to the EMPTY STRING does not
  # — it satisfies the variable and plans clean. An unset GitHub repo variable renders as
  # exactly that empty string, so the missing default guards nothing without this block and
  # the failure lands at apply instead, where ACM rejects a certificate for a bare "portal.".
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\\.[a-z][a-z0-9-]+$", var.parent_domain))
    error_message = "parent_domain must be a lowercase registrable domain such as example.com — with a non-numeric final label, no trailing dot, and no scheme or path. An empty value means the repo variable is unset."
  }
}

variable "route53_zone_id" {
  description = "Hosted zone ID for parent_domain, serving both the ACM validation records and the alias records. Set as the TF_VAR_route53_zone_id repo variable. NO DEFAULT ON PURPOSE."
  type        = string

  # Two failures this shape catches, both of which otherwise validate clean and fail late.
  # The empty string, as above. And the "/hostedzone/Z…" form the API returns: it names the
  # right zone and reads correct, but it is also rendered into the deploy role's Route 53
  # grant, where IAM matches ARNs case- and character-sensitively — so the prefixed form
  # yields a grant matching nothing, and every record write is denied for a reason the value
  # does not look like it could cause.
  validation {
    condition     = can(regex("^Z[A-Z0-9]+$", var.route53_zone_id))
    error_message = "route53_zone_id must be a bare uppercase hosted zone ID (Z…) — strip the /hostedzone/ prefix the Route 53 API returns. An empty value means the repo variable is unset."
  }
}

variable "spa_subdomain" {
  description = "Label under parent_domain serving the container SPA, giving the host {spa_subdomain}.{parent_domain}."
  type        = string
  default     = "portal"

  # The default does NOT survive an empty env var: TF_VAR_spa_subdomain="" overrides it and
  # yields the host ".example.com", which is plausible enough to reach ACM and be rejected
  # there. deploy-infra.yml falls back with || so an unset repo variable never arrives empty;
  # this block is what catches the fallback being dropped in a later edit.
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", var.spa_subdomain))
    error_message = "spa_subdomain must be a single lowercase DNS label such as portal — not a dotted name, and not empty."
  }
}

variable "api_subdomain" {
  description = "Label under parent_domain serving the HTTP API, giving the host {api_subdomain}.{parent_domain}."
  type        = string
  default     = "api"

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", var.api_subdomain))
    error_message = "api_subdomain must be a single lowercase DNS label such as api — not a dotted name, and not empty."
  }
}

variable "spa_desired_count" {
  description = "Tasks the SPA service runs. Zero by default, so the very first apply can create a service before any image exists; a running deployment sets it to 1 or more, and the image pipeline REFUSES to report success at zero, where waiting for stability proves nothing. Set as the TF_VAR_spa_desired_count repo variable — deploy-infra.yml falls back to 0 so an unset variable never arrives as the empty string."
  type        = number
  default     = 0

  validation {
    condition     = var.spa_desired_count >= 0 && floor(var.spa_desired_count) == var.spa_desired_count
    error_message = "spa_desired_count must be a whole number of tasks, zero or more."
  }
}

variable "spa_image_tag" {
  description = "Tag of the SPA image the task definition references. The registry is IMMUTABLE — there is no :latest and no tag that can be re-pushed after a bad build — so this is the commit sha of the image CI pushed. The default exists only so the very first apply can create a task definition before any image does; CI has owned the running revision since the image pipeline landed, so this value no longer describes what runs. Set as the TF_VAR_spa_image_tag repo variable."
  type        = string
  default     = "placeholder"

  validation {
    condition     = can(regex("^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$", var.spa_image_tag))
    error_message = "spa_image_tag must be a valid ECR tag: it starts with a letter, digit or underscore, continues with those plus dot and hyphen, and is at most 128 characters. ECR refuses a leading dot or hyphen, and an empty value means the repo variable is unset."
  }
}

variable "max_upload_bytes" {
  description = "Largest single upload the portal offers, carried to the container as the runtime document's maxUploadBytes. Supplied from the SAME VITE_MAX_UPLOAD_BYTES repo variable deploy-app.yml renders the CloudFront document from — one source, because two renderers of one document that read different variables disagree with no symptom on either screen. The default is the fallback for an unset variable, matching the workflow's."
  type        = number
  default     = 5368709120

  validation {
    condition     = var.max_upload_bytes > 0 && floor(var.max_upload_bytes) == var.max_upload_bytes
    error_message = "max_upload_bytes must be a whole number of bytes greater than zero."
  }
}
