# ── The session store: one table and the key it is encrypted with ─────────────
# OUTSIDE the web tier's switch, so switching the tier off neither schedules the key for deletion
# nor drops every session. Nothing here reads a `network` or `spa` output. README.md.

# With named_principals set, the key's own policy decides who may use it and no identity policy can
# widen that. The task role is matched by aws:PrincipalArn on a "*" principal, which KMS does not
# check exists, so this key outside the switch does not need the role inside it. Without them the key
# delegates to the account's IAM, for a store a developer reaches with their own credentials.
locals {
  key_policy = (
    var.named_principals == null
    ? templatefile("${path.module}/policies/key-delegated.json.tftpl", { account_id = var.account_id })
    : templatefile("${path.module}/policies/key-named.json.tftpl", {
      account_id      = var.account_id
      aws_region      = var.aws_region
      table_name      = var.table_name
      deploy_role_arn = var.named_principals.deploy_role_arn
      task_role_arn   = var.named_principals.task_role_arn
    })
  )
}

resource "aws_kms_key" "session" {
  description             = "Encrypts the session table ${var.table_name} (${var.key_alias}), which holds refresh tokens."
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = local.key_policy

  tags = { Name = trimprefix(var.key_alias, "alias/") }
}

resource "aws_kms_alias" "session" {
  name          = var.key_alias
  target_key_id = aws_kms_key.session.key_id
}

# Point-in-time recovery is OFF, deliberately: a backup would keep refresh tokens past the sessions
# they belong to, and a restored session store is not something anyone needs. TTL is storage
# hygiene; the server checks expiry on every read, because an expired item is returned until
# DynamoDB gets round to deleting it.
resource "aws_dynamodb_table" "sessions" {
  name                        = var.table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  deletion_protection_enabled = true

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.session.arn
  }

  point_in_time_recovery {
    enabled = false
  }

  tags = { Name = var.table_name }
}
