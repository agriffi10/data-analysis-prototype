#!/usr/bin/env bash
# Points every function the plan names at this run's image, DEPLOY_CONCURRENCY at a time, in ONE job.
#
# WHY ONE JOB RUNNING SEVERAL AT ONCE. A function's deploy is ~25s, nearly all of it spent in
# Lambda's waiters, and GitHub bills every job's wall clock rounded up to a minute. Six shard jobs
# each walking ~15 functions in sequence billed ~45 minutes a run to wait out ~90 updates; eight
# at a time in one job waits them out in about five and pays the rounding once. Eight concurrent
# updates is close to the six the shards already ran side by side, so the load on Lambda's API is
# about what it was: the waiters poll GetFunction, which has its own 100/s quota, and the handful of
# other calls a function makes share the account's 15/s control-plane pool.
#
# EVERY FUNCTION GETS ITS ATTEMPT, however many fail — a broken function must not hold back
# unrelated ones, and a failure that comes back in seconds (an apply rewriting a plane's env block
# fails every verb of that plane with a fast ResourceConflictException) costs nothing to repeat.
#
# THE JOB'S TIMEOUT IS THE COST BOUND, AND THERE IS DELIBERATELY NO EARLY STOP. When every function
# fails slowly — measured once: idle (Inactive) functions each failed the active waiter after ~6 min,
# a wait point-lambda.sh now skips for them, and six sequential shards ran to their 30-minute
# timeout, 188 billed minutes — eight at a time reaches the timeout in one job, and that is the
# bill. A stop after N failures was built and removed: at eight wide it saved ~3 minutes over the
# timeout, and every way of telling a systemic failure from a local one (any failure, a failure
# that took long) misjudged a real case — a fast conflict after a long wait for the image, a
# fleet-wide failure just under the threshold.
#
# Each function that lands is appended to the record file AS IT LANDS, and each function's log is
# printed the moment it finishes, so a job killed by its timeout still hands the reconciliation the
# partial truth and the reader every finished function's reason. Only the summary waits for the end.
#
# Usage: PLANNED='["api", ...]' deploy-fleet.sh <record-file>
# Exits 0 only when every planned function landed; otherwise 1, naming each that did not.
set -euo pipefail

RECORD="${1:?usage: deploy-fleet.sh <file to record each pointed function in>}"
CONCURRENCY="${DEPLOY_CONCURRENCY:-8}"
POINT="$(cd "$(dirname "$0")" && pwd)/point-lambda.sh"

# GNU `xargs -P 0` runs everything at once, and a non-number fails inside `xargs` after the plan
# has been accepted — refused here instead, before anything starts.
case "$CONCURRENCY" in
  '' | 0* | *[!0-9]*)
    echo "::error::DEPLOY_CONCURRENCY must be a whole number of at least 1."
    exit 1
    ;;
esac

# A read loop rather than `mapfile` (bash 4+), so the whole path can be dry-run on a Mac.
FUNCS=()
while IFS= read -r fn; do
  [ -n "$fn" ] && FUNCS+=("$fn")
done < <(jq -r '.[]' <<<"${PLANNED:?PLANNED must hold the planned function names as a JSON array}")

# "Did not run" is never "clean": an empty plan would start nothing and report success.
if [ "${#FUNCS[@]}" -eq 0 ]; then
  echo "::error::the deploy plan named no functions, so this run would point nothing and report success."
  exit 1
fi

# A name becomes a file name and an `xargs` argument below, so anything outside Lambda's own name
# alphabet is refused rather than quoted around.
for fn in "${FUNCS[@]}"; do
  case "$fn" in
    *[!A-Za-z0-9_-]*)
      echo "::error::refusing a planned name outside [A-Za-z0-9_-]. Lambda allows no other character, so the plan is wrong."
      exit 1
      ;;
  esac
done

# Two concurrent updates of one function race `update-function-code`, and the loser's waiter can
# return against the winner's version.
DUPLICATES=$(printf '%s\n' "${FUNCS[@]}" | sort | uniq -d | tr '\n' ' ')
if [ -n "$DUPLICATES" ]; then
  echo "::error::the deploy plan names these more than once, and two concurrent updates of one function race: ${DUPLICATES}"
  exit 1
fi

# The runner's own scratch directory when there is one, mktemp's default otherwise.
if [ -n "${RUNNER_TEMP:-}" ]; then
  WORK=$(mktemp -d "${RUNNER_TEMP}/deploy-fleet.XXXXXX")
else
  WORK=$(mktemp -d)
fi
trap 'rm -rf "$WORK"' EXIT
: > "$RECORD"
RECORD="$(cd "$(dirname "$RECORD")" && pwd)/$(basename "$RECORD")"

echo "Pointing ${#FUNCS[@]} functions, ${CONCURRENCY} at a time."

# One worker per function. It always exits 0 — its outcome is the marker file it leaves — because
# `xargs` stops launching altogether when a command exits 255, which `aws ... wait` does on timeout.
#
# Its log is assembled in a file and written out by ONE `cat` when the function finishes: a block
# under the pipe's 4 KB atomic-write size lands whole, so eight workers do not interleave their
# lines, and nothing waits for the end of the run to be printed.
# shellcheck disable=SC2016  # expanded by each worker, not here
WORKER='
name=$1
if bash "$POINT" "$name" > "$WORK/$name.log" 2>&1; then
  echo "$name" >> "$RECORD"
  : > "$WORK/$name.ok"
  mark="✓"
else
  : > "$WORK/$name.failed"
  mark="✗"
fi
{ echo "::group::${mark} ${name}"; cat "$WORK/$name.log"; echo "::endgroup::"; } > "$WORK/$name.out"
cat "$WORK/$name.out"
exit 0
'
export POINT WORK RECORD

RUNNER_STATUS=0
printf '%s\n' "${FUNCS[@]}" | xargs -n 1 -P "$CONCURRENCY" bash -c "$WORKER" worker || RUNNER_STATUS=$?

LANDED=()
FAILED=()
LOST=()
for NAME in "${FUNCS[@]}"; do
  if [ -e "$WORK/$NAME.ok" ]; then
    LANDED+=("$NAME")
  elif [ -e "$WORK/$NAME.failed" ]; then
    FAILED+=("$NAME")
  else
    LOST+=("$NAME")
  fi
done

STATUS=0
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "::error::${#FAILED[@]} function(s) failed to deploy: ${FAILED[*]}"
  STATUS=1
fi
# A worker killed by a signal makes `xargs` give up. GNU's exits at once without waiting for the
# rest, so functions still in flight then are named here even if they go on to land; `pointed` can
# only over-report them as un-pointed, never miss one.
if [ "${#LOST[@]}" -gt 0 ]; then
  echo "::error::no outcome was recorded for ${#LOST[@]} function(s), and the parallel runner exited ${RUNNER_STATUS}: ${LOST[*]}"
  STATUS=1
elif [ "$RUNNER_STATUS" -ne 0 ]; then
  echo "::error::the parallel runner exited ${RUNNER_STATUS} although every function has an outcome."
  STATUS=1
fi
if [ "$STATUS" -eq 0 ]; then
  echo "All ${#LANDED[@]} functions deployed."
fi
exit "$STATUS"
