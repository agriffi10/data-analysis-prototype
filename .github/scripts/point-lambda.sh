#!/usr/bin/env bash
# Deploys ONE Lambda's code, whichever way that function is packaged.
#
# WHY THIS DISPATCHES RATHER THAN REPLACING deploy-lambda.sh. The cutover changes 86 functions in a
# single apply, and an apply can fail partway. If the pipeline spoke only `--image-uri`, a
# half-finished cutover would leave main holding a mixed fleet with no pipeline able to deploy the
# zip half — and the revert would not recover it either, since `update-function-code --s3-bucket`
# against an Image function is an InvalidParameterValueException. Reading the LIVE package type
# costs one field of a call this script already makes, and it means the cutover push needs no
# pipeline change at all: this file lands first, its zip branch exercised against the real fleet on
# merge, and the image branch takes over per function as Terraform replaces it.
#
# The zip branch is not reimplemented here. It execs deploy-lambda.sh, which owns the package
# build, the combined size guard, the artifact upload and the layer attachment — and which
# lambdas/test_deploy_packaging.py drives directly by extracting its copy block and RUNNING it.
# Rewriting that logic here would leave that suite testing a file nothing calls.
#
# Required env: PROJECT_NAME, ENVIRONMENT, GITHUB_SHA. The zip branch additionally needs BUCKET and
# LAYERS_JSON, which it validates itself.
set -euo pipefail

NAME="${1:?usage: point-lambda.sh <function-name>}"
FUNCTION="${PROJECT_NAME}-${ENVIRONMENT}-${NAME}"

# ── The function has to exist, and be idle ────────────────────────────────────
# Deploy Infrastructure and Deploy Lambdas fire on the same push, so this can win the race. Both
# waits are inherited from deploy-lambda.sh rather than reasoned about again: a just-created
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
aws lambda wait function-active-v2 --function-name "$FUNCTION"

PACKAGE_TYPE=$(aws lambda get-function --function-name "$FUNCTION" \
  --query 'Configuration.PackageType' --output text)

if [ "$PACKAGE_TYPE" = "Zip" ]; then
  echo "${NAME}: Zip-packaged, deploying through deploy-lambda.sh"
  exec bash "$(dirname "$0")/deploy-lambda.sh" "$NAME"
fi

if [ "$PACKAGE_TYPE" != "Image" ]; then
  echo "::error::${FUNCTION} reports PackageType '${PACKAGE_TYPE}', which is neither Zip nor Image. Refusing to guess."
  exit 1
fi

# ── The image branch ──────────────────────────────────────────────────────────
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
       --image-ids "imageTag=${GITHUB_SHA}" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "::error::${REPOSITORY_NAME}:${GITHUB_SHA} is not in the registry after ~5 min. Check the 'Deploy Lambda image' run for this commit."
    exit 1
  fi
  echo "Waiting for ${REPOSITORY_NAME}:${GITHUB_SHA} (attempt ${attempt}/30)…"
  sleep 10
done

TARGET="${REPOSITORY}:${GITHUB_SHA}"
echo "${NAME}: Image-packaged, pointing at ${TARGET}"

aws lambda update-function-code \
  --function-name "$FUNCTION" \
  --image-uri "$TARGET" \
  --publish >/dev/null

# A container function's update is ASYNCHRONOUS. Returning on the API call alone reports a deploy
# that has not happened — the waiter fails on LastUpdateStatus Failed rather than timing out.
aws lambda wait function-updated-v2 --function-name "$FUNCTION"

STATUS=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query 'LastUpdateStatus' --output text)
if [ "$STATUS" != "Successful" ]; then
  REASON=$(aws lambda get-function-configuration --function-name "$FUNCTION" \
    --query 'LastUpdateStatusReason' --output text 2>/dev/null || true)
  echo "::error::${FUNCTION} finished its update as ${STATUS}: ${REASON}"
  exit 1
fi

# READ THE EFFECT BACK, not the exit status of the call that asked for it. `Code.ImageUri` carries
# the TAG that was requested; `Code.ResolvedImageUri` carries the digest it resolved to, which
# never equals what we asked for and would fail this comparison on every function.
LANDED=$(aws lambda get-function --function-name "$FUNCTION" \
  --query 'Code.ImageUri' --output text)
if [ "$LANDED" != "$TARGET" ]; then
  echo "::error::${FUNCTION} reports image ${LANDED} after an update that asked for ${TARGET}."
  exit 1
fi

echo "✓ ${NAME} → ${GITHUB_SHA}"
