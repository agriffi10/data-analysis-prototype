output "s3_static_assets_bucket_name" {
  description = "Name of the S3 bucket hosting the built SPA. Used by the deploy-app workflow."
  value       = module.app.static_assets_bucket_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Used by the deployment workflow to create cache invalidations."
  value       = module.app.cloudfront_distribution_id
}

output "cloudfront_domain" {
  description = "CloudFront domain for the portal. Set VITE_APP_URL to this value after the first deploy."
  value       = "https://${module.app.cloudfront_domain_name}"
}

output "github_actions_role_arn" {
  description = "IAM role ARN assumed by the GitHub Actions deployment workflows."
  value       = module.base.github_actions_role_arn
}

output "aws_region" {
  description = "AWS region where resources are deployed. Maps to VITE_AWS_REGION."
  value       = var.aws_region
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID. Set VITE_COGNITO_USER_POOL_ID to this value."
  value       = module.auth.user_pool_id
}

output "cognito_user_pool_client_id" {
  description = "Cognito SPA app client ID. Set VITE_COGNITO_USER_POOL_CLIENT_ID to this value."
  value       = module.auth.user_pool_client_id
}

output "cognito_domain" {
  description = "Cognito Hosted UI domain. Set VITE_COGNITO_DOMAIN to this value."
  value       = module.auth.user_pool_domain

  # The CSP's connect-src allows local.cognito_hosted_ui_domain, but the app
  # actually fetches the domain THIS output names (via VITE_COGNITO_DOMAIN). If
  # the two ever disagree the authorization-code exchange is blocked and sign-in
  # breaks with no failing test anywhere — that outage happened once already
  # (2026-08-04). A precondition is a hard error at plan time; a `check` block
  # would only warn, which is how this class of bug goes unnoticed.
  precondition {
    condition     = module.auth.user_pool_domain == local.cognito_hosted_ui_domain
    error_message = "CSP/Hosted UI drift: connect-src allows ${local.cognito_hosted_ui_domain} but the user pool domain is ${module.auth.user_pool_domain}. Sign-in would be blocked. Reconcile local.cognito_hosted_ui_domain in main.tf with modules/auth."
  }
}

output "s3_user_space_bucket_name" {
  description = "Name of the user-space S3 bucket (Bucket 1). Set VITE_S3_USER_SPACE_BUCKET to this value (consumed by the build starting SPEC-013)."
  value       = module.data.user_space_bucket_name
}

output "cognito_identity_pool_id" {
  description = "Cognito Identity Pool ID. Set VITE_COGNITO_IDENTITY_POOL_ID to this value (SPEC-011)."
  value       = module.auth.identity_pool_id
}

output "lambda_artifacts_bucket_name" {
  description = "Lambda deployment artifacts bucket (SPEC-012). The deploy-lambdas workflow uploads packages here before update-function-code."
  value       = module.lambda_artifacts.bucket_name
}

output "pre_signup_function_name" {
  description = "Name of the pre-signup validation Lambda (SPEC-012). The deploy-lambdas workflow targets this for update-function-code."
  value       = module.auth.pre_signup_function_name
}

output "athena_workgroup_name" {
  description = "Name of the shared Athena workgroup (SPEC-032). Set VITE_ATHENA_WORKGROUP to this value (consumed by the app starting SPEC-034)."
  value       = module.analytics.athena_workgroup_name
}

output "athena_admin_bucket_name" {
  description = "Name of the admin-only Athena results bucket (SPEC-032). Exported for ops; not consumed by the app."
  value       = module.analytics.athena_admin_bucket_name
}

# ── Shared-space foundation (SPEC-050) ───────────────────────────────────────
output "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2, SPEC-050). Maps to a VITE_* once shared-space file ops land (SPEC-057)."
  value       = module.shared_spaces.shared_space_bucket_name
}

output "shared_space_request_queue_url" {
  description = "URL of the FIFO shared-space request queue (SPEC-050). The browser enqueues control-plane requests here once granted sqs:SendMessage (SPEC-056); maps to VITE_SHARED_SPACE_QUEUE_URL."
  value       = module.shared_spaces.request_queue_url
}

output "shared_space_orchestrator_role_arn" {
  description = "ARN of the privileged shared-space orchestrator role (Step Function + provisioner Lambda, SPEC-050). Added as a Lake Formation admin in SPEC-056."
  value       = module.shared_spaces.orchestrator_role_arn
}

output "shared_space_state_machine_arn" {
  description = "ARN of the shared-space orchestrator Step Function (SPEC-050). Used by the control-plane bring-up checks (docs/testing/owed.md)."
  value       = module.shared_spaces.state_machine_arn
}

# ── Notifications write pipeline (SPEC-058) ──────────────────────────────────
output "notifications_queue_url" {
  description = "URL of the FIFO notifications request queue (SPEC-058; ends in .fifo). The browser enqueues markRead/markAllRead here once granted sqs:SendMessage (granted in this spec); maps to VITE_NOTIFICATIONS_QUEUE_URL in SPEC-059."
  value       = module.notifications.notifications_queue_url
}

output "notifications_queue_arn" {
  description = "ARN of the FIFO notifications request queue (SPEC-058) — the portal-role + (future trusted-producer, SPEC-061) sqs:SendMessage scope."
  value       = module.notifications.notifications_queue_arn
}

output "notifications_writer_role_arn" {
  description = "ARN of the privileged notifications-writer role (SPEC-058) — the single writer of every user's notifications.json."
  value       = module.notifications.notifications_writer_role_arn
}

# ── Verification access (SPEC-186 FR-004) ────────────────────────────────────
# The three values a live check needs by name. `trail_name` is here for a reason worth
# stating: a trail that is not logging returns an EMPTY result, which reads exactly like a
# `RestoreObject` that never happened — so the negative assertion has to confirm the trail is
# on before it trusts the absence (SPEC-138's "did not run is never clean").
output "verification_role_arn" {
  description = "SPEC-186 FR-004: the read-only role a live check assumes for catalog read-backs and the archive audit record."
  value       = module.verification.verification_role_arn
}

output "verification_trail_bucket" {
  description = "SPEC-186 FR-004: where the archive vault's object-level CloudTrail events land."
  value       = module.verification.trail_bucket_name
}

output "verification_trail_name" {
  description = "SPEC-186 FR-004: the trail itself, so a check can prove it is logging before reading an absence as evidence."
  value       = module.verification.trail_name
}
