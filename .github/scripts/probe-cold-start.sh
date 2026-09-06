#!/usr/bin/env bash
# Invokes each probed function once and proves the DEPLOYED artefact starts.
#
# WHAT THE SIGNAL IS. Three designs were tried; the first two were measured wrong rather than
# argued wrong, and the third was wrong for a reason no emulator can show.
#
# The subject is the cold start, not the handler: an invocation that returns a HANDLER error is a
# pass, because the handler running is the thing being proved.
#
#   1. `START RequestId` — written BEFORE init and regardless of its outcome, so it proves nothing.
#      It is also the first line, and `--log-type Tail` returns the last 4 KB, so a chatty function
#      loses it to truncation. Wrong in both directions.
#   2. `errorType` beginning `Runtime.` — an exception raised at import reports its own class
#      (`RuntimeError`), no prefix. That is the shape this fleet most invites, since
#      `observability.init` runs at module scope.
#   3. `REPORT RequestId` present — true under the runtime interface emulator, and FALSE in
#      production: AWS's own documented output for a `Runtime.ExitError` init failure carries
#      `START`, `END` and `REPORT`. The emulator diverges on this path in ways that are visible
#      from here (it answers 502 with no `X-Amz-Function-Error`; production answers 200 with one),
#      so it cannot be trusted about it.
#
# WHAT IS UNAMBIGUOUS IN BOTH WORLDS, and is therefore what this checks:
#
#   * an `errorType` under `Runtime.` — the runtime saying directly that it could not run the
#     handler;
#   * `Status: error` in the log — a field Lambda writes into `REPORT`/`INIT_REPORT` only when a
#     phase FAILED. It never appears on a healthy invocation, so it cannot redden a good deploy;
#   * the absence of a `REPORT` line at all — nothing completed.
#
# `INIT_REPORT` presence is deliberately NOT a signal. Some runtimes emit it on every cold start,
# so failing on it would turn every deploy red — the wrong direction entirely.
#
# THE RESIDUAL, recorded in docs/testing/owed.md with the one command that settles it: an
# old-style `REPORT` line carries no `Status` field, so an init failure whose errorType is not
# under `Runtime.` and whose log is old-style would pass. Nothing here can settle which format
# this account emits; the first green run's output is what does.
#
# `aws lambda invoke` EXITS 0 ON A FUNCTION ERROR — the status code is 200 and the error rides in a
# header — so nothing here reads its exit status as a verdict.
#
# Required env: PROJECT_NAME, ENVIRONMENT. Reads .github/lambda-probes.json.
set -euo pipefail

TABLE="${PROBE_TABLE:-$(dirname "$0")/../lambda-probes.json}"
[ -f "$TABLE" ] || { echo "::error::$TABLE is missing; the probe has no population."; exit 1; }

NAMES=()
while IFS= read -r name; do
  [ -n "$name" ] && NAMES+=("$name")
done < <(jq -r '.probe[]' "$TABLE")

# "Did not run" is never "clean". A table that parsed to nothing would otherwise loop zero times
# and report success over an empty population.
EXPECTED=$(jq '.probe | length' "$TABLE")
if [ "${#NAMES[@]}" -eq 0 ] || [ "${#NAMES[@]}" -ne "$EXPECTED" ]; then
  echo "::error::read ${#NAMES[@]} probe names but the table declares ${EXPECTED}. Refusing to report a pass over a population this script could not read."
  exit 1
fi

FAILED=()
STARTED=0

