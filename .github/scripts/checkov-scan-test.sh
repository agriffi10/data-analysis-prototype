#!/usr/bin/env bash
#
# The fixture corpus for checkov-scan.sh and for the two numerators' refusal of a skipped
# finding. It runs against the INSTALLED Checkov, in each job whose gate relies on them,
# before that job's scans.
#
# A refusal is the half of the wrapper that no ordinary run exercises. In CI there is never a
# config file to refuse, so a refusal that stopped firing, for instance because a ConfigArgParse
# release stopped recording a config file that Checkov still reads, would look exactly like a
# clean scan. This corpus plants configuration in each place Checkov reports taking it from (a
# config file in the working directory, the -d directory or $HOME, and a flag's environment
# variable) and asserts the REASON: the wrapper names the planted source, prints nothing a
# caller could parse, and the plan gate's numerator refuses what it left behind. The clean cases
# assert the other direction. With nothing planted, the fixture's finding is reported by its
# check ID, so a wrapper that refused everything fails here too.
#
# The wrapper cannot see a suppression written inside a scanned file: an inline
# `checkov:skip=<ID>` comment, which Checkov records as SKIPPED rather than failed. The
# numerators refuse those instead, and the last cases plant one for each gate and assert the
# refusal names the check ID and the resource. One case asserts silence: a skip of an ID the
# gate does not hold changes nothing. Each first asserts that Checkov recorded the planted
# skip, so a scanner that stopped honouring the comment fails here rather than passing a case
# that no longer plants anything.
#
# Every case runs with HOME pointed at an empty directory, so a config in the real home
# directory cannot decide a case that is not about it.
#
# Usage: checkov-scan-test.sh   (with checkov on PATH)
# Exit: 0 when every case holds, 1 when any does not, 2 when the corpus could not run.

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
scan="$here/checkov-scan.sh"
narrow="$here/checkov-plan-iam.sh"
enforced="$here/checkov-enforced.sh"

