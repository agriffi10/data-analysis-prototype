# ── Shared Athena Workgroup ────────────────────────────────
# One workgroup every authenticated user queries through. Per-user isolation is
# NOT at the workgroup layer — it's the Glue database/table ARN scoped by the
# `username` principal tag (FR-006) plus the per-user results prefix. Athena has
# no built-in per-user result location, so enforcement is OFF and the app sets a
# per-user OutputLocation (s3://<user-space-bucket>/{username}/athenaresults/) on
# every StartQueryExecution; IAM (FR-006) is what actually confines each caller to
# its own prefix.

# IAM propagation guard: the module-level depends_on = [module.base] orders the
# deploy-role policy (which now grants Athena/S3-admin-bucket perms, FR-007) before
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
    # OFF on purpose: the client supplies a per-user OutputLocation per query (see
    # header). The real per-user boundary is the FR-006 IAM scoping, noted here so
    # nobody "hardens" this to true and breaks per-user result routing.
    enforce_workgroup_configuration    = false
    publish_cloudwatch_metrics_enabled = true

    # Pin engine v3 explicitly (not "AUTO") so engine upgrades are a deliberate,
    # reviewed change rather than silent.
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    # Cost guardrail — fail a query that would scan more than this. Tunable.
    bytes_scanned_cutoff_per_query = var.query_scan_cutoff_bytes

    result_configuration {
      # DEFAULT/fallback only → the admin-only bucket (FR-003). Any query that ever
      # omits an explicit OutputLocation writes here, never to a user-readable place.
      # Scoped to a fallback-results/ prefix (not the bucket root) so the
      # expire-admin-results lifecycle rule can target ONLY transient fallback output
      # and leave the SPEC-050 shared-spaces/ registry prefix untouched (s3.tf).
      output_location = "s3://${var.athena_admin_bucket_name}/fallback-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  depends_on = [time_sleep.wait_for_deploy_policy]
}
