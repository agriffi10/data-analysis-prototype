terraform {
  backend "s3" {
    # The state bucket and DynamoDB lock table must be created before running `tofu init`.
    # All connection values are supplied via backend.conf (gitignored — never committed).
    # Run: tofu init -backend-config=backend.conf
    # See infra/bootstrap/README.md for setup instructions and backend.conf.example.
    key     = "s3-upload-portal/terraform.tfstate"
    encrypt = true
  }
}
