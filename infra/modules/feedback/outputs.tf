output "feedback_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues one submission here per POST /v1/feedback, on its own execution role; nothing else writes it."
  value       = aws_sqs_queue.requests.url
}

output "feedback_queue_arn" {
  description = "ARN of the FIFO request queue — the `sqs:SendMessage` scope for the API and for nobody else. The portal role holds no grant on this queue at all, which is what stops a browser writing a feedback record attributed to somebody it chose."
  value       = aws_sqs_queue.requests.arn
}

output "feedback_writer_role_arn" {
  description = "ARN of the feedback-writer role (the single writer of each day's feedback document)."
  value       = aws_iam_role.writer.arn
}
