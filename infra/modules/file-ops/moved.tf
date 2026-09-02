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
  from = aws_lambda_function.functions["acquire-lock"]
  to   = module.functions["acquire-lock"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["acquire-lock"]
  to   = module.functions["acquire-lock"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["release-lock"]
  to   = module.functions["release-lock"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["release-lock"]
  to   = module.functions["release-lock"].aws_cloudwatch_log_group.this
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
  from = aws_lambda_function.functions["check-destinations"]
  to   = module.functions["check-destinations"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["check-destinations"]
  to   = module.functions["check-destinations"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["build-transfer-manifest"]
  to   = module.functions["build-transfer-manifest"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["build-transfer-manifest"]
  to   = module.functions["build-transfer-manifest"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["copy-objects"]
  to   = module.functions["copy-objects"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["copy-objects"]
  to   = module.functions["copy-objects"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["collect-transfer-results"]
  to   = module.functions["collect-transfer-results"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["collect-transfer-results"]
  to   = module.functions["collect-transfer-results"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["delete-source"]
  to   = module.functions["delete-source"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["delete-source"]
  to   = module.functions["delete-source"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["finalise-outcomes"]
  to   = module.functions["finalise-outcomes"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["finalise-outcomes"]
  to   = module.functions["finalise-outcomes"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["notify"]
  to   = module.functions["notify"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["notify"]
  to   = module.functions["notify"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_cloudwatch_log_group.this
}
