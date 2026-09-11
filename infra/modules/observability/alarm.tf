# The backlog alarm: the age of the logs queue's oldest message. README.md.
#
# AGE, not the sweep's stop reason, because age is the lag itself and holds whatever the cause —
# a wave cap, the time reserve, a blocked group, or a sweep that is not running at all. A sweep
# can also stop on its wave cap while caught up, chasing what arrives during an active session.
#
# 1800s is three missed ticks. A healthy queue's oldest message waits for the next tick and no
# longer, measured at 574-586s across a whole idle day, and each missed tick adds ~600s to that
# peak: two in a row reach ~1780s and do not fire this, three in a row do, about 40 minutes after
# the last good sweep. Two five-minute datapoints, so a brief spike cannot fire it either.
#
# NO alarm_actions, by decision: the state is read in the console and by a session's
# describe-alarms. Nothing enforces that — an action aimed at a Lambda that already exists would
# apply with the grants the deploy role holds — so adding one is a decision to re-make, not a fix.
resource "aws_cloudwatch_metric_alarm" "logs_backlog" {
  alarm_name        = local.backlog_alarm_name
  alarm_description = "The logs queue's oldest message has waited over 30 minutes: the log sweep is three ticks behind or not running. infra/modules/observability/README.md."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateAgeOfOldestMessage"
  dimensions = {
    QueueName = aws_sqs_queue.logs.name
  }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 1800

  # The sweep logs into this queue every tick, so a healthy queue always has something to report.
  # No data therefore means something is wrong, and it reads as INSUFFICIENT_DATA rather than as a
  # healthy queue.
  treat_missing_data = "missing"
}
