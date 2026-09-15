#!/usr/bin/env bash
#
# The fixture corpus for checkov-scan.sh, for the two numerators' refusal of a skipped finding,
# for checkov-tf-population.sh, and for the plan numerator's refusal of a policy the plan cannot
# show. It runs against the INSTALLED Checkov, in each job whose gate relies on them, before
# that job's scans.
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
# refusal names the check ID and the resource. Silence is asserted too: a skip outside a
# gate's count, of an ID it does not enforce or on a resource that is not IAM, changes
# nothing. Each first asserts that Checkov recorded the planted skip, so a scanner that
# stopped honouring the comment fails here rather than passing a case that no longer plants
# anything.
#
# Three more ways a finding reaches no count follow. A file OpenTofu loads in a shape the
# terraform framework cannot read is refused by checkov-tf-population.sh, and each shape is
# planted. The files it allows are planted with a failure each and scanned with the workflow's
# flags, which is what proves "allowed" means "read". A module called from outside the checkout
# is refused by the enforced numerator. And a policy the plan marks unknown until
# apply is refused by the plan numerator when the resource is new, and named in a warning when
# it is updated in place. Those fixtures are trimmed from plans `tofu show -json` rendered,
# because `after_unknown` marks a role's computed `inline_policy` unknown on every create, which
# no hand-built fixture had.
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
population="$here/checkov-tf-population.sh"

