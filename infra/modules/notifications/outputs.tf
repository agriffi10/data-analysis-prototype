output "notifications_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). Maps to VITE_NOTIFICATIONS_QUEUE_URL; the browser enqueues markRead/markAllRead here."
  value       = aws_sqs_queue.requests.url
}

output "notifications_queue_arn" {
  description = "ARN of the FIFO request queue — the sqs:SendMessage scope for the portal role and for every trusted producer. The portal role's half is unconditioned and cannot be otherwise (no SQS condition key reaches a message body); the writer refuses a `create` from it by SenderId instead."
  value       = aws_sqs_queue.requests.arn
}

output "notifications_writer_role_arn" {
  description = "ARN of the privileged notifications-writer role (the single writer of every user's notifications.json)."
  value       = aws_iam_role.writer.arn
}
