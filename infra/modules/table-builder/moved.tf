# ── The container cutover's state moves ──────────────────────────────────────
# Every function and its log group changed ADDRESS when the fleet became calls to
# ../docker-lambda. Without these, Terraform plans a create at the new address and a destroy at
# the old one with NO DEPENDENCY EDGE BETWEEN THEM — for a function that is CreateFunction racing
# DeleteFunction on one name, and for a log group it is ResourceAlreadyExistsException or lost
# logs. `moved` takes static addresses only, so there is one block per instance.
#
# The move is not the replacement. `package_type` is ForceNew, so each function is still
# destroyed and recreated after the move; what these buy is that Terraform does it as ONE
# ordered replacement rather than as an unordered create/destroy pair.

moved {
  from = aws_lambda_function.functions["validate-authorize"]
  to   = module.functions["validate-authorize"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["validate-authorize"]
  to   = module.functions["validate-authorize"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["check-table-absent"]
  to   = module.functions["check-table-absent"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["check-table-absent"]
  to   = module.functions["check-table-absent"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["load-table-definition"]
  to   = module.functions["load-table-definition"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["load-table-definition"]
  to   = module.functions["load-table-definition"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["acquire-refresh-lock"]
  to   = module.functions["acquire-refresh-lock"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["acquire-refresh-lock"]
  to   = module.functions["acquire-refresh-lock"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["release-refresh-lock"]
  to   = module.functions["release-refresh-lock"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["release-refresh-lock"]
  to   = module.functions["release-refresh-lock"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["inspect-source"]
  to   = module.functions["inspect-source"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["inspect-source"]
  to   = module.functions["inspect-source"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["infer-schema"]
  to   = module.functions["infer-schema"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["infer-schema"]
  to   = module.functions["infer-schema"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["diff-schema"]
  to   = module.functions["diff-schema"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["diff-schema"]
  to   = module.functions["diff-schema"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["apply-refresh"]
  to   = module.functions["apply-refresh"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["apply-refresh"]
  to   = module.functions["apply-refresh"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["execute-ddl"]
  to   = module.functions["execute-ddl"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["execute-ddl"]
  to   = module.functions["execute-ddl"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_cloudwatch_log_group.this
}
