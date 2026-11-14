# ── The session store: one table and the key it is encrypted with ─────────────
# OUTSIDE the web tier's switch, so switching the tier off neither schedules the key for deletion
# nor drops every session. Nothing here reads a `network` or `spa` output. README.md.

# The key's policy delegates to the account's IAM and names NO OTHER PRINCIPAL. Naming the task
# role would make this module read a role inside the switch, and the identity policies that use
# the key (the deploy role's, the task role's) are the ones the plan-time IAM scan reads.
resource "aws_kms_key" "session" {
  description             = "Encrypts the portal server's session table, which holds refresh tokens."
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "TheAccountDelegatesToIam"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      }
    ]
  })

  tags = { Name = "${var.project_name}-${var.environment}-session" }
}

resource "aws_kms_alias" "session" {
  name          = local.key_alias
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
