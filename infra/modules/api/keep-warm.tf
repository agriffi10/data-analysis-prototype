# ── The daily wake for the API function ──────────────────────────────────────
# An image function idle for weeks goes Inactive, and Lambda REJECTS the invoke that wakes it, so
# the first request after a quiet spell would fail. The SPA retries only an idempotent query,
# once. One invoke a day is the cadence measured to keep a function Active. README.md.
#
# The payload is the health route, which answers 200 with no identity and no AWS call. A bare
# event would be refused as unauthenticated every day and read as a refusal. test_handler.py runs
# this file.
resource "aws_cloudwatch_event_rule" "keep_warm" {
  name                = "${var.project_name}-${var.environment}-api-keep-warm"
  description         = "Invoke the API function once a day on its health route, so it never goes Inactive and fails the next request."
  schedule_expression = "rate(24 hours)"
}

resource "aws_cloudwatch_event_target" "keep_warm" {
  rule  = aws_cloudwatch_event_rule.keep_warm.name
  arn   = module.api.function_arn
  input = file("${path.module}/keep-warm.json")
}

# A target without its permission applies green and fails every invoke silently, counted only
# in the rule's FailedInvocations. test_keep_warm.py pairs each target with one of these.
resource "aws_lambda_permission" "keep_warm" {
  statement_id  = "AllowKeepWarmSchedule"
  action        = "lambda:InvokeFunction"
  function_name = module.api.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.keep_warm.arn
}