command -v checkov >/dev/null 2>&1 || {
  echo "::error title=Checkov corpus::checkov is not installed. The corpus did not run, which is not a pass." >&2
  exit 2
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/plan" "$work/elsewhere" "$work/home" "$work/planted-home" "$work/stub" \
  "$work/tf" "$work/docker" "$work/enrich"
: > "$work/accepted.txt"

# One policy granting s3:GetObject on every resource. Checkov 3.3.9 reports CKV_AWS_355 (a
# restrictable action on "*") and CKV_AWS_288 against it, and every plant below skips
# CKV_AWS_355. The clean case asserts that ID is reported, which is what makes a plant's
# refusal mean something.
cat > "$work/plan/plan.json" <<'EOF'
{
  "format_version": "1.2",
  "terraform_version": "1.8.8",
  "planned_values": {
    "root_module": {
      "resources": [
        {
          "address": "aws_iam_policy.wild",
          "mode": "managed",
          "type": "aws_iam_policy",
          "name": "wild",
          "provider_name": "registry.opentofu.org/hashicorp/aws",
          "values": {
            "name": "wild",
            "policy": "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\"],\"Resource\":\"*\"}]}"
          }
        }
      ]
    }
  }
}
EOF
skip='skip-check:
  - CKV_AWS_355
'

failures=0
fail() { echo "::error title=Checkov corpus::$1" >&2; failures=$((failures + 1)); }

# Runs the wrapper from a directory, with HOME and any extra environment given as NAME=value
# words before `--`. Leaves the exit status in $rc, stdout in $work/out and stderr in $work/err.
run() {
  local dir="$1"; shift
  local env=()
  while [ "$1" != "--" ]; do env+=("$1"); shift; done
  shift
  rc=0
  # The `+` form, because bash 3.2 treats an empty array as unset under `set -u`.
  (cd "$dir" && env HOME="$work/home" ${env[@]+"${env[@]}"} "$scan" "$@") > "$work/out" 2> "$work/err" || rc=$?
}

expect_refusal() {
  local case="$1" needle="$2"
  if [ "$rc" -ne 2 ]; then
    fail "$case: the wrapper exited $rc, not 2. The planted configuration was not refused."
  elif [ -s "$work/out" ]; then
    fail "$case: the wrapper refused but wrote to stdout, which a caller could parse as a scan."
  elif ! grep -qF -- "$needle" "$work/err"; then
    fail "$case: the wrapper refused without naming ${needle}. Its reason was: $(head -c 600 "$work/err")"
  else
    echo "ok - $case"
  fi
}

plan_args=(-f plan.json --framework terraform_plan --output json --compact --soft-fail)

# Clean, -f: no refusal, and the fixture's finding comes through the wrapper and the numerator
# by its check ID.
run "$work/plan" -- "${plan_args[@]}"
if [ "$rc" -ne 0 ]; then
  fail "clean -f scan: the wrapper exited $rc with nothing planted. $(head -c 600 "$work/err")"
elif ! jq -e '(if type=="array" then .[0] else . end) | [.results.failed_checks[]? | select(.check_id == "CKV_AWS_355" and .resource == "aws_iam_policy.wild")] | length == 1' "$work/out" >/dev/null 2>&1; then
  fail "clean -f scan: CKV_AWS_355 on aws_iam_policy.wild was not reported, so the fixture no longer proves what a plant hides."
elif ! "$narrow" "$work/out" "$work/accepted.txt" 2> "$work/narrow-err" > /dev/null \
    || ! grep -qF "CKV_AWS_355 on aws_iam_policy.wild" "$work/narrow-err"; then
  fail "clean -f scan: the plan gate's numerator did not report CKV_AWS_355 on aws_iam_policy.wild. $(head -c 600 "$work/narrow-err")"
else
  echo "ok - clean -f scan reports CKV_AWS_355 by its check ID"
fi

# Clean, -d: the directory form, which the .tf scan uses, is not refused when nothing is planted.
run "$work/elsewhere" -- -d "$work/plan" --framework terraform_plan --output json --compact --soft-fail
if [ "$rc" -ne 0 ]; then
  fail "clean -d scan: the wrapper exited $rc with nothing planted. $(head -c 600 "$work/err")"
elif ! jq -e '(if type=="array" then .[0] else . end) | [.results.failed_checks[]?.check_id] | index("CKV_AWS_355")' "$work/out" >/dev/null 2>&1; then
  fail "clean -d scan: CKV_AWS_355 was not reported."
else
  echo "ok - clean -d scan reports CKV_AWS_355"
fi

# The reported case: a config in the working directory. The numerator must refuse the empty
# output rather than count it as zero.
printf '%s' "$skip" > "$work/plan/.checkov.yml"
cwd=$(cd "$work/plan" && pwd -P)
run "$work/plan" -- "${plan_args[@]}"
expect_refusal "config in the working directory" "Config File ($cwd/.checkov.yml)"
nrc=0
"$narrow" "$work/out" "$work/accepted.txt" > "$work/narrow-out" 2> "$work/narrow-err" || nrc=$?
if [ "$nrc" -ne 2 ] || [ -s "$work/narrow-out" ] || ! grep -qF "holds no Checkov result" "$work/narrow-err"; then
  fail "numerator on a refused scan: exited $nrc and printed '$(cat "$work/narrow-out")'. It must refuse output that holds no scan, not count it."
else
  echo "ok - the numerator refuses what a refused scan left behind"
fi
rm "$work/plan/.checkov.yml"

# A config in the directory named by -d, with the working directory elsewhere. The .yaml
# spelling, so both names Checkov reads are planted somewhere in this corpus.
printf '%s' "$skip" > "$work/plan/.checkov.yaml"
run "$work/elsewhere" -- -d "$work/plan" --framework terraform_plan --output json --compact --soft-fail
expect_refusal "config in the -d directory" "Config File ($work/plan/.checkov.yaml)"
rm "$work/plan/.checkov.yaml"

# A config in the home directory.
printf '%s' "$skip" > "$work/planted-home/.checkov.yml"
run "$work/plan" HOME="$work/planted-home" -- "${plan_args[@]}"
expect_refusal "config in the home directory" "Config File ($work/planted-home/.checkov.yml)"

# A flag's environment variable.
run "$work/plan" CKV_SKIP_CHECK=CKV_AWS_355 -- "${plan_args[@]}"
expect_refusal "CKV_SKIP_CHECK in the environment" "CKV_SKIP_CHECK"

# Checkov cannot report its configuration at all.
run "$work/plan" -- "${plan_args[@]}" --no-such-flag
expect_refusal "an invocation checkov rejects" "could not report its configuration"

# The report's format, which is Checkov's own. A stub stands in for checkov here because these
# cases are about the wrapper reading a report the installed version does not print.
cat > "$work/stub/checkov" <<'EOF'
#!/usr/bin/env bash
printf '%s' "$STUB_REPORT"
EOF
chmod +x "$work/stub/checkov"

run "$work/plan" PATH="$work/stub:$PATH" STUB_REPORT=$'Arguments: -f plan.json\nDefaults:\n  --branch: master\n' -- "${plan_args[@]}"
expect_refusal "a report with no command-line section" "printed no command-line section"

# A section with a name the wrapper has never seen is refused like a config file, so renaming
# "Config File" cannot hide one.
run "$work/plan" PATH="$work/stub:$PATH" STUB_REPORT=$'Command Line Args:   -f plan.json\nSettings File (x.yml):\n  skip-check: [\'CKV_AWS_355\']\nDefaults:\n  --branch: master\n' -- "${plan_args[@]}"
expect_refusal "a section the wrapper does not know" "Settings File (x.yml)"

# ── A finding Checkov reports SKIPPED ────────────────────────────────────────────────────

# Runs a numerator over the last scan's output with the list file given. Leaves its status in
# $nrc, stdout in $work/narrow-out and stderr in $work/narrow-err.
numerator() {
  nrc=0
  "$1" "$work/out" "$2" > "$work/narrow-out" 2> "$work/narrow-err" || nrc=$?
}

# True when the last scan recorded exactly one skip of <check ID>, on <resource> if one is given.
recorded_skip() {
  jq -e --arg id "$1" --arg res "${2:-}" '(if type=="array" then .[0] else . end)
    | [.results.skipped_checks[]? | select(.check_id == $id and ($res == "" or .resource == $res))]
    | length == 1' "$work/out" >/dev/null 2>&1
}

expect_skip_refused() {
  local case="$1" needle="$2"
  if [ "$nrc" -ne 2 ]; then
    fail "$case: the numerator exited $nrc and printed '$(cat "$work/narrow-out")'. A skipped finding on a gated ID was not refused."
  elif [ -s "$work/narrow-out" ]; then
    fail "$case: the numerator refused but wrote to stdout, which the gate would read as a count."
  elif ! grep -qF -- "$needle is SKIPPED" "$work/narrow-err"; then
    fail "$case: the numerator refused without naming $needle as skipped. Its reason was: $(head -c 600 "$work/narrow-err")"
  else
    echo "ok - $case"
  fi
}

# Two log groups, one with a retention period and one without, so CKV_AWS_66 passes on one and
# fails on the other. That is the shape the numerator's coverage check cannot see: a skip on
# the failing one leaves the ID evaluated. The argument is the ID the failing one skips.
log_groups() {
  cat > "$work/tf/main.tf" <<EOF
resource "aws_cloudwatch_log_group" "kept" {
  name              = "kept"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "bare" {
  # checkov:skip=$1: planted by the corpus
  name = "bare"
}
EOF
}
echo CKV_AWS_66 > "$work/enforced.txt"
tf_args=(-d tf --framework terraform --skip-path .terraform --output json --compact --soft-fail)

# Silence. CKV_AWS_158 fails on the same resource and is not enforced, so skipping it must
# leave the enforced count at the one CKV_AWS_66 finding, with no refusal.
log_groups CKV_AWS_158
run "$work" -- "${tf_args[@]}"
numerator "$enforced" "$work/enforced.txt"
if [ "$rc" -ne 0 ] || ! recorded_skip CKV_AWS_158 aws_cloudwatch_log_group.bare; then
  fail "skip of an ID the gate does not hold: checkov did not record the planted skip (wrapper exit $rc), so silence here proves nothing."
elif [ "$nrc" -ne 0 ] || [ "$(cat "$work/narrow-out")" != "1" ] \
    || ! grep -qF "CKV_AWS_66 failed 1 time(s), first at aws_cloudwatch_log_group.bare" "$work/narrow-err" \
    || grep -qF "SKIPPED" "$work/narrow-err"; then
  fail "skip of an ID the gate does not hold: the numerator exited $nrc and printed '$(cat "$work/narrow-out")', not the one CKV_AWS_66 finding. $(head -c 600 "$work/narrow-err")"
else
  echo "ok - a skip of an ID the gate does not hold changes nothing"
fi

# The reported case: the enforced ID itself, skipped on the failing resource. A count of
# failures reads zero here, and the ID still passes on the other group.
log_groups CKV_AWS_66
run "$work" -- "${tf_args[@]}"
numerator "$enforced" "$work/enforced.txt"
if [ "$rc" -ne 0 ] || ! recorded_skip CKV_AWS_66 aws_cloudwatch_log_group.bare \
    || ! jq -e '(if type=="array" then .[0] else . end) | [.results.passed_checks[]? | select(.check_id == "CKV_AWS_66" and .resource == "aws_cloudwatch_log_group.kept")] | length == 1' "$work/out" >/dev/null 2>&1; then
  fail "skip of an enforced ID: checkov did not record the skip beside a pass of the same ID (wrapper exit $rc), so the fixture no longer plants the case."
else
  expect_skip_refused "skip of an enforced ID, still evaluated elsewhere" "CKV_AWS_66 on aws_cloudwatch_log_group.bare"
fi

# The Dockerfile scan's form. A Dockerfile check has one result per file, so the skip leaves the
# ID evaluated against nothing too, and the refusal must name the skip rather than blame a typo.
printf 'FROM python:latest\n# checkov:skip=CKV_DOCKER_7: planted by the corpus\nRUN echo corpus\n' > "$work/docker/Dockerfile"
echo CKV_DOCKER_7 > "$work/docker-enforced.txt"
run "$work/docker" -- -f Dockerfile --framework dockerfile --output json --compact --soft-fail
numerator "$enforced" "$work/docker-enforced.txt"
docker_res=$(jq -r '(if type=="array" then .[0] else . end) | [.results.skipped_checks[]? | select(.check_id == "CKV_DOCKER_7")] | .[0].resource // empty' "$work/out" 2>/dev/null)
if [ "$rc" -ne 0 ] || ! recorded_skip CKV_DOCKER_7 || [ -z "$docker_res" ]; then
  fail "skip in a Dockerfile: checkov did not record the planted skip (wrapper exit $rc), so the case plants nothing."
elif grep -qF "evaluated against nothing" "$work/narrow-err"; then
  fail "skip in a Dockerfile: the numerator blamed an unevaluated ID, which invites removing it from the list, instead of naming the skip. $(head -c 600 "$work/narrow-err")"
else
  expect_skip_refused "skip of an enforced ID in a Dockerfile" "CKV_DOCKER_7 on $docker_res"
fi

# The plan gate. The workflow's plan scan reads no inline comment, because Checkov takes a
# `.tf` file's skips into a plan scan only under --repo-root-for-plan-enrichment. This passes
# that flag to prove the numerator refuses what the flag would let through. The log group is
# the silent half: the plan gate counts IAM findings only, so its skip must not be named.
jq '.planned_values.root_module.resources += [{"address": "aws_cloudwatch_log_group.bare",
      "mode": "managed", "type": "aws_cloudwatch_log_group", "name": "bare",
      "provider_name": "registry.opentofu.org/hashicorp/aws", "values": {"name": "bare"}}]' \
  "$work/plan/plan.json" > "$work/enrich/plan.json"
