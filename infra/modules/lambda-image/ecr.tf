# ── The Lambda image's registry ───────────────────────────────────────────────
# One image for the whole Lambda fleet, tagged by commit sha, and every function runs it. A
# repository of its own rather than a shelf in the SPA's: the two have different lifecycles, and a
# shared repository would make one's expiry policy the other's problem — the SPA rolls back in
# deploys, the fleet rolls back in days.
#
# IMMUTABLE TAGS ARE THE LOAD-BEARING SETTING, for the reason the SPA's repository states: the
# deploy tags by commit sha, so with mutable tags a re-push under an existing sha silently changes
# what a rolled-back function starts, and nothing in the state records it. There is no :latest.

resource "aws_ecr_repository" "lambda" {
  name                 = local.image_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # AES256, not a CMK — the same deliberate no the SPA's repository takes, dispositioned once in
  # docs/security-baseline.md. Answering it differently here would be a second answer to one
  # question. REVISITING IT IS A FORCE-NEW, and force_delete is deliberately unset, so the
  # replacement fails at DeleteRepository until the images are removed by hand.
  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = { Name = local.image_name }
}

# The retention bound is COMPUTED, not chosen — lambdas/test_lambda_image_lifecycle.py derives it
# from the merge rate this repository sustains and the rollback window it is meant to cover, and
# fails if the two disagree. A number picked by eye hides whatever model produced it. The rate is
# derived from recorded commit counts rather than restated, so lowering it means falsifying a
# measurement rather than retyping a number.
#
# ONE INTERACTION THIS BOUND DOES NOT SEE: an untagged image still occupies a slot in the count
# below even though rule 1 is the only rule that may expire it. That is zero today, because the
# build is a plain single-platform `docker build` into an immutable repository — nothing orphans a
# tag and nothing writes a manifest list. `docker buildx` would change that: its default
# provenance attestations arrive as untagged manifests, roughly one per push, and would quietly
# take the effective tagged bound below what this test computes.
#
# What makes a generous bound cheap: ECR de-duplicates layers within a repository, and the
# dependency layer is identical across builds that do not touch a requirements file. The marginal
# cost of the Nth image is its code layer, which is single-digit megabytes.
#
# THE UNTAGGED RULE IS NOT ABOUT RE-PUSHED TAGS. Under IMMUTABLE a push cannot take an existing
# tag at all — PutImage refuses it — so nothing is orphaned that way. What it catches is an image
# index's untagged children and a deliberate tag deletion. README.md.
resource "aws_ecr_lifecycle_policy" "lambda" {
  repository = aws_ecr_repository.lambda.name

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
        description  = "Keep five days of pushes at the busiest sustained merge rate."
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 75
        }
        action = { type = "expire" }
      },
    ]
  })
}
