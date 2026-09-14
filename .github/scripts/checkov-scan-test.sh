#!/usr/bin/env bash
#
# The fixture corpus for checkov-scan.sh. It runs against the INSTALLED Checkov, in each job
# whose gate relies on the wrapper, before that job's scans.
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
# Every case runs with HOME pointed at an empty directory, so a config in the real home
# directory cannot decide a case that is not about it.
#
# Usage: checkov-scan-test.sh   (with checkov on PATH)
# Exit: 0 when every case holds, 1 when any does not, 2 when the corpus could not run.

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
scan="$here/checkov-scan.sh"
narrow="$here/checkov-plan-iam.sh"

command -v checkov >/dev/null 2>&1 || {
  echo "::error title=Checkov corpus::checkov is not installed. The corpus did not run, which is not a pass." >&2
  exit 2
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/plan" "$work/elsewhere" "$work/home" "$work/planted-home" "$work/stub"
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

if [ "$failures" -gt 0 ]; then
  echo "::error title=Checkov corpus::$failures case(s) failed. The wrapper's refusal cannot be trusted with this checkov." >&2
  exit 1
fi
echo "every case held"
