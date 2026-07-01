# ── Lake Formation bootstrap (SPEC-032 FR-004) ───────────────────────────────
# Make LF the enforcing authority for the Glue Data Catalog: designate admins and
# remove the default IAMAllowedPrincipals "Super" grants, so new databases/tables
# get NO automatic catalog-wide access and LF genuinely gates the catalog.
#
# SAFE TO ENABLE NOW because:
#   (a) the file browser reads the user-space bucket via direct S3 IAM (hybrid mode,
#       FR-005) — NOT through LF — so removing the Super grant doesn't touch it;
#   (b) no per-user Glue databases exist yet (SPEC-033), so there's nothing to lock
#       out. The end-to-end query path only works once SPEC-033's post-confirmation
#       Lambda creates a user's database AND LF-grants the shared role on it.
# Until then, FR-006's Glue IAM scoping + this enforcement simply deny catalog
# access — the correct, safe state.
resource "aws_lakeformation_data_lake_settings" "this" {
  # Admins can grant/revoke and register locations:
  #   - deploy role        — runs the IaC
  #   - provisioner Lambda — issues per-database grants (root wires module.auth's
  #                          output into lambda_provisioner_role_arn)
  # (The account root was briefly a direct admin to validate the per-user databases;
  # removed once confirmed.) All ARNs are KNOWN at plan time (constructed strings);
  # an unknown element inside this compact() silently drops the admins change.
  # compact() also drops any empty ARN so the module still plans standalone.
  #   - shared-space orchestrator (SPEC-056) — grants on shared DBs + the shared
  #     location; constructed string, ordered after module.shared_spaces so it exists.
  #   - table-builder execute-ddl (SPEC-070) — CREATEs tables in the dynamic per-user +
  #     per-shared-space target DBs (can't be statically enumerated → catalog-wide
  #     creator via LF admin). Constructed string; the role is created by
  #     module.table_builder (which depends_on this module), so a from-scratch first
  #     apply may need a re-run once the role exists (SPEC-070 FR-005).
  admins = compact([var.deploy_role_arn, var.lambda_provisioner_role_arn, var.shared_space_orchestrator_role_arn, var.table_builder_execute_ddl_role_arn])

  # Empty default permissions for the special IAMAllowedPrincipals principal =
  # remove the automatic "Super" grant on newly created databases and tables.
  create_database_default_permissions {
    permissions = []
    principal   = "IAM_ALLOWED_PRINCIPALS"
  }

  create_table_default_permissions {
    permissions = []
    principal   = "IAM_ALLOWED_PRINCIPALS"
  }

  depends_on = [time_sleep.wait_for_deploy_policy]
}

# ── Hybrid-mode registration of the user-space bucket (SPEC-032 FR-005) ──────
# Register the user-space bucket as an LF location in HYBRID access mode so the
# same data is reachable two ways:
#   - NON-opted-in principals (the file browser, SPEC-013 direct S3 IAM) — unchanged
#   - opted-in principals (the portal role for analytics) — via LF credential vending
# LF assumes the custom registration role (iam.tf) to vend creds for this location.
#
# WARNING: do NOT flip this to enforced (non-hybrid) mode without opting in EVERY
# principal first — it would break the file browser's direct S3 access.
resource "aws_lakeformation_resource" "user_space" {
  arn                   = var.user_space_bucket_arn
  role_arn              = aws_iam_role.lf_registration.arn
  hybrid_access_enabled = true

  depends_on = [aws_iam_role_policy.lf_registration]
}

# Data-location grant (SPEC-032 FR-005): the shared portal role needs
# DATA_LOCATION_ACCESS on the registered location to CREATE any table over it —
# both CREATE EXTERNAL TABLE (read-only) and CTAS / INSERT INTO (writes). This is a
# single location-level grant (not per-user); per-user gating still comes from IAM
# (the Glue database ARN principal-tag scoping in FR-006 and S3
# ${aws:PrincipalTag/username}/* from SPEC-013), so the role can only actually
# create/write within its own session's prefix. The LF INSERT *table* permission
# for writes is granted later, per-database, by the SPEC-033 Lambda.
resource "aws_lakeformation_permissions" "portal_data_location" {
  principal   = var.portal_role_arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = var.user_space_bucket_arn
  }

  depends_on = [
    aws_lakeformation_data_lake_settings.this,
    aws_lakeformation_resource.user_space,
  ]
}
