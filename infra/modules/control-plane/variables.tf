variable "name" {
  description = "The plane's slug, the middle of every name this module creates: \"table-share\" gives dat-prod-table-share-requests.fifo. Shared spaces' is the singular \"shared-space\"."
  type        = string
}

variable "project_name" {
  description = "The project prefix every name starts with."
  type        = string
}

variable "environment" {
  description = "The environment name, second in every name and the verbs' ENV_NAME."
  type        = string
}

variable "aws_region" {
  description = "The region every constructed ARN names."
  type        = string
}

variable "account_id" {
  description = "The account every constructed ARN names."
  type        = string
}

variable "functions" {
  description = "The plane's verbs, keyed by verb (the suffix of each function's name and the key the definition template reads its ARN by)."
  type = map(object({
    handler              = string
    timeout              = number
    memory               = number
    ephemeral_storage_mb = optional(number, 512)
    environment          = optional(map(string), {})
  }))
}

variable "environment_variables" {
  description = "The environment every verb shares. Every variable the plane's domain config requires belongs here, never in a verb's own map: the config runs on any import chain, so a verb missing one fails on whichever branch reads it."
  type        = map(string)
}

variable "lambda_image_repository_url" {
  description = "The fleet's one image registry."
  type        = string
}

variable "lambda_image_tag" {
  description = "The tag the functions are created from; ignored afterwards, because CI points every function on each deploy."
  type        = string
}

variable "content_based_deduplication" {
  description = "Whether the request queue deduplicates on content. The producer's explicit MessageDeduplicationId is the real guard either way."
  type        = bool
}

variable "dlq_content_based_deduplication" {
  description = "Whether the DLQ deduplicates on content, set separately because data quality's differs from its queue's."
  type        = bool
}

variable "dlq_max_receive_count" {
  description = "Receives before a request moves to the DLQ, where the drain tells the user it failed."
  type        = number
}

variable "definition_template" {
  description = "Path to the plane's state-machine definition template. It is rendered with `<verb>_function_arn` for every verb (hyphens as underscores), `state_machine_timeout_seconds` when a ceiling is set, and `definition_vars`."
  type        = string
}

variable "definition_vars" {
  description = "The plane's own values its definition reads, such as its map caps."
  type        = map(any)
  default     = {}
}

variable "ceiling" {
  description = "The machine's top-level TimeoutSeconds and the door a timed-out run is told through. Null is no ceiling and no TIMED_OUT rule; set, the rule exists, targets the notifier verb, and the definition reads the seconds."
  type = object({
    seconds          = number
    notifier_verb    = string
    rule_description = string
  })
  default = null
}

variable "execution_policy" {
  description = "The execution role's policy document, rendered by the caller from the plane's own template: the union of every verb's needs."
  type        = string
}

variable "execution_policy_name" {
  description = "The execution role's inline policy name. Shared spaces' is \"orchestrator\"; a rename is a replacement."
  type        = string
  default     = "permissions"
}

variable "execution_role_name" {
  description = "Overrides the execution role's derived name. Shared spaces keeps its orchestrator role by name, because the Lake Formation admin list and the user-space bucket allowlist name it."
  type        = string
  default     = null
}

variable "distributed_map" {
  description = "Set when the definition runs a distributed map: the Step Functions role then starts and describes its child executions and reads and writes the manifest prefix in the admin bucket. The wildcard is passed as each plane builds it today."
  type = object({
    manifest_prefix              = string
    can_stop                     = bool
    child_execution_arn_wildcard = string
  })
  default = null
}

variable "admin_bucket_arn" {
  description = "The admin bucket, where a distributed map's manifests and results live."
  type        = string
}
