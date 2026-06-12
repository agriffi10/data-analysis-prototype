variable "bucket_name" {
  description = "Globally-unique name for the Lambda deployment artifacts bucket. Computed in the root module and passed both here (creation) and to the base module's deploy policy (scoping), avoiding a base<->this dependency cycle."
  type        = string
}
