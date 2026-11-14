# ── The image registry ────────────────────────────────────────────────────────
# OUTSIDE the spa module because the web tier has an off switch and this must outlive it: a
# registry destroyed with the tier takes every image with it, and force_delete is unset.
#
# IMMUTABLE TAGS ARE THE LOAD-BEARING SETTING. The deploy tags by commit sha, so with mutable
# tags a re-push under an existing sha silently changes what a rolled-back task definition
# starts — and nothing in the state records it. There is no :latest. README.md.

resource "aws_ecr_repository" "spa" {
  name                 = local.image_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # AES256, not a CMK — a deliberate no, dispositioned in docs/security-baseline.md.
  # REVISITING IT IS A TWO-STEP once images exist: ForceNew, with force_delete deliberately
  # unset, so the replacement fails at DeleteRepository until they are removed by hand.
  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = { Name = local.image_name }
}

# With IMMUTABLE tags and single-manifest pushes (both SPA builds pass --provenance=false
# --sbom=false), an untagged image is one nothing references. Thirty images is then a rollback
# window of thirty deploys; an index push would spend three slots per deploy on itself and its
# untagged children.
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
