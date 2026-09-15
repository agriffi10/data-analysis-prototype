# Every document here is a templatefile(), never an aws_iam_policy_document data source. This
# module is called with depends_on = [module.base], which defers every data source in it to apply
# whenever module.base has a change pending, and a policy read at apply is one the plan cannot
# show. README.md.

resource "aws_iam_role" "sweep" {
  name               = local.sweep_role_name
  assume_role_policy = templatefile("${path.module}/policies/sweep-trust.json.tftpl", {})
}

# The sweep writes logs and reads BACK ONLY WHAT IT WROTE. No s3:DeleteObject, no Glue, no
# Athena, no access to either user-data bucket — and so no user-space bucket-policy allowlist
# entry is needed for this role. Why it reads at all, and what bounds it: README.md.
#
# The S3 statement is scoped to logs/* — NOT the bucket root, which also holds fallback-results/,
# shared-spaces/ and table-share/. Widening it lets the sweep overwrite a user's query results
# with log lines, or copy them into logs/.
resource "aws_iam_role_policy" "sweep" {
  name = "sweep"
  role = aws_iam_role.sweep.id

  policy = templatefile("${path.module}/policies/sweep-permissions.json.tftpl", {
    logs_queue_arn   = aws_sqs_queue.logs.arn
    admin_bucket_arn = var.admin_bucket_arn
    logs_prefix      = local.logs_prefix
    log_group_arn    = module.sweep.log_group_arn
  })
}

# The sweep is also a PRODUCER — it instruments itself, which proves the whole path without
# touching a control plane. The grant is sqs:SendMessage on the logs queue and nothing else.
#
# The PORTAL role is granted NOTHING on this queue, here or anywhere — it is the identity a
# user's request acts as, and a grant would let a user-scoped session forge log events.
# Producers are execution roles only. README.md.
resource "aws_iam_role_policy" "sweep_producer" {
  name = "logs-producer"
  role = aws_iam_role.sweep.id

  policy = templatefile("${path.module}/policies/logs-producer.json.tftpl", {
    logs_queue_arn = aws_sqs_queue.logs.arn
  })
}
