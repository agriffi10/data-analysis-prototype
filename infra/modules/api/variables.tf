variable "project_name" {
  description = "Short name used as a prefix for AWS resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names and carried to the function as ENV_NAME."
  type        = string
}

variable "aws_region" {
  description = "Region for the HTTP API, the function and the regional custom domain."
  type        = string
}

variable "api_host" {
  description = "Hostname the API answers on, without scheme. Built at root from the domain variables and passed down — never derived here, so one place decides what the origin is."
  type        = string
}

variable "api_certificate_arn" {
  description = "Regional ACM certificate for api_host. Fed from the certificate VALIDATION resource, not the certificate itself: both carry the same ARN, but only the validation creates the edge that stops a clean rebuild attaching a PENDING_VALIDATION certificate."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone that answers for the parent domain, carrying this API's A-alias record."
  type        = string
}

variable "spa_origin" {
  description = "Origin of the container SPA, admitted by CORS. The container is where ported features are proved."
  type        = string
}

variable "logs_queue_url" {
  description = "FIFO queue the structured-logging layer writes spans to."
  type        = string
}

variable "logs_queue_arn" {
  description = "ARN of that queue, scoping the function's only non-logging grant."
  type        = string
}

variable "admin_bucket" {
  description = "Admin bucket name, carried as ADMIN_BUCKET."
  type        = string
}

variable "user_space_bucket" {
  description = "User-space bucket name, carried as USER_SPACE_BUCKET."
  type        = string
}

variable "shared_space_bucket" {
  description = "Shared-space bucket name, carried as SHARED_SPACE_BUCKET."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup name, carried as ATHENA_WORKGROUP."
  type        = string
}

# ── The provider block ────────────────────────────────────────────────────────
# Five fields, computed at root. The client secret, redirect URI and post-logout URI are
# deliberately ABSENT.
#
# EACH CARRIES A VALIDATION rather than relying on having no default: AN UNSET REPO VARIABLE
# RENDERS AS THE EMPTY STRING, which satisfies a required variable AND overrides a default,
# so "no default" guards nothing on its own. README.md.

variable "oidc_issuer" {
  description = "Exact `iss` the API requires on every token. Computed at root from the pool."
  type        = string

  validation {
    condition     = can(regex("^https://[^ ]+$", var.oidc_issuer))
    error_message = "oidc_issuer must be an https URL. An empty value means it was never computed."
  }
}

variable "oidc_audience" {
  description = "The app clients a token's `aud` may be one of: the SPA's and, while sign-in moves to it, the portal server's. Rendered comma-separated into OIDC_AUDIENCE, which the verifier parses back into a set."
  type        = list(string)

  validation {
    condition     = length(var.oidc_audience) > 0
    error_message = "oidc_audience must name at least one app client. Empty means it was never computed, and an empty set refuses every token."
  }

  validation {
    condition = alltrue([
      for client in var.oidc_audience : length(trimspace(client)) > 0 && !strcontains(client, ",")
    ])
    error_message = "Every client id in oidc_audience must be non-empty and hold no comma, which the rendering joins on."
  }
}

variable "oidc_jwks_uri" {
  description = "Where the signing keys are published. Passed in whole and treated here as opaque: Cognito happens to publish under the issuer and other providers do not, so a URL built from oidc_issuer inside this module would bake in the provider assumption the block exists to remove."
  type        = string

  validation {
    condition     = can(regex("^https://[^ ]+$", var.oidc_jwks_uri))
    error_message = "oidc_jwks_uri must be an https URL. An empty value means it was never computed."
  }
}

variable "oidc_username_claim" {
  description = "Which claim carries the username everything in this product is keyed on."
  type        = string

  validation {
    condition     = length(var.oidc_username_claim) > 0
    error_message = "oidc_username_claim must name a claim. Empty would leave every request unattributable."
  }
}

