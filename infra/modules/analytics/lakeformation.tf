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
  #   - table-builder execution role (SPEC-070; shared by all five verbs) — Describes
  #     (check-table-absent) + CREATEs (execute-ddl) tables in the dynamic per-user +
  #     per-shared-space target DBs (can't be statically enumerated → catalog-wide
  #     Describe/create via LF admin). Constructed string; the role is created by
  #     module.table_builder (which depends_on this module), so a from-scratch first
  #     apply may need a re-run once the role exists (SPEC-070 FR-005).
  #   - table-share execution role (SPEC-092; same model) — reads LF-gated source
  #     tables (inspect-source), Describes recipient DBs (check-target-absent) and
  #     CREATEs the clone tables (create-table) in the dynamic recipient DBs.
  #   - data-quality execution role (SPEC-111; same model, shared by all nine verbs) —
  #     CREATEs (create-temp-tables) and DELETEs (drop-temp-tables) the THROWAWAY
  #     dq_tmp_* external tables Athena profiles the source through, in the actor's own
  #     database or the shared space's. Every table it creates is dropped on both the
  #     success and the failure path, so this admin leaves no catalog artefact behind.
  #     Constructed string; the role is created by module.data_quality (which
  #     module.analytics depends_on), so it exists before LF validates the principal.
  admins = compact([var.deploy_role_arn, var.lambda_provisioner_role_arn, var.shared_space_orchestrator_role_arn, var.table_builder_execution_role_arn, var.table_share_execution_role_arn, var.data_quality_execution_role_arn])

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

# ── TBAC: control-plane create-table access to every managed database ─────────
# Fixes the SPEC-070/111 error. Being an LF data-lake ADMIN does NOT grant a role
# CREATE_TABLE on a database it did not create — so table-builder / table-share /
# data-quality (all admins) cannot create tables in the dynamic per-user /
# per-shared-space target DBs. Rather than loop a per-DB named grant onto each of
# these shared admin roles (exactly the toil LF-Tags exist to remove), tag every
# managed DB with ONE `portal-managed` LF-Tag and grant the roles on the TAG. The
# provisioning Lambdas (post_confirmation / create_space) attach the tag to each new
# DB; a table inherits its DB's tag, so a created table is reachable by the same
# grant. Adding a future control-plane role is then one grant here — no Lambda change.
#
# The portal role is deliberately NOT tag-granted: its per-user isolation depends on
# the named database ARN + IAM principal tag, so it keeps its per-DB named grant
# (issued by the SPEC-033 Lambda) rather than blanket tag access to every DB.
locals {
  # The three shared control-plane execution roles that create tables in dynamic
  # managed DBs. compact() drops any empty ARN so the module still plans standalone.
  control_plane_role_arns = toset(compact([
    var.table_builder_execution_role_arn,
    var.table_share_execution_role_arn,
    var.data_quality_execution_role_arn,
  ]))
}

