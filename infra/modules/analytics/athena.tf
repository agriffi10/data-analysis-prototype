# ── Shared Athena Workgroup ────────────────────────────────
# One workgroup for every user. PER-USER ISOLATION IS NOT AT THIS LAYER — it is the Glue
# database/table ARN scoped by the `username` principal tag, plus the per-user results prefix.
# README.md.

# IAM propagation guard: the deploy role's first CreateWorkGroup / CreateBucket call in the
# same apply can race its own grant.

# IAM propagation guard: the module-level depends_on = [module.base] orders the
# deploy-role policy (which now grants Athena/S3-admin-bucket perms) before
# this module runs, but IAM is eventually consistent — this fresh pause absorbs the
# propagation window so the deploy role's first CreateWorkGroup / CreateBucket call
# in the same apply doesn't race the grant and hit AccessDenied (same pattern as
# data/s3.tf and auth/lambda.tf).
resource "time_sleep" "wait_for_deploy_policy" {
  create_duration = "30s"
}

resource "aws_athena_workgroup" "portal" {
  name = var.workgroup_name

  configuration {
    # OFF ON PURPOSE — the client supplies a per-user OutputLocation per query, and IAM is the
    # real boundary. DO NOT "harden" this to true: it breaks per-user result routing.
    enforce_workgroup_configuration    = false
    publish_cloudwatch_metrics_enabled = true

    # Pinned, not AUTO, so an engine upgrade is a deliberate reviewed change.
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    # Cost guardrail. Also the cutoff a data-quality check over a large source hits.
    bytes_scanned_cutoff_per_query = var.query_scan_cutoff_bytes

    result_configuration {
      # DEFAULT/fallback ONLY, to the admin bucket — a query that omits an explicit
      # OutputLocation writes here, NEVER to a user-readable place. Under fallback-results/
      # rather than the root so the expiry rule cannot reach the registry prefix.
      output_location = "s3://${var.athena_admin_bucket_name}/fallback-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  depends_on = [time_sleep.wait_for_deploy_policy]
}
