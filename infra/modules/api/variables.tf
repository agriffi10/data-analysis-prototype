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

variable "app_url" {
  description = "Origin of the CloudFront-served portal, admitted by CORS beside spa_origin for as long as it is the rollback. Empty until the first CloudFront deploy, and omitted from the list when empty — the same ternary the Cognito callback list and both bucket CORS rules already use. It is removed at the cutover, when the container origin is the only one left."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = "FIFO queue the structured-logging layer writes spans to."
  type        = string
}

variable "logs_queue_arn" {
  description = "ARN of that queue, scoping the function's only non-logging grant."
  type        = string
}

variable "user_pool_id" {
  description = "Cognito User Pool id, carried as COGNITO_USER_POOL_ID. A cpcommon required variable: the layer resolves config lazily, so an unset one fails at first read rather than at import — the environment is complete anyway, so the spec that starts verifying tokens inherits no surprise."
  type        = string
}

variable "app_client_id" {
  description = "Cognito app client id, carried as COGNITO_APP_CLIENT_ID."
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
# Five fields, and the verifier reads nothing else about who issues its tokens. That is the
# whole point of them: the target environment swaps the identity provider by changing these
# values rather than by rewriting an authorization path. Every one is computed at root from
# resources Terraform already owns — none is an operator input today.
#
# The client secret, redirect URI and post-logout URI are deliberately ABSENT. They belong to
# a server-side login flow this API does not perform, and a required variable that reaches
# production unset fails a long way from its cause.
#
# Each carries a validation rather than relying on having no default. An unset repo variable
# renders as the EMPTY STRING, which satisfies a required variable and overrides a default —
# so "no default" guards nothing on its own.

variable "oidc_issuer" {
  description = "Exact `iss` the API requires on every token. Computed at root from the pool."
  type        = string

  validation {
    condition     = can(regex("^https://[^ ]+$", var.oidc_issuer))
    error_message = "oidc_issuer must be an https URL. An empty value means it was never computed."
  }
}

variable "oidc_audience" {
  description = "Exact `aud` the API requires — the app client the SPA's ID token is issued to."
  type        = string

  validation {
    condition     = length(var.oidc_audience) > 0
    error_message = "oidc_audience must be the app client id. Empty means it was never computed."
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

  # `tomap` and not `jsondecode` alone: jsondecode accepts a bare scalar, so `42` and `"id"`
  # both satisfy a can(jsondecode(…)) guard, reach the function, and fail in the verifier's
  # parse instead of here. tomap additionally rejects a list. An empty OBJECT still passes,
  # which is correct — a provider asserting no such claim is not thereby misconfigured.
  validation {
    condition     = can(tomap(jsondecode(var.oidc_required_claims)))
    error_message = "oidc_required_claims must be a JSON object such as {\"token_use\":\"id\"} — not a scalar, not a list. An empty value means it was never computed, and would silently stop the token-type check from running at all."
  }
}