# NOTE `portal-managed` (this, a Lake Formation tag on DATABASES, hyphenated) is NOT
# `portal.managed` (a table TBLPROPERTY, dotted — cpcommon/ddl.py, SPEC-143 FR-007). This
# one GRANTS: it is how the control-plane roles get CREATE_TABLE in dynamic databases.
# That one only RECORDS that the portal created a table, and nothing reads it to decide
# anything. One character apart, unrelated jobs.
resource "aws_lakeformation_lf_tag" "portal_managed" {
  key    = "portal-managed"
  values = ["true"]

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# ASSIGNING the tag to a database requires ASSOCIATE permission ON THE TAG — and, like
# CREATE_TABLE, LF data-lake ADMIN status does NOT implicitly grant it (confirmed live:
# the post-confirmation role, an admin, got "Required ASSOCIATE on portal-managed" from
# AddLFTagsToResource). The tag CREATOR (the deploy role, via Terraform) has it
# implicitly; the two provisioning roles that call AddLFTagsToResource — post_confirmation
# (personal DBs) and the shared-space orchestrator (shared DBs) — must be granted it
# explicitly. DESCRIBE lets them reference the tag. The control-plane execution roles
# do NOT assign the tag (they only benefit from the tag-policy grants below), so they
# are not granted ASSOCIATE.
resource "aws_lakeformation_permissions" "provisioner_tag_associate" {
  for_each    = toset(compact([var.lambda_provisioner_role_arn, var.shared_space_orchestrator_role_arn]))
  principal   = each.value
  permissions = ["ASSOCIATE", "DESCRIBE"]

  lf_tag {
    key    = aws_lakeformation_lf_tag.portal_managed.key
    values = ["true"]
  }

  depends_on = [aws_lakeformation_lf_tag.portal_managed]

  # THIS BROKE MAIN, AND WITHOUT IT EVERY FUTURE INFRA APPLY FAILS. Read before removing.
  #
  # Lake Formation does not read this grant back the way Terraform wrote it. We grant
  # ASSOCIATE+DESCRIBE on values ["true"]; a refresh returns values ["*"] with
  # permissions_with_grant_option ["ALTER","ASSOCIATE","DESCRIBE","DROP"] — the principal's
  # EFFECTIVE permissions, because these two roles are also data-lake admins. `values` is
  # replacement-forcing, so every plan showed "must be replaced" and every apply tried to
  # revoke-then-regrant.
  #
  # The revoke then FAILS, because the grant it describes was never explicitly made:
  #   InvalidInputException: No permissions revoked. Revoking Tag permissions on Tags
  #   that grantee does not have permissions on.
  # (Observed 2026-07-21 on the SPEC-112 phase-3 merge, which aborted the apply before it
  # reached the state machine. Nothing was revoked, so the grants survived — a louder
  # failure than it looks, and a luckier one.)
  #
  # The grant itself is correct and is doing its job: it is what lets post_confirmation and
  # create_space call AddLFTagsToResource (SPEC-111's live e2e passed on it). Only the
  # read-back diverges. The tag has exactly ONE value, so LF's ["*"] and our ["true"] are
  # the same grant described two ways.
  #
  # WHAT THIS COSTS: a genuine out-of-band revocation of these grants would no longer show
  # up as drift. That is the accepted trade — the alternative is a permanently red main and
  # an infra pipeline that cannot deploy anything. If provisioning ever fails with
  # "Required ASSOCIATE on portal-managed", check this grant FIRST; Terraform will not.
  lifecycle {
    ignore_changes = [lf_tag, permissions_with_grant_option]
  }
}

# DB level: DESCRIBE + CREATE_TABLE/ALTER/DROP on any database carrying the tag —
# what lets a verb create (and clean up) tables in the target DB.
resource "aws_lakeformation_permissions" "control_plane_tag_database" {
  for_each    = local.control_plane_role_arns
  principal   = each.value
  permissions = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]

  lf_tag_policy {
    resource_type = "DATABASE"
    expression {
      key    = aws_lakeformation_lf_tag.portal_managed.key
      values = ["true"]
    }
  }

  depends_on = [aws_lakeformation_lf_tag.portal_managed]
}

# Table level (via tag inheritance): read + write + table DDL on every table in a
# tagged DB, so a verb can SELECT/INSERT and DROP the tables it manages. Mirrors the
# portal role's per-DB table grant; row-level DELETE is still granted nowhere.
resource "aws_lakeformation_permissions" "control_plane_tag_table" {
  for_each    = local.control_plane_role_arns
  principal   = each.value
  permissions = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]

  lf_tag_policy {
    resource_type = "TABLE"
    expression {
      key    = aws_lakeformation_lf_tag.portal_managed.key
      values = ["true"]
    }
  }

  depends_on = [aws_lakeformation_lf_tag.portal_managed]
}

# The location half LF-Tags can't express: DATA_LOCATION_ACCESS on the registered
# user-space bucket for each control-plane role, so `CREATE EXTERNAL TABLE` over a
# `{username}/…` prefix passes LF's location check. A single per-BUCKET grant covers
# every user prefix, exactly like the portal role's grant above; which user's data a
# role may touch is gated by validate-authorize, not per-prefix IAM.
resource "aws_lakeformation_permissions" "control_plane_user_data_location" {
  for_each    = local.control_plane_role_arns
  principal   = each.value
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = var.user_space_bucket_arn
  }

  depends_on = [
    aws_lakeformation_data_lake_settings.this,
    aws_lakeformation_resource.user_space,
  ]
}
