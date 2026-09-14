output "notifications_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues markRead/markAllRead here on the caller's behalf; the seven notifying execution roles and the drain write it too."
  value       = aws_sqs_queue.requests.url
}

output "notifications_queue_arn" {
  description = "ARN of the FIFO request queue — the `sqs:SendMessage` scope for the API and for every trusted producer. The portal role holds no grant on it, so a user reaches this queue only through the API, whose notifications route accepts `markRead` and `markAllRead` and refuses `create`. The writer's refusal of a `create` whose SenderId names the portal role is a second fence behind that missing grant."
  value       = aws_sqs_queue.requests.arn
}

output "notifications_writer_role_arn" {
  description = "ARN of the privileged notifications-writer role (the single writer of every user's notifications.json)."
  value       = aws_iam_role.writer.arn
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [module.writer.function_name]
}
