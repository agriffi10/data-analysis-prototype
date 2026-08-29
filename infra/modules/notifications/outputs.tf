output "notifications_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues markRead/markAllRead here on the caller's behalf; the seven notifying execution roles and the drain write it too."
  value       = aws_sqs_queue.requests.url
}

output "notifications_queue_arn" {
  description = "ARN of the FIFO request queue — the `sqs:SendMessage` scope for the API and for every trusted producer. The portal role's half is unconditioned and cannot be otherwise (no SQS condition key reaches a message body); the writer refuses a `create` from it by SenderId instead."
  value       = aws_sqs_queue.requests.arn
}

output "notifications_writer_role_arn" {
  description = "ARN of the privileged notifications-writer role (the single writer of every user's notifications.json)."
  value       = aws_iam_role.writer.arn
}
