output "logs_queue_url" {
  description = "URL of the logs queue. Set as LOGS_QUEUE_URL on every function that logs; optional by construction (cpcommon.observability reads it with os.environ.get), so a function that misses it logs to stdout rather than crashing at cold start."
  value       = aws_sqs_queue.logs.url
}

output "logs_queue_arn" {
  description = "ARN of the logs queue, for producer grants."
  value       = aws_sqs_queue.logs.arn
}