variable "oidc_required_claims" {
  description = "JSON object of claim name to the exact value a token must carry, e.g. {\"token_use\":\"id\"}. An empty object is valid for a provider asserting no such claim; an empty STRING is not, and is what an unset variable looks like."
  type        = string

  # Three layers, each measured: jsondecode alone accepts a bare scalar, tomap rejects that
  # and a list, and `keys` is what rejects the literal `null` — which tomap accepts and which
  # plans clean end to end. An empty OBJECT still passes, correctly.
  validation {
    condition     = can(keys(tomap(jsondecode(var.oidc_required_claims))))
    error_message = "oidc_required_claims must be a JSON object such as {\"token_use\":\"id\"} — not a scalar, not a list. An empty value means it was never computed, and would silently stop the token-type check from running at all."
  }
}

# ── The identity layer ────────────────────────────────────────────────────────
# Three values, NONE defaulted. A defaulted slot count silently drops every shared space a
# user is in, which presents as the propagation delay the product already documents — so
# nothing about the running system distinguishes it from correct behaviour. README.md.

variable "portal_role_arn" {
  description = "The EXISTING portal role the API assumes to act as its caller -- the role the data module creates. No new role is created: the user-space bucket policy's hand-maintained allowlist already names this one, and aws:PrincipalArn resolves an assumed-role request to the role's IAM ARN, so assuming the same role keeps that entry valid."
  type        = string
}

variable "principal_tag_key" {
  description = "The session-tag key carrying the username. Agreement with the portal role's user-space permission template is asserted by test rather than made structural: that template hard-codes the literal instead of taking this variable."
  type        = string
}

variable "max_shared_memberships" {
  description = "Number of shared-space membership slots the API stamps tags for. The same variable that sizes the Cognito custom attributes, the portal role's trust statement (its sts:TagKeys list) and its shared-space policy."
  type        = number
}

variable "shared_space_queue_url" {
  description = "URL of the shared-space FIFO request queue. This function is its only writer."
  type        = string
}

variable "notifications_queue_url" {
  description = "URL of the notifications FIFO request queue. This function is its only writer."
  type        = string
}

variable "table_build_queue_url" {
  description = "URL of the table-builder FIFO request queue. This function is its only writer."
  type        = string
}

variable "table_share_queue_url" {
  description = "URL of the table-share FIFO request queue. This function is its only writer."
  type        = string
}

variable "data_quality_queue_url" {
  description = "URL of the data-quality FIFO request queue. This function is its only writer."
  type        = string
}

variable "file_send_queue_url" {
  description = "URL of the file-send FIFO request queue. This function is its only writer."
  type        = string
}

variable "archive_queue_url" {
  description = "URL of the archive FIFO request queue. This function is its only writer."
  type        = string
}

variable "file_ops_queue_url" {
  description = "URL of the file-ops FIFO request queue. This function is its only writer."
  type        = string
}

variable "results_conversion_queue_url" {
  description = "URL of the results-conversion FIFO request queue. This function is its only writer."
  type        = string
}

variable "feedback_queue_url" {
  description = "URL of the feedback FIFO request queue. This function is its only writer, and unlike the nine above the browser never held a grant on it."
  type        = string
}

variable "request_queue_arns" {
  description = "Every FIFO request queue ARN this function may write. Exactly the ten — the nine control-plane request queues plus feedback; never a wildcard, never a DLQ, and never the notifications queue's writer path."
  type        = list(string)

  validation {
    condition     = length(var.request_queue_arns) == 10
    error_message = "The API writes exactly ten request queues — nine control planes plus feedback; a shorter list means one lost its route."
  }
}

variable "lambda_image_repository_url" {
  description = "Registry URI of the fleet's one container image, from module.lambda_image. Every function in this module runs that image and differs only by its command."
  type        = string
}

variable "lambda_image_tag" {
  description = "The commit sha this module's functions are CREATED from. Ignored after creation — CI re-points every function with update-function-code on each deploy — but it must be a tag the registry already holds, or CreateFunction fails."
  type        = string
}
