# ── The image registry ────────────────────────────────────────────────────────
# One repository, holding one image: the SPA. The build that pushes to it is CI's;
# everything about how it is stored is here.
#
# IMMUTABLE TAGS ARE THE LOAD-BEARING SETTING. The deploy tags by commit sha and the task
# definition references that tag, so an image is what its tag says it is for as long as the
# revision exists. With mutable tags a re-push under an existing sha silently changes what a
# rolled-back task definition starts, and nothing in the state records it.

resource "aws_ecr_repository" "spa" {
  name                 = local.spa_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # AES256, not a CMK. Checkov reports the absence of a customer-managed key and it is a
  # deliberate no: the layers are a public SPA bundle, and a CMK here buys a key policy to
  # maintain rather than a secret to protect. The disposition is in docs/security-baseline.md
  # beside the other no-CMK entries.
  #
  # REVISITING IT IS A TWO-STEP once the repository holds an image: this block is ForceNew and
  # `force_delete` is deliberately unset, so the replacement fails at DeleteRepository until the
  # images are removed by hand. Deleting a registry full of deployed images should be a
  # deliberate act, not a side effect of an encryption change.
  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = { Name = local.spa_name }
}

# Bounded, so the registry does not grow one layer set per deploy forever. Untagged images
# go first and quickly: with IMMUTABLE tags an untagged image is one a later push orphaned,
# and nothing can reference it. The tagged rule keeps the last thirty, which is a rollback
# window measured in deploys rather than in days.
resource "aws_ecr_lifecycle_policy" "spa" {
  repository = aws_ecr_repository.spa.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after one day."
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the last thirty images."
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 30
        }
        action = { type = "expire" }
      },
    ]
  })
}
