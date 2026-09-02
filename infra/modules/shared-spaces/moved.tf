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
  from = aws_lambda_function.functions["validate"]
  to   = module.functions["validate"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["validate"]
  to   = module.functions["validate"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["create"]
  to   = module.functions["create"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["create"]
  to   = module.functions["create"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["add-members"]
  to   = module.functions["add-members"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["add-members"]
  to   = module.functions["add-members"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["remove-members"]
  to   = module.functions["remove-members"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["remove-members"]
  to   = module.functions["remove-members"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["leave"]
  to   = module.functions["leave"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["leave"]
  to   = module.functions["leave"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["delete"]
  to   = module.functions["delete"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["delete"]
  to   = module.functions["delete"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["forget"]
  to   = module.functions["forget"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["forget"]
  to   = module.functions["forget"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["acknowledge-membership"]
  to   = module.functions["acknowledge-membership"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["acknowledge-membership"]
  to   = module.functions["acknowledge-membership"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["transfer-ownership"]
  to   = module.functions["transfer-ownership"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["transfer-ownership"]
  to   = module.functions["transfer-ownership"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["notify-failure"]
  to   = module.functions["notify-failure"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.functions["backfill-ever-active"]
  to   = module.functions["backfill-ever-active"].aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.functions["backfill-ever-active"]
  to   = module.functions["backfill-ever-active"].aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.transfer_reader
  to   = module.transfer_reader.aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.transfer_reader
  to   = module.transfer_reader.aws_cloudwatch_log_group.this
}
