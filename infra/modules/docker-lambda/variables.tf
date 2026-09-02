variable "function_name" {
  description = "The deployed function name. Built by the calling module from project, environment and the function's suffix, so the one string stays the caller's to decide."
  type        = string
}

variable "image_repository_url" {
  description = "Registry URI of the fleet's one image, from module.lambda_image.repository_url. Every function in the fleet runs the same image and differs only by its command."
  type        = string
}

variable "image_tag" {
  description = "The commit sha whose image this function is CREATED from. It is ignored after creation — CI re-points every function with update-function-code on each deploy — but it must be a tag the registry already holds, or CreateFunction fails."
  type        = string
}

variable "command" {
  description = "The image command, which is what makes one image serve 86 functions: [\"<module>.<handler>\"], exactly the string a zip-packaged function carried as its `handler`."
  type        = list(string)

  validation {
    # An empty command starts the image with no handler at all. There is no CMD in the Dockerfile
    # to fall back on — deliberately, so a function that forgot to declare one cannot start and
    # quietly do the wrong thing — which makes an empty list a container that fails at INIT.
    condition     = length(var.command) > 0
    error_message = "command must name a handler; the image declares no CMD, so an empty command cannot start."
  }

  validation {
    condition     = alltrue([for c in var.command : can(regex("^[a-z0-9_]+\\.[a-z0-9_]+$", c))])
    error_message = "each command element must be <module>.<handler> in snake_case, matching the handler string the zip-packaged function used."
  }
}

variable "role_arn" {
  description = "Execution role ARN. Unchanged by the move to containers — a packaging change grants nothing new."
  type        = string
}

variable "environment" {
  description = "The function's environment map, passed whole. Every variable a shared layer's config requires at import must be present, or the function fails at cold start rather than at deploy."
  type        = map(string)
  default     = {}
}

variable "timeout_seconds" {
  description = "Execution ceiling in seconds."
  type        = number
}

variable "memory_mb" {
  description = "Memory tier. Declared ALWAYS, never left to the AWS default, for two reasons: an unset tier is invisible in the plan and shows up only as a production OOM, and an attribute the configuration does not set comes back UNKNOWN in a replacement plan, which is what the cutover's parity fixture compares against."
  type        = number
  default     = 128
}

variable "architectures" {
  description = "Instruction set. Declared explicitly for the same plan-visibility reason as memory, and because the image is built --platform linux/amd64: an arm64 function fails at start with a manifest error that reads nothing like the mismatch it is."
  type        = list(string)
  default     = ["x86_64"]
}

variable "reserved_concurrency" {
  description = "Reserved concurrent executions. -1 is the provider's own 'unreserved', declared rather than omitted so the value is known in a replacement plan."
  type        = number
  default     = -1
}

variable "vpc_config" {
  description = "Subnets and security groups, or null for a function outside the VPC. The API function is deliberately outside it and stays that way."
  type = object({
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

variable "log_retention_days" {
  description = "Log group retention. The group is created HERE rather than beside the function's caller, so a function and its log group cannot be declared in two places and disagree."
  type        = number
  default     = 14
}

variable "description" {
  description = "Optional function description."
  type        = string
  default     = null
}

variable "tags" {
  description = "Optional resource tags."
  type        = map(string)
  default     = {}
}
