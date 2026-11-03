# ── The daily wake for both Cognito triggers ─────────────────────────────────
# An image function idle for weeks goes Inactive, and Lambda REJECTS the invoke that wakes it.
# Cognito does not retry that failure: pre-signup would fail on Cognito's own page, and
# post-confirmation would confirm the user with no database and no record that provisioning was
# skipped. One invoke a day is the cadence measured to keep a function Active. README.md.
#
# The payload is a no-op by each handler's EXISTING rules, not by a branch added for it: a valid
# username and no email passes pre-signup, and a triggerSource that is not a sign-up confirmation
# returns from post-confirmation before any Glue or Lake Formation call. Both handlers' tests run
# this file.
resource "aws_cloudwatch_event_rule" "keep_warm" {
  name                = "${var.project_name}-${var.environment}-auth-keep-warm"
  description         = "Invoke both Cognito triggers once a day with a no-op payload, so neither goes Inactive and fails the next sign-up."
  schedule_expression = "rate(24 hours)"
}

resource "aws_cloudwatch_event_target" "keep_warm_pre_signup" {
  rule  = aws_cloudwatch_event_rule.keep_warm.name
  arn   = module.pre_signup.function_arn
  input = file("${path.module}/keep-warm.json")
}

resource "aws_cloudwatch_event_target" "keep_warm_post_confirmation" {
  rule  = aws_cloudwatch_event_rule.keep_warm.name
  arn   = module.post_confirmation.function_arn
  input = file("${path.module}/keep-warm.json")
}

# A target without its permission applies green and fails every invoke silently, counted only
# in the rule's FailedInvocations. test_keep_warm.py pairs each target with one of these.
resource "aws_lambda_permission" "keep_warm_pre_signup" {
  statement_id  = "AllowKeepWarmSchedule"
  action        = "lambda:InvokeFunction"
  function_name = module.pre_signup.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.keep_warm.arn
}

resource "aws_lambda_permission" "keep_warm_post_confirmation" {
  statement_id  = "AllowKeepWarmSchedule"
  action        = "lambda:InvokeFunction"
  function_name = module.post_confirmation.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.keep_warm.arn
}
