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
  from = aws_lambda_function.pre_signup
  to   = module.pre_signup.aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.pre_signup
  to   = module.pre_signup.aws_cloudwatch_log_group.this
}

moved {
  from = aws_lambda_function.post_confirmation
  to   = module.post_confirmation.aws_lambda_function.this
}

moved {
  from = aws_cloudwatch_log_group.post_confirmation
  to   = module.post_confirmation.aws_cloudwatch_log_group.this
}
