variable "function_name" {
  description = "The function's full deployed name, as its caller has always declared it."
  type        = string
}

variable "role_name" {
  description = "The execution role's full name. Given rather than derived, because the callers' names do not share a rule (the logs sweep's has no -role suffix)."
  type        = string
}

variable "role_policies" {
  description = "The role's inline policies, by name, each a document the caller rendered. A policy naming the function's own log group takes that ARN as a constructed string, so no policy waits on the function it permits."
  type        = map(string)
}

variable "trust_policy" {
  description = "The role's trust document. Null is this module's Lambda trust (Sid LambdaAssume); the logs sweep passes its own, which carries no Sid."
  type        = string
  default     = null
}

variable "handler" {
  description = "The handler the image runs as this function's command."
  type        = string
}

variable "timeout_seconds" {
  description = "The function's timeout."
  type        = number
}

variable "memory_mb" {
  description = "The function's memory."
  type        = number
}

variable "environment_variables" {
  description = "The function's environment."
  type        = map(string)
}

variable "lambda_image_repository_url" {
  description = "The fleet's one image registry."
  type        = string
}

variable "lambda_image_tag" {
  description = "The tag the function is created from; ignored afterwards, because CI points every function on each deploy."
  type        = string
}

variable "rule_name" {
  description = "The EventBridge schedule rule's name."
  type        = string
}

variable "rule_description" {
  description = "The rule's description. Null where the caller has never set one."
  type        = string
  default     = null
}

variable "schedule_expression" {
  description = "When the function runs, as an EventBridge rate or cron expression."
  type        = string
}

variable "permission_statement_id" {
  description = "The statement id of the permission letting the rule invoke the function. The callers' ids differ, and the id is part of the permission's identity."
  type        = string
}