cat > "$work/enrich/main.tf" <<'EOF'
resource "aws_iam_policy" "wild" {
  # checkov:skip=CKV_AWS_355: planted by the corpus
  name   = "wild"
  policy = "{}"
}

resource "aws_cloudwatch_log_group" "bare" {
  # checkov:skip=CKV_AWS_66: planted by the corpus
  name = "bare"
}
EOF
run "$work/enrich" -- -f plan.json --framework terraform_plan --repo-root-for-plan-enrichment . \
  --output json --compact --soft-fail
numerator "$narrow" "$work/accepted.txt"
if [ "$rc" -ne 0 ] || ! recorded_skip CKV_AWS_355 aws_iam_policy.wild \
    || ! recorded_skip CKV_AWS_66 aws_cloudwatch_log_group.bare; then
  fail "skip in the plan's source: checkov did not record both planted skips (wrapper exit $rc), so the case plants nothing."
elif grep -qF "aws_cloudwatch_log_group.bare" "$work/narrow-err"; then
  fail "skip in the plan's source: the plan numerator named a non-IAM skip, which its IAM-only count does not hold. $(head -c 600 "$work/narrow-err")"
else
  expect_skip_refused "skip of an IAM finding in the plan's source" "CKV_AWS_355 on aws_iam_policy.wild"
fi

if [ "$failures" -gt 0 ]; then
  echo "::error title=Checkov corpus::$failures case(s) failed. The gates' refusals cannot be trusted with this checkov." >&2
  exit 1
fi
echo "every case held"
