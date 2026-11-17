variable "project_name" {
  description = "Short name used as a prefix for AWS resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names."
  type        = string
}

variable "aws_region" {
  description = "Region the cluster and the load balancer live in."
  type        = string
}

variable "account_id" {
  description = "Account the resources are created in. Passed in rather than read from a data source here: this module carries a depends_on, and a module-level depends_on defers every data source inside it."
  type        = string
}

variable "vpc_id" {
  description = "VPC holding the load balancer's subnets and both security groups."
  type        = string
}

variable "public_subnet_ids" {
  description = "Subnets the internet-facing load balancer is placed in."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Subnets the tasks run in. No default route reaches the internet from any of them, which is what makes assign_public_ip = false load-bearing rather than decorative."
  type        = list(string)
}

variable "task_security_group_id" {
  description = "The task security group, created by the network module with NO rules. Every rule names a group this module also names, so all of them are declared here."
  type        = string
}

variable "vpc_endpoint_security_group_id" {
  description = "The interface endpoints' group — the destination of the task's only port-443 egress allowance. Its reciprocal ingress rule is declared in the network module beside the endpoints and must NOT be re-declared here (InvalidPermission.Duplicate)."
  type        = string
}

variable "s3_prefix_list_id" {
  description = "The S3 gateway endpoint's managed prefix list. The task's egress to S3 must name it: a CIDR egress rule does not match gateway-endpoint traffic, and the failure is an image pull that hangs rather than one that refuses."
  type        = string
}

variable "spa_host" {
  description = "Hostname the container answers on, without scheme. Built at root from the domain variables and passed down — never derived here."
  type        = string
}

variable "spa_certificate_arn" {
  description = "Regional ACM certificate for spa_host. Fed from the certificate VALIDATION resource, not the certificate itself: both carry the same ARN, but only the validation creates the edge that stops a clean rebuild attaching a PENDING_VALIDATION certificate to the listener."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone that answers for the parent domain, carrying this host's A-alias record."
  type        = string
}

variable "admin_bucket_name" {
  description = "The Athena admin bucket, which takes the load balancer's access logs under alb-access-logs/. This module writes that bucket's FIRST policy."
  type        = string
}

variable "access_logs_prefix" {
  description = "Prefix in the admin bucket the load balancer writes access logs under, decided at root because the module that owns the bucket's lifecycle rules must expire the same prefix. ALB appends its own AWSLogs/{account}/ beneath it."
  type        = string
}

variable "elb_account_arn" {
  description = "The load-balancing service's own account in this region, as an ARN — the older of the two delivery identities the access-log bucket policy grants. Which one AWS actually delivers as here was not isolated, so both are granted and narrowing to one is owed a live check."
  type        = string
}

variable "desired_count" {
  description = "Tasks the service runs. Zero here so the first apply creates a service before any image exists; the deploy that pushes an image raises it."
  type        = number
}

variable "runtime_config" {
  description = "The runtime configuration document's keys and their values, from root. Rendered into the task environment as CONFIG_<key> — one entry per key, never hand-listed here, so a key added to the classification cannot be half-wired. The portal's classification owns which keys exist; this module owns the block."
  type        = map(string)
}

variable "session_environment" {
  description = "The portal server's session settings, from root, rendered into the task environment under exactly these names. Server-only: none may be a CONFIG_ key, which would put it in the browser's document, and the client secret is not among them (it arrives through `secrets`)."
  type        = map(string)

  validation {
    condition = alltrue([
      for key in keys(var.session_environment) :
      !startswith(key, "CONFIG_") && !strcontains(upper(key), "SECRET")
    ])
    error_message = "session_environment may hold no CONFIG_ key and no secret; the secret reaches the task through client_secret_parameter_arn."
  }

  validation {
    condition     = contains(keys(var.session_environment), "SESSION_TABLE_NAME")
    error_message = "session_environment must name SESSION_TABLE_NAME, the table the server keeps sessions in."
  }
}

variable "client_secret_parameter_arn" {
  description = "The SSM SecureString holding the confidential client's secret, injected as OIDC_CLIENT_SECRET at task start. Built at root from the parameter's name, so the plan knows it."
  type        = string
}

variable "session_table_arn" {
  description = "The session table the task role may use. Built at root from the table's name, so the plan-time IAM scan can read the grant."
  type        = string
}

variable "dynamodb_prefix_list_id" {
  description = "The DynamoDB gateway endpoint's managed prefix list, from `network`, which the task's egress to the session store names."
  type        = string
}

variable "csp_connect_src" {
  description = "The whole connect-src source list, built at root and carried to the container as PORTAL_CSP_CONNECT_SRC. It is computed at root rather than here because root is where the origins are built — it fed both delivery paths while there were two, and feeds the only one now."
  type        = string
}

variable "task_cpu" {
  description = "Fargate CPU units for the task. The smallest valid pairing for a static-asset server."
  type        = string
  default     = "256"
}

variable "task_memory" {
  description = "Fargate memory (MiB) for the task."
  type        = string
  default     = "512"
}

variable "container_port" {
  description = "Port the container listens on. 8080 because the image sets PORT=8080 and runs as an unprivileged user, which cannot bind below 1024; the image and the target group must agree."
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "Path the target group polls. What it serves belongs to the image; that it is this path is agreed between the image and this module, and asserted by test."
  type        = string
  default     = "/healthz"
}

variable "repository_url" {
  description = "The registry the task definition pulls from. It lives in the spa-image module rather than here so it outlives the web tier's off switch."
  type        = string
}

variable "repository_arn" {
  description = "The same registry's ARN, which the execution role's pull grant is scoped to."
  type        = string
}

variable "image_tag" {
  description = "Tag of the image the task definition references. The registry is IMMUTABLE, so there is no :latest to point at and no tag that can be re-pushed after a bad build — the tag is the commit sha of the image CI pushed, and the placeholder default exists only so the first apply can create a task definition before any image does. Supplied as a repo variable, like every other environment fact."
  type        = string
  default     = "placeholder"

  validation {
    # An empty repo variable renders as the empty string, which satisfies a required variable
    # AND overrides a default — so the guard is on the VALUE, not on its presence.
    condition     = can(regex("^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$", var.image_tag))
    error_message = "image_tag must be a valid ECR tag: it starts with a letter, digit or underscore, continues with those plus dot and hyphen, and is at most 128 characters. ECR refuses a leading dot or hyphen."
  }
}