for NAME in "${NAMES[@]}"; do
  FUNCTION="${PROJECT_NAME}-${ENVIRONMENT}-${NAME}"
  PAYLOAD_FILE="$(mktemp)"
  # PRIVATE, not a fixed name: this script is executed by `lambdas/test_probe_cold_start.py`,
  # and a fixed path is one file shared by every run of the suite on the machine — a second
  # run truncating it while this one reads it back turns a real diagnosis into an empty one.
  STDERR_FILE="$(mktemp)"
  echo "::group::${NAME}"

  # A function still settling answers 409, which would land in the "could not be invoked" branch as
  # a red build for a fleet that is fine. `pointed` waits per function, but an infra apply between
  # the two jobs can put one back into Pending.
  aws lambda wait function-active-v2 --function-name "$FUNCTION" 2>/dev/null || true

  # An empty payload. Every probed function either refuses it after import or does its ordinary
  # scheduled work; the one that would MUTATE on it is exempted in the table, with the reason.
  #
  # stderr is kept SEPARATE from the captured JSON: folding it in with 2>&1 would let any CLI
  # warning corrupt the parse and be reported as a function that did not start.
  if ! META=$(aws lambda invoke \
        --function-name "$FUNCTION" \
        --payload '{}' \
        --cli-binary-format raw-in-base64-out \
        --log-type Tail \
        --output json \
        "$PAYLOAD_FILE" 2>"$STDERR_FILE"); then
    echo "::error::${FUNCTION} could not be invoked: $(cat "$STDERR_FILE")"
    FAILED+=("${NAME} (invoke failed)")
    rm -f "$PAYLOAD_FILE" "$STDERR_FILE"; echo "::endgroup::"; continue
  fi

  # `// empty` rather than a default string: the AWS CLI prints the literal `None` for an absent
  # field under `--output text`, and `None` is valid base64. Reading this as JSON avoids that
  # entirely, and an absent LogResult stays absent.
  LOG=$(jq -r '.LogResult // empty' <<<"$META" | base64 --decode 2>/dev/null || true)
  ERROR_KIND=$(jq -r '.FunctionError // empty' <<<"$META")
  ERROR_TYPE=$(jq -r '.errorType // empty' "$PAYLOAD_FILE" 2>/dev/null || true)
  rm -f "$PAYLOAD_FILE" "$STDERR_FILE"

  if [ -z "$ERROR_KIND" ]; then
    # It returned a result, so the handler ran. No log needed to conclude that.
    echo "✓ ${NAME}: returned without error, so the handler ran"
    STARTED=$((STARTED + 1))
  elif [[ "$ERROR_TYPE" == Runtime.* ]]; then
    echo "::error::${FUNCTION} did not start: ${ERROR_TYPE}. The runtime could not reach the handler. Log tail:"
    printf '%s\n' "$LOG"
    FAILED+=("${NAME} (${ERROR_TYPE})")
  elif grep -q 'Status: error' <<<"$LOG"; then
    # Lambda writes this into REPORT/INIT_REPORT only when a phase failed, so it is a positive
    # statement of failure rather than an inference from an absence.
    echo "::error::${FUNCTION} reported a failed phase (Status: error) — the container did not start. errorType: ${ERROR_TYPE:-none}. Log tail:"
    printf '%s\n' "$LOG"
    FAILED+=("${NAME} (phase failed)")
  elif grep -qE '^REPORT RequestId' <<<"$LOG"; then
    # ANCHORED. Unanchored, a traceback quoting the string passes — measured on a real container
    # whose import error embedded a log line. The anchor also excludes INIT_REPORT, which is a
    # different line with a different meaning.
    #
    # The handler ran and raised, which is what an empty payload is for. The type is PRINTED
    # rather than swallowed, so a new failure mode is visible before it is understood.
    echo "✓ ${NAME}: handler ran and refused the payload (${ERROR_TYPE:-no type})"
    STARTED=$((STARTED + 1))
  else
    echo "::error::${FUNCTION} errored with no REPORT line, so the invocation never completed through the runtime — the container did not start. errorType: ${ERROR_TYPE:-none}. Log tail:"
    printf '%s\n' "$LOG"
    FAILED+=("${NAME} (${ERROR_TYPE:-no REPORT})")
  fi
  echo "::endgroup::"
done

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "::error::${#FAILED[@]} of ${#NAMES[@]} probed functions did not start: ${FAILED[*]}"
  exit 1
fi

echo "All ${#NAMES[@]} probed functions reached their handler (${STARTED} confirmed)."
if [ "$STARTED" -ne "${#NAMES[@]}" ]; then
  echo "::error::the count above does not add up: ${STARTED} confirmed of ${#NAMES[@]} with no failures recorded, which means a branch fell through without deciding."
  exit 1
fi
