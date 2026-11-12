variable "queue_name" {
  description = "The FIFO request queue's full name, ending in .fifo."
  type        = string
}

variable "dlq_name" {
  description = "The request queue's own dead-letter queue, ending in .fifo. Never shared with another queue, so a malformed message here cannot dead-letter anything else's."
  type        = string
}

variable "content_based_deduplication" {
  description = "Whether the request queue deduplicates on the body. The callers differ: one sets an explicit deduplication id on every send and keeps this off, so a send that stopped setting one fails loudly rather than mostly collapsing."
  type        = bool
}

variable "deduplication_scope" {
  description = "The request queue's deduplication scope. Null leaves the queue-wide default; messageGroup collapses two messages only inside one group."
  type        = string
  default     = null
}

variable "function_name" {
  description = "The writer's full deployed name."
  type        = string
}

variable "role_name" {
  description = "The writer's execution role's full name."
  type        = string
}

variable "role_policy" {
  description = "The role's one inline policy, named writer, as a document the caller rendered. The queue's and the log group's ARNs in it are constructed strings, so it waits on nothing this module creates."
  type        = string
}

variable "handler" {
  description = "The handler the image runs as the writer's command."
  type        = string
}

variable "memory_mb" {
  description = "The writer's memory. The callers differ: one document is capped and one grows all day."
  type        = number
}

variable "environment_variables" {
  description = "The writer's environment."
  type        = map(string)
}

variable "lambda_image_repository_url" {
  description = "The fleet's one image registry."
  type        = string
}

variable "lambda_image_tag" {
  description = "The tag the writer is created from; ignored afterwards, because CI points every function on each deploy."
  type        = string
}
