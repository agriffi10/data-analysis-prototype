# ── Lake Formation bootstrap ───────────────────────────────
# Removes the default IAMAllowedPrincipals "Super" grants so new databases and tables get NO
# automatic catalog-wide access. Safe to enable because the file browser reads via direct S3
# IAM (hybrid mode), not through LF. README.md.
resource "aws_lakeformation_data_lake_settings" "this" {
  # ⚠ EVERY ARN HERE IS A CONSTRUCTED STRING, KNOWN AT PLAN TIME — an unknown element inside
  # this compact() SILENTLY DROPS THE ADMINS CHANGE. compact() also drops empty ARNs so the
  # module plans standalone. Some of these roles are created by modules that depends_on this
  # one, so a from-scratch first apply may need a re-run once they exist. README.md.
  admins = compact([var.deploy_role_arn, var.lambda_provisioner_role_arn, var.shared_space_orchestrator_role_arn, var.table_builder_execution_role_arn, var.table_share_execution_role_arn, var.data_quality_execution_role_arn])

  # Empty defaults for IAMAllowedPrincipals = remove the automatic "Super" grant on newly
  # created databases and tables.
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

# ── Hybrid-mode registration of the user-space bucket ──────
# HYBRID, so the same data is reachable by direct S3 IAM. Lake Formation vends credentials only to a
# principal opted in over the location, and the infrastructure opts none in: the portal role reads
# the objects through IAM for analytics too, and Lake Formation governs the catalog alone. An opt-in
# made outside it would not show here; the name-collision report's opt-in list reads the account.
#
# ⚠ DO NOT FLIP THIS TO ENFORCED without opting in EVERY principal first — it would break the
# file browser's direct S3 access. README.md.
resource "aws_lakeformation_resource" "user_space" {
  arn                   = var.user_space_bucket_arn
  role_arn              = aws_iam_role.lf_registration.arn
  hybrid_access_enabled = true

  depends_on = [aws_iam_role_policy.lf_registration]
}

# DATA_LOCATION_ACCESS is required to CREATE any table over the location — both CREATE
# EXTERNAL TABLE and CTAS / INSERT INTO. A SINGLE location-level grant, not per-user; per-user
# gating still comes from IAM. The LF INSERT table permission is granted later, per-database,
# by the post-confirmation Lambda.
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
# ⚠ BEING AN LF DATA-LAKE ADMIN DOES NOT GRANT CREATE_TABLE on a database the role did not
# create. Rather than loop a per-DB named grant onto each shared role, every managed database
# carries ONE `portal-managed` tag and the roles are granted on the TAG. A table inherits its
# database's tag, so adding a future control-plane role is one grant here — no Lambda change.
#
# The portal role is deliberately NOT tag-granted: its isolation depends on the named database
# ARN plus the IAM principal tag. README.md.
locals {
  # compact() drops any empty ARN so the module still plans standalone.
  control_plane_role_arns = toset(compact([
    var.table_builder_execution_role_arn,
    var.table_share_execution_role_arn,
    var.data_quality_execution_role_arn,
  ]))
}

# ⚠ `portal-managed` (a Lake Formation tag on DATABASES, hyphenated) is NOT `portal.managed`
# (a table TBLPROPERTY, dotted, in cpcommon/ddl.py). This one GRANTS; that one only RECORDS,
# and nothing reads it to decide anything. ONE CHARACTER APART, UNRELATED JOBS.
resource "aws_lakeformation_lf_tag" "portal_managed" {
  key    = "portal-managed"
  values = ["true"]

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# ⚠ ASSIGNING the tag requires ASSOCIATE ON THE TAG, and LF ADMIN STATUS DOES NOT IMPLICITLY
# GRANT IT — confirmed live: the post-confirmation role, an admin, got "Required ASSOCIATE on
# portal-managed" from AddLFTagsToResource. The tag CREATOR has it implicitly; the two
# provisioning roles must be granted it explicitly. The execution roles do not assign the tag,
# so they are not granted ASSOCIATE. README.md.
resource "aws_lakeformation_permissions" "provisioner_tag_associate" {
  for_each    = toset(compact([var.lambda_provisioner_role_arn, var.shared_space_orchestrator_role_arn]))
  principal   = each.value
  permissions = ["ASSOCIATE", "DESCRIBE"]

  lf_tag {
    key    = aws_lakeformation_lf_tag.portal_managed.key
    values = ["true"]
  }

  depends_on = [aws_lakeformation_lf_tag.portal_managed]

  # ⚠ THIS BROKE MAIN, AND WITHOUT IT EVERY FUTURE INFRA APPLY FAILS. Read README.md before
  # removing.
  #
  # Lake Formation does not read this grant back the way Terraform wrote it: a refresh returns
  # the principal's EFFECTIVE permissions, because these roles are also data-lake admins.
  # `values` is replacement-forcing, so every plan showed "must be replaced" — and the revoke
  # then FAILS, because the grant it describes was never explicitly made.
  #
  # WHAT THIS COSTS: a genuine out-of-band revocation would no longer show up as drift. IF
  # PROVISIONING EVER FAILS WITH "Required ASSOCIATE on portal-managed", CHECK THIS GRANT
  # FIRST — Terraform will not.
  lifecycle {
    ignore_changes = [lf_tag, permissions_with_grant_option]
  }
}

# DB level: what lets a verb create and clean up tables in the target database.
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

# Table level, via tag inheritance. Mirrors the portal role's per-DB table grant; row-level
# DELETE is still granted nowhere.
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

# THE LOCATION HALF LF-TAGS CANNOT EXPRESS — tags cover DB and table resources, not S3
# locations. One per-BUCKET grant covers every user prefix; which user's data a role may touch
# is gated by validate-authorize, not per-prefix IAM.
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

# ── The read-only verification principal ──────────────────────────────────────
# DESCRIBE alone, on the same `portal-managed` tag, because the databases are created at
# runtime and nothing static can enumerate them. The IAM half lives in modules/verification.
#
# DELIBERATELY ABSENT: SELECT and DATA_LOCATION_ACCESS. This role reads a table's DEFINITION
# and cannot read a byte of what the table points at. README.md.
locals {
  verification_role_arns = toset(compact([var.verification_role_arn]))
}

resource "aws_lakeformation_permissions" "verification_tag_database" {
  for_each    = local.verification_role_arns
  principal   = each.value
  permissions = ["DESCRIBE"]

  lf_tag_policy {
    resource_type = "DATABASE"
    expression {
      key    = aws_lakeformation_lf_tag.portal_managed.key
      values = ["true"]
    }
  }

  depends_on = [aws_lakeformation_lf_tag.portal_managed]
}

resource "aws_lakeformation_permissions" "verification_tag_table" {
  for_each    = local.verification_role_arns
  principal   = each.value
  permissions = ["DESCRIBE"]

  lf_tag_policy {
    resource_type = "TABLE"
    expression {
      key    = aws_lakeformation_lf_tag.portal_managed.key
      values = ["true"]
    }
  }

  depends_on = [aws_lakeformation_lf_tag.portal_managed]
}
