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
  from = aws_lambda_function.functions["inspect-source"]
  to   = module.functions["inspect-source"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["inspect-source"]
  to   = module.functions["inspect-source"].aws_cloudwatch_log_group.this
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
  from = aws_lambda_function.functions["collect-transfer-results"]
  to   = module.functions["collect-transfer-results"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["collect-transfer-results"]
  to   = module.functions["collect-transfer-results"].aws_cloudwatch_log_group.this
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
  from = aws_lambda_function.functions["rollback"]
  to   = module.functions["rollback"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["rollback"]
  to   = module.functions["rollback"].aws_cloudwatch_log_group.this
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
  from = aws_lambda_function.functions["write-manifest"]
  to   = module.functions["write-manifest"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["write-manifest"]
  to   = module.functions["write-manifest"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["write-receipt"]
  to   = module.functions["write-receipt"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["write-receipt"]
  to   = module.functions["write-receipt"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["inspect-archive"]
  to   = module.functions["inspect-archive"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["inspect-archive"]
  to   = module.functions["inspect-archive"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["check-destination-clear"]
  to   = module.functions["check-destination-clear"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["check-destination-clear"]
  to   = module.functions["check-destination-clear"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["build-restore-manifest"]
  to   = module.functions["build-restore-manifest"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["build-restore-manifest"]
  to   = module.functions["build-restore-manifest"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["initiate-restore"]
  to   = module.functions["initiate-restore"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["initiate-restore"]
  to   = module.functions["initiate-restore"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["poll-restore"]
  to   = module.functions["poll-restore"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["poll-restore"]
  to   = module.functions["poll-restore"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["delete-archived"]
  to   = module.functions["delete-archived"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["delete-archived"]
  to   = module.functions["delete-archived"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["update-receipt"]
  to   = module.functions["update-receipt"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["update-receipt"]
  to   = module.functions["update-receipt"].aws_cloudwatch_log_group.this
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
