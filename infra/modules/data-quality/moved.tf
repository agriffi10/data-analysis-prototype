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
  from = aws_lambda_function.functions["create-temp-tables"]
  to   = module.functions["create-temp-tables"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["create-temp-tables"]
  to   = module.functions["create-temp-tables"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["start-profile-query"]
  to   = module.functions["start-profile-query"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["start-profile-query"]
  to   = module.functions["start-profile-query"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["check-query"]
  to   = module.functions["check-query"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["check-query"]
  to   = module.functions["check-query"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["byte-scan"]
  to   = module.functions["byte-scan"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["byte-scan"]
  to   = module.functions["byte-scan"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["assemble-report"]
  to   = module.functions["assemble-report"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["assemble-report"]
  to   = module.functions["assemble-report"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["drop-temp-tables"]
  to   = module.functions["drop-temp-tables"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["drop-temp-tables"]
  to   = module.functions["drop-temp-tables"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_cloudwatch_log_group.this
}