command -v checkov >/dev/null 2>&1 || {
  echo "::error title=Checkov corpus::checkov is not installed. The corpus did not run, which is not a pass." >&2
  exit 2
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/plan" "$work/elsewhere" "$work/home" "$work/planted-home" "$work/stub" \
  "$work/tf" "$work/docker" "$work/enrich" "$work/repo" "$work/no-tf" \
  "$work/unknown/policy" "$work/unknown/trust" "$work/unknown/silent" "$work/unknown/updated" \
  "$work/unknown/replaced" "$work/unknown/cbd" "$work/remote/infra"
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
elif ! "$narrow" "$work/out" "$work/accepted.txt" "$work/plan/plan.json" 2> "$work/narrow-err" > /dev/null \
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
"$narrow" "$work/out" "$work/accepted.txt" "$work/plan/plan.json" > "$work/narrow-out" 2> "$work/narrow-err" || nrc=$?
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

# Runs a numerator over the last scan's output with the list file given, and the rendered plan
# for the plan numerator. Leaves its status in $nrc, stdout in $work/narrow-out and stderr in
# $work/narrow-err.
numerator() {
  local script="$1"; shift
  nrc=0
  "$script" "$work/out" "$@" > "$work/narrow-out" 2> "$work/narrow-err" || nrc=$?
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
tf_args=(-d tf --framework terraform --output json --compact --soft-fail)

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
numerator "$narrow" "$work/accepted.txt" "$work/enrich/plan.json"
if [ "$rc" -ne 0 ] || ! recorded_skip CKV_AWS_355 aws_iam_policy.wild \
    || ! recorded_skip CKV_AWS_66 aws_cloudwatch_log_group.bare; then
  fail "skip in the plan's source: checkov did not record both planted skips (wrapper exit $rc), so the case plants nothing."
elif grep -qF "aws_cloudwatch_log_group.bare" "$work/narrow-err"; then
  fail "skip in the plan's source: the plan numerator named a non-IAM skip, which its IAM-only count does not hold. $(head -c 600 "$work/narrow-err")"
else
  expect_skip_refused "skip of an IAM finding in the plan's source" "CKV_AWS_355 on aws_iam_policy.wild"
fi

# ── A file OpenTofu reads that the scan cannot ───────────────────────────────────────────

# Runs checkov-tf-population.sh over a directory. Leaves its status in $prc, stdout in
# $work/pop-out and stderr in $work/pop-err.
populate() {
  prc=0
  "$population" "$1" > "$work/pop-out" 2> "$work/pop-err" || prc=$?
}

expect_population_refused() {
  local case="$1" needle="$2"
  if [ "$prc" -ne 2 ]; then
    fail "$case: the population check exited $prc, not 2, so it did not refuse."
  elif [ -s "$work/pop-out" ]; then
    fail "$case: the population check refused but wrote to stdout."
  elif ! grep -qF -- "$needle" "$work/pop-err"; then
    fail "$case: the population check refused without saying '$needle'. Its reason was: $(head -c 600 "$work/pop-err")"
  else
    echo "ok - $case"
  fi
}

log_group() { printf 'resource "aws_cloudwatch_log_group" "%s" {\n  name = "%s"\n}\n' "$1" "$1"; }

# Every file here is one OpenTofu reads and the population check allows, each holding a log
# group with no retention, so CKV_AWS_66 must fail on every one. `logs.terraform.tf` is the name
# the old `--skip-path '.terraform'` hid, a hidden directory is one Checkov walks past unless a
# module call leads into it, and `overrides.tf` sits one letter from an override file's name.
mkdir -p "$work/repo/infra/modules/.hidden" "$work/repo/infra/policies"
{ log_group root; printf 'module "hidden" {\n  source = "./modules/.hidden"\n}\n'; } > "$work/repo/infra/main.tf"
log_group named_like_the_data_dir > "$work/repo/infra/logs.terraform.tf"
log_group hidden > "$work/repo/infra/modules/.hidden/main.tf"
log_group one_letter_from_an_override > "$work/repo/infra/overrides.tf"
printf '{"Version": "2012-10-17", "Statement": []}\n' > "$work/repo/infra/policies/doc.json"
printf 'region = "us-east-1"\n' > "$work/repo/infra/terraform.tfvars.example"
# `add -f` throughout, because a global excludes file carrying the usual Terraform patterns
# would otherwise leave an override or variable file unstaged, and its case would fail.
git -C "$work/repo" init -q && git -C "$work/repo" add -A -f

populate "$work/repo"
run "$work/repo" -- -d infra --framework terraform --output json --compact --soft-fail
numerator "$enforced" "$work/enforced.txt"
seen=$(jq -r '(if type=="array" then .[0] else . end) | [.results.failed_checks[]? | select(.check_id == "CKV_AWS_66") | .resource] | sort | join(" ")' "$work/out" 2>/dev/null)
want="aws_cloudwatch_log_group.named_like_the_data_dir aws_cloudwatch_log_group.one_letter_from_an_override aws_cloudwatch_log_group.root module.hidden.aws_cloudwatch_log_group.hidden"
if [ "$prc" -ne 0 ] || [ -s "$work/pop-out" ] || ! grep -qF "none that OpenTofu loads" "$work/pop-err"; then
  fail "files the scan reads: the population check exited $prc on a tree it must allow. $(head -c 600 "$work/pop-err")"
elif [ "$rc" -ne 0 ] || [ "$seen" != "$want" ]; then
  fail "files the scan reads: CKV_AWS_66 failed on '$seen', not on every planted file (wrapper exit $rc). A file the population check allows is one the scan did not read."
elif [ "$nrc" -ne 0 ] || [ "$(cat "$work/narrow-out")" != "4" ]; then
  fail "files the scan reads: the enforced numerator exited $nrc and printed '$(cat "$work/narrow-out")', not the 4 planted findings."
else
  echo "ok - every file the population check allows is read by the scan"
fi

# Each shape it refuses, planted alone into the allowed tree: one outside infra/, because a
# module source can name a directory there, one whose name git quotes unless it is asked for raw
# paths, and variable files, which change what Checkov scores rather than what it reads.
refused_shape() {
  local path="$1" needle="$2"
  mkdir -p "$(dirname "$work/repo/$path")"
  log_group bare > "$work/repo/$path"
  git -C "$work/repo" add -f -- "$path"
  populate "$work/repo"
  expect_population_refused "refuses $path" "$path: $needle"
  git -C "$work/repo" rm -q --cached -- "$path" && rm "$work/repo/$path"
}
refused_shape infra/bare.tofu "OpenTofu loads it and the terraform framework does not parse it"
refused_shape infra/bare.tf.json "OpenTofu loads it and the terraform framework does not parse it"
refused_shape infra/bare.tofu.json "OpenTofu loads it and the terraform framework does not parse it"
refused_shape infra/override.tf "OpenTofu merges it into the block it overrides"
refused_shape infra/main_override.tf "OpenTofu merges it into the block it overrides"
refused_shape lambdas/outside.tofu "OpenTofu loads it and the terraform framework does not parse it"
refused_shape "infra/sécurité.tofu" "OpenTofu loads it and the terraform framework does not parse it"
refused_shape infra/modules/.hidden/planted.auto.tfvars.json "Checkov applies a variable file to the module beside it"
refused_shape infra/terraform.tfvars "Checkov applies a variable file to the module beside it"

# A listing with no .tf file in it refuses, so a wrong root cannot pass as a clean one.
printf 'no infrastructure here\n' > "$work/no-tf/README.md"
git -C "$work/no-tf" init -q && git -C "$work/no-tf" add -A -f
populate "$work/no-tf"
expect_population_refused "refuses a tree with no .tf file" "no .tf file is tracked"

# A directory git cannot list refuses rather than reading as empty. The ceiling stops git finding
# a repository above the corpus's directory, which a TMPDIR inside a checkout would put there.
prc=0
GIT_CEILING_DIRECTORIES="$work" "$population" "$work/elsewhere" > "$work/pop-out" 2> "$work/pop-err" || prc=$?
expect_population_refused "refuses a directory git cannot list" "could not list the files tracked"

# ── A module the scan could not read ─────────────────────────────────────────────────────

# Four module calls from outside the checkout, beside a log group that passes CKV_AWS_66, so the
# count alone would read zero. Checkov must record CKV_TF_1 on each, as passed (a pinned commit),
# failed, or skipped under an inline comment, which is what the numerator reads.
cat > "$work/remote/infra/main.tf" <<'TF'
resource "aws_cloudwatch_log_group" "kept" {
  name              = "kept"
  retention_in_days = 30
}

module "from_git" {
  source = "git::https://example.com/module.git"
}

module "from_the_registry" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0.0"
}

module "pinned" {
  source = "git::https://example.com/module.git?ref=0123456789abcdef0123456789abcdef01234567"
}

module "skipped" {
  # checkov:skip=CKV_TF_1: planted by the corpus
  source = "git::https://example.com/module.git?ref=v1"
}
TF
run "$work/remote" -- -d infra --framework terraform --output json --compact --soft-fail
numerator "$enforced" "$work/enforced.txt"
missing=""
for module in from_git from_the_registry pinned skipped; do
  jq -e --arg m "$module" '(if type=="array" then .[0] else . end)
    | [.results.passed_checks[]?, .results.failed_checks[]?, .results.skipped_checks[]? | select(.check_id == "CKV_TF_1" and .resource == $m)]
    | length == 1' "$work/out" >/dev/null 2>&1 || missing="$missing $module"
done
if [ "$rc" -ne 0 ] || [ -n "$missing" ]; then
  fail "modules from outside the checkout: checkov recorded no CKV_TF_1 result on$missing (wrapper exit $rc), so the numerator has nothing to read them by."
elif [ "$nrc" -ne 2 ] || [ -s "$work/narrow-out" ]; then
  fail "modules from outside the checkout: the enforced numerator exited $nrc and printed '$(cat "$work/narrow-out")'. A module the scan did not read was counted as clean."
else
  unnamed=""
  for module in from_git from_the_registry pinned skipped; do
    grep -qF "module \"$module\"" "$work/narrow-err" || unnamed="$unnamed $module"
  done
  if [ -n "$unnamed" ] || ! grep -qF "takes its source from outside the checkout" "$work/narrow-err"; then
    fail "modules from outside the checkout: the numerator refused without naming$unnamed. Its reason was: $(head -c 600 "$work/narrow-err")"
  else
    echo "ok - a module called from outside the checkout is refused, whether its CKV_TF_1 passed, failed or was skipped"
  fi
fi

# ── An IAM document the plan cannot show ─────────────────────────────────────────────────

# Trimmed from a plan `tofu show -json` rendered with OpenTofu 1.12 and AWS provider 5.100.0.
# `wild_and_new` grants s3:GetObject on "*" beside a statement naming a queue the same apply
# creates, so its policy is unknown.
cat > "$work/unknown/policy/plan.json" <<'EOF'
{"format_version": "1.2", "terraform_version": "1.12.1",
 "planned_values": {"root_module": {"resources": [
  {"address":"aws_iam_role_policy.wild_and_new","mode":"managed","type":"aws_iam_role_policy","name":"wild_and_new","values":{"role":"fixed"}}
 ]}},
 "resource_changes": [
  {"address":"aws_iam_role_policy.wild_and_new","mode":"managed","type":"aws_iam_role_policy","name":"wild_and_new","change":{"actions":["create"],"before":null,"after":{"role":"fixed"},"after_unknown":{"policy":true}}}
 ]}
EOF

# A role whose trust policy names a role the same apply creates. Its first inline policy is
# unknown too, which Checkov does not read either way, so only the trust policy is named.
cat > "$work/unknown/trust/plan.json" <<'EOF'
{"format_version": "1.2", "terraform_version": "1.12.1",
 "planned_values": {"root_module": {"resources": [
  {"address":"aws_iam_role.r","mode":"managed","type":"aws_iam_role","name":"r","values":{"inline_policy":[{"name":"inl"},{"name":"known","policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Action\":\"sqs:SendMessage\",\"Effect\":\"Allow\",\"Resource\":\"arn:aws:sqs:us-east-1:111111111111:q\"}]}"}]}}
 ]}},
 "resource_changes": [
  {"address":"aws_iam_role.r","mode":"managed","type":"aws_iam_role","name":"r","change":{"actions":["create"],"before":null,"after":{"inline_policy":[{"name":"inl"},{"name":"known","policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Action\":\"sqs:SendMessage\",\"Effect\":\"Allow\",\"Resource\":\"arn:aws:sqs:us-east-1:111111111111:q\"}]}"}]},"after_unknown":{"assume_role_policy":true,"inline_policy":[{"policy":true},{}],"managed_policy_arns":true}}}
 ]}
EOF

# Everything the refusal must pass over, each unknown attribute as the real plan marked it: a
# new role's computed inline_policy, a policy_id, a policy_arn, a queue policy (not IAM), and a
# data source read at apply. `m` and `k` are known wildcard grants, so the count is theirs.
cat > "$work/unknown/silent/plan.json" <<'EOF'
{"format_version": "1.2", "terraform_version": "1.12.1",
 "planned_values": {"root_module": {"resources": [
  {"address":"aws_iam_policy.m","mode":"managed","type":"aws_iam_policy","name":"m","values":{"policy":"{\"Statement\":[{\"Action\":\"s3:GetObject\",\"Effect\":\"Allow\",\"Resource\":\"*\"}],\"Version\":\"2012-10-17\"}"}},
  {"address":"aws_iam_role.other","mode":"managed","type":"aws_iam_role","name":"other","values":{"assume_role_policy":"{\"Statement\":[{\"Action\":\"sts:AssumeRole\",\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}],\"Version\":\"2012-10-17\"}"}},
  {"address":"aws_iam_role_policy.k","mode":"managed","type":"aws_iam_role_policy","name":"k","values":{"policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Action\":\"s3:GetObject\",\"Effect\":\"Allow\",\"Resource\":\"*\"}]}","role":"fixed"}},
  {"address":"aws_iam_role_policy_attachment.a","mode":"managed","type":"aws_iam_role_policy_attachment","name":"a","values":{"role":"other"}},
  {"address":"aws_sqs_queue_policy.qp","mode":"managed","type":"aws_sqs_queue_policy","name":"qp","values":{}},
  {"address":"data.aws_iam_policy.read","mode":"data","type":"aws_iam_policy","name":"read","values":{}}
 ]}},
 "resource_changes": [
  {"address":"data.aws_iam_policy.read","mode":"data","type":"aws_iam_policy","name":"read","change":{"actions":["read"],"before":null,"after":{},"after_unknown":{"policy":true,"policy_id":true}}},
  {"address":"aws_iam_policy.m","mode":"managed","type":"aws_iam_policy","name":"m","change":{"actions":["create"],"before":null,"after":{"policy":"{\"Statement\":[{\"Action\":\"s3:GetObject\",\"Effect\":\"Allow\",\"Resource\":\"*\"}],\"Version\":\"2012-10-17\"}"},"after_unknown":{"policy_id":true}}},
  {"address":"aws_iam_role.other","mode":"managed","type":"aws_iam_role","name":"other","change":{"actions":["create"],"before":null,"after":{"assume_role_policy":"{\"Statement\":[{\"Action\":\"sts:AssumeRole\",\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}],\"Version\":\"2012-10-17\"}"},"after_unknown":{"inline_policy":true,"managed_policy_arns":true}}},
  {"address":"aws_iam_role_policy.k","mode":"managed","type":"aws_iam_role_policy","name":"k","change":{"actions":["create"],"before":null,"after":{"policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Action\":\"s3:GetObject\",\"Effect\":\"Allow\",\"Resource\":\"*\"}]}","role":"fixed"},"after_unknown":{}}},
  {"address":"aws_iam_role_policy_attachment.a","mode":"managed","type":"aws_iam_role_policy_attachment","name":"a","change":{"actions":["create"],"before":null,"after":{"role":"other"},"after_unknown":{"policy_arn":true}}},
  {"address":"aws_sqs_queue_policy.qp","mode":"managed","type":"aws_sqs_queue_policy","name":"qp","change":{"actions":["create"],"before":null,"after":{},"after_unknown":{"policy":true,"queue_url":true}}}
 ]}
EOF

expect_unknown_refused() {
  local case="$1" needle="$2"
  if [ "$nrc" -ne 2 ]; then
    fail "$case: the plan numerator exited $nrc and printed '$(cat "$work/narrow-out")'. A policy the plan cannot show was counted."
  elif [ -s "$work/narrow-out" ]; then
    fail "$case: the plan numerator refused but wrote to stdout, which the gate would read as a count."
  elif ! grep -qF -- "$needle is unknown until apply" "$work/narrow-err"; then
    fail "$case: the plan numerator refused without naming '$needle'. Its reason was: $(head -c 600 "$work/narrow-err")"
  else
    echo "ok - $case"
  fi
}

# The reported case, first showing what the refusal is for: Checkov scores the unknown grant
# without failing it, so the count alone would be zero.
run "$work/unknown/policy" -- "${plan_args[@]}"
numerator "$narrow" "$work/accepted.txt" "$work/unknown/policy/plan.json"
if [ "$rc" -ne 0 ] || ! jq -e '(if type=="array" then .[0] else . end)
    | ([.results.passed_checks[]? | select(.resource == "aws_iam_role_policy.wild_and_new")] | length > 0)
      and ([.results.failed_checks[]? | select(.resource == "aws_iam_role_policy.wild_and_new")] | length == 0)' "$work/out" >/dev/null 2>&1; then
  fail "policy unknown until apply: checkov did not pass the unknown grant without failing it (wrapper exit $rc), so the case no longer shows a count that would read zero."
else
  expect_unknown_refused "refuses a policy unknown until apply" "aws_iam_role_policy.wild_and_new: its policy"
fi

run "$work/unknown/trust" -- "${plan_args[@]}"
numerator "$narrow" "$work/accepted.txt" "$work/unknown/trust/plan.json"
expect_unknown_refused "refuses a trust policy unknown until apply" "aws_iam_role.r: its assume_role_policy"
if grep -qF "its inline_policy" "$work/narrow-err"; then
  fail "refuses a trust policy unknown until apply: it also named the inline policy, which Checkov does not read known or unknown."
fi

run "$work/unknown/silent" -- "${plan_args[@]}"
numerator "$narrow" "$work/accepted.txt" "$work/unknown/silent/plan.json"
if [ "$rc" -ne 0 ] || [ "$nrc" -ne 0 ] || [ "$(cat "$work/narrow-out")" != "4" ] \
    || grep -qF "unknown until apply" "$work/narrow-err"; then
  fail "unknowns that are not a policy the IAM checks read: the plan numerator exited $nrc and printed '$(cat "$work/narrow-out")', not the 4 known findings (wrapper exit $rc). $(head -c 600 "$work/narrow-err")"
else
  echo "ok - an unknown that is not a policy the IAM checks read changes nothing"
fi

# Trimmed from a plan rendered against a state that already held both policies. The first is
# updated in place with its document unknown, which is named rather than refused, because a
# module's depends_on makes an unchanged document look exactly like this. The second is renamed,
# which IAM cannot do in place, so it is replaced, and a replacement is new.
cat > "$work/unknown/updated/plan.json" <<'PLAN'
{"format_version": "1.2", "terraform_version": "1.12.1",
 "planned_values": {"root_module": {"resources": [
  {"address":"aws_iam_role_policy.updated","mode":"managed","type":"aws_iam_role_policy","name":"updated","values":{"name":"updated","role":"fixed"}}
 ]}},
 "resource_changes": [
  {"address":"aws_iam_role_policy.updated","mode":"managed","type":"aws_iam_role_policy","name":"updated","change":{"actions":["update"],"before":{"name":"updated","policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"*\"}]}","role":"fixed"},"after":{"name":"updated","role":"fixed"},"after_unknown":{"policy":true}}}
 ]}
PLAN
cat > "$work/unknown/replaced/plan.json" <<'PLAN'
{"format_version": "1.2", "terraform_version": "1.12.1",
 "planned_values": {"root_module": {"resources": [
  {"address":"aws_iam_role_policy.replaced","mode":"managed","type":"aws_iam_role_policy","name":"replaced","values":{"name":"replaced-renamed","role":"fixed"}}
 ]}},
 "resource_changes": [
  {"address":"aws_iam_role_policy.replaced","mode":"managed","type":"aws_iam_role_policy","name":"replaced","change":{"actions":["delete","create"],"before":{"name":"replaced","policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"*\"}]}","role":"fixed"},"after":{"name":"replaced-renamed","role":"fixed"},"after_unknown":{"name_prefix":true,"policy":true}}}
 ]}
PLAN

run "$work/unknown/updated" -- "${plan_args[@]}"
: > "$work/step-summary"
nrc=0
GITHUB_STEP_SUMMARY="$work/step-summary" "$narrow" "$work/out" "$work/accepted.txt" "$work/unknown/updated/plan.json" \
  > "$work/narrow-out" 2> "$work/narrow-err" || nrc=$?
if [ "$rc" -ne 0 ] || [ "$nrc" -ne 0 ] || [ "$(cat "$work/narrow-out")" != "0" ] || grep -qF "::error" "$work/narrow-err"; then
  fail "a policy unknown on an in-place update: the plan numerator exited $nrc and printed '$(cat "$work/narrow-out")' (wrapper exit $rc). It must name the document and still count. $(head -c 600 "$work/narrow-err")"
elif ! grep -qF "::warning title=Checkov (plan IAM)::aws_iam_role_policy.updated: its policy is unknown until apply on an in-place update" "$work/narrow-err"; then
  fail "a policy unknown on an in-place update: no warning named it, so the job would not say the gate did not read it. $(head -c 600 "$work/narrow-err")"
elif ! grep -qF -- "- aws_iam_role_policy.updated: its policy" "$work/step-summary"; then
  fail "a policy unknown on an in-place update: the job summary does not name it. It holds: $(head -c 300 "$work/step-summary")"
else
  echo "ok - a policy unknown on an in-place update is named, not refused"
fi

run "$work/unknown/replaced" -- "${plan_args[@]}"
numerator "$narrow" "$work/accepted.txt" "$work/unknown/replaced/plan.json"
expect_unknown_refused "refuses a replaced policy unknown until apply" "aws_iam_role_policy.replaced: its policy"

# The same replacement under create_before_destroy, whose actions put "create" first.
cat > "$work/unknown/cbd/plan.json" <<'PLAN'
{"format_version": "1.2", "terraform_version": "1.12.1",
 "planned_values": {"root_module": {"resources": [
  {"address":"aws_iam_role_policy.cbd","mode":"managed","type":"aws_iam_role_policy","name":"cbd","values":{"name":"cbd-renamed","role":"fixed"}}
 ]}},
 "resource_changes": [
  {"address":"aws_iam_role_policy.cbd","mode":"managed","type":"aws_iam_role_policy","name":"cbd","change":{"actions":["create","delete"],"before":{"name":"cbd","policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"*\"}]}","role":"fixed"},"after":{"name":"cbd-renamed","role":"fixed"},"after_unknown":{"name_prefix":true,"policy":true}}}
 ]}
PLAN
run "$work/unknown/cbd" -- "${plan_args[@]}"
numerator "$narrow" "$work/accepted.txt" "$work/unknown/cbd/plan.json"
expect_unknown_refused "refuses a create-before-destroy replacement unknown until apply" "aws_iam_role_policy.cbd: its policy"

# The plan is an argument the gate cannot run without.
numerator "$narrow" "$work/accepted.txt" "$work/unknown/no-such-plan.json"
if [ "$nrc" -ne 2 ] || [ -s "$work/narrow-out" ] || ! grep -qF "no-such-plan.json is missing" "$work/narrow-err"; then
  fail "a missing plan: the plan numerator exited $nrc and printed '$(cat "$work/narrow-out")'. It must refuse to count without the plan."
else
  echo "ok - the plan numerator refuses to count without the plan"
fi
numerator "$narrow" "$work/accepted.txt" "$work/out"
if [ "$nrc" -ne 2 ] || [ -s "$work/narrow-out" ] || ! grep -qF "is not a rendered plan" "$work/narrow-err"; then
  fail "a file that is not a plan: the plan numerator exited $nrc and printed '$(cat "$work/narrow-out")'. It must refuse a plan argument that holds no plan."
else
  echo "ok - the plan numerator refuses a plan argument that holds no plan"
fi

if [ "$failures" -gt 0 ]; then
  echo "::error title=Checkov corpus::$failures case(s) failed. The gates' refusals cannot be trusted with this checkov." >&2
  exit 1
fi
echo "every case held"
