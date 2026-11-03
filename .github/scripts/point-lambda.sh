#!/usr/bin/env bash
# Points ONE Lambda at the fleet's container image.
#
# THE ZIP BRANCH IS GONE, and the live `PackageType` read that dispatched to it is now a REFUSAL.
# It existed for the cutover: while an 86-function replacement could fail partway, a pipeline that
# spoke only `--image-uri` would have left main holding a mixed fleet it could not deploy. That
# apply completed, every function is Image-packaged, and a zip function reappearing is a fact
# somebody needs told rather than something to deploy around.
#
# Required env: PROJECT_NAME, ENVIRONMENT, GITHUB_SHA. IMAGE_TAG is optional and overrides the sha —
# it is the rollback: point the fleet at a tag the registry already holds, with no code change.
set -euo pipefail

NAME="${1:?usage: point-lambda.sh <function-name>}"
FUNCTION="${PROJECT_NAME}-${ENVIRONMENT}-${NAME}"

# The rollback tag is refused HERE TOO, before anything waits on it: this script looks it up and
# prints it once per function, so it does not lean on its caller having checked the shape.
bash "$(dirname "$0")/check-image-tag.sh" "${IMAGE_TAG:-}"

# ── The function has to exist, and be idle ────────────────────────────────────
# Deploy Infrastructure and Deploy Lambdas fire on the same push, so this can win the race. Both
# waits are inherited from the zip pipeline rather than reasoned about again: a just-created
# function sits in Pending, and update-function-code against it is a ResourceConflictException
# (hit on SPEC-088). `PackageType` being Image does NOT imply State Active, and a container
# function's create is slower than a zip's — the cutover is the run most likely to prove it.
for attempt in $(seq 1 30); do
  if aws lambda get-function --function-name "$FUNCTION" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "::error::Function ${FUNCTION} not ready after ~5 min. Run Deploy Infrastructure first."
    exit 1
  fi
  echo "Waiting for ${FUNCTION} (attempt ${attempt}/30)…"
  sleep 10
done

# NOT FOR AN INACTIVE ONE. Lambda parks a function idle for a few weeks as Inactive, and nothing but
# an invoke or this update wakes it, so the waiter would spend its five minutes and fail on every
# function in the fleet, and the deploy would spend its whole timeout on them, pointing only the
# functions that were not idle.
STATE=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query 'State' --output text)
if [ "$STATE" != "Inactive" ]; then
  aws lambda wait function-active-v2 --function-name "$FUNCTION"
fi

PACKAGE_TYPE=$(aws lambda get-function --function-name "$FUNCTION" \
  --query 'Configuration.PackageType' --output text)

if [ "$PACKAGE_TYPE" != "Image" ]; then
  echo "::error::${FUNCTION} reports PackageType '${PACKAGE_TYPE}', and this pipeline only deploys Image. A function that is not container-packaged cannot be pointed at an image, and deploying it some other way is not a decision to make here."
  exit 1
fi

# ── Which image ───────────────────────────────────────────────────────────────
# IMAGE_TAG defaults to this commit. Supplying one is the rollback, and it is the only lever that
# needs to exist: the registry is immutable and tagged by sha, so naming a previous sha names
# exactly the artefact that ran then.
TAG="${IMAGE_TAG:-$GITHUB_SHA}"

REPOSITORY_NAME="${PROJECT_NAME}-${ENVIRONMENT}-lambda"
if ! REPOSITORY=$(aws ecr describe-repositories --repository-names "$REPOSITORY_NAME" \
                    --query 'repositories[0].repositoryUri' --output text 2>/dev/null); then
  echo "::error::no repository named ${REPOSITORY_NAME}. Terraform builds it from project_name and environment."
  exit 1
fi

# The image for THIS commit is built by a workflow that fires on the same push, so the tag may not
# be in the registry yet. Bounded, and the error names the workflow to look at rather than the
# function — pointing at a tag that does not exist fails with a message about the image.
for attempt in $(seq 1 30); do
  if aws ecr describe-images --repository-name "$REPOSITORY_NAME" \
       --image-ids "imageTag=${TAG}" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "::error::${REPOSITORY_NAME}:${TAG} is not in the registry after ~5 min. Check the 'Deploy Lambda image' run for this commit."
    exit 1
  fi
  echo "Waiting for ${REPOSITORY_NAME}:${TAG} (attempt ${attempt}/30)…"
  sleep 10
done

TARGET="${REPOSITORY}:${TAG}"
echo "${NAME}: Image-packaged, pointing at ${TARGET}"

aws lambda update-function-code \
  --function-name "$FUNCTION" \
  --image-uri "$TARGET" \
  --publish >/dev/null

# A container function's update is ASYNCHRONOUS. Returning on the API call alone reports a deploy
# that has not happened.
#
# THE WAITER IS RUN UNDER `if !`, NOT BARE, and that is the difference between a legible failure
# and a useless one. `function-updated-v2` has a terminal FAILURE state on
# `LastUpdateStatus == "Failed"`, so it exits non-zero — and under this file's `set -e` a bare call
# would abort the script right here, leaving the read below unreachable in exactly the case it was
# written for. The operator would get botocore's "Waiter FunctionUpdatedV2 failed: Waiter
# encountered a terminal failure state" instead of the reason AWS supplied, on the failure this arc
# is most likely to hit: a bad manifest, an architecture mismatch, an image that will not start.
if ! aws lambda wait function-updated-v2 --function-name "$FUNCTION"; then
  STATUS=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
    --query 'LastUpdateStatus' --output text 2>/dev/null || echo "unknown")
  REASON=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
    --query 'LastUpdateStatusReason' --output text 2>/dev/null || true)
  echo "::error::${FUNCTION} finished its update as ${STATUS}: ${REASON}"
  exit 1
fi

# Belt as well as braces: a waiter that returned success has not necessarily left the function
# Successful (it also accepts on a state this script does not enumerate), so the status is read.
STATUS=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query 'LastUpdateStatus' --output text)
if [ "$STATUS" != "Successful" ]; then
  REASON=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
    --query 'LastUpdateStatusReason' --output text 2>/dev/null || true)
  echo "::error::${FUNCTION} finished its update as ${STATUS}: ${REASON}"
  exit 1
fi

# An update is what wakes an idle function, and a Successful status does not say it woke: the
# function would report this deploy as landed and fail its first invoke. Read rather than waited on
# when still Inactive, because the waiter would spend five minutes finding that out, per function.
STATE=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query 'State' --output text)
if [ "$STATE" = "Inactive" ]; then
  echo "::error::${FUNCTION} is still Inactive after an update that finished as Successful."
  exit 1
fi
aws lambda wait function-active-v2 --function-name "$FUNCTION"

# READ THE EFFECT BACK, not the exit status of the call that asked for it. `Code.ImageUri` carries
# the TAG that was requested; `Code.ResolvedImageUri` carries the digest it resolved to, which
# never equals what we asked for and would fail this comparison on every function.
LANDED=$(aws lambda get-function --function-name "$FUNCTION" \
  --query 'Code.ImageUri' --output text)
if [ "$LANDED" != "$TARGET" ]; then
  echo "::error::${FUNCTION} reports image ${LANDED} after an update that asked for ${TARGET}."
  exit 1
fi

echo "✓ ${NAME} → ${TAG}"
