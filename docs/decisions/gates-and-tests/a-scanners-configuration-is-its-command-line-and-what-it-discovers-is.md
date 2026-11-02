---
type: Decision
title: "A scanner's configuration is its command line, and what it discovers is refused (2026-09-14)"
description: "**A scanner's configuration is its COMMAND LINE, and what it DISCOVERS is refused.** Checkov reads a `.checkov.yml` from the `-d` directory, the working directory and `$HOME`; Semgrep skips whatever a `.semgrepignore` anywhere in the tree matches; gitleaks reads a `.gitleaks.toml` and a `.gitleaksignore` from the repository, and never sees a path a `-diff` attribute hides from `git log -p`; and all three read variables. Measured, each took a finding off a blocking gate while the job read as clean, from a file no reviewer reads as part of a gate. So every Checkov, Semgrep and gitleaks scan runs through its `*-scan.sh` wrapper, which asks the tool what decided the scan (`--show-config`, the report's skip reasons, gitleaks's debug log, `git check-attr`) and refuses anything but the command line and the defaults. A corpus plants each source against the installed version before the job's scans. Refuse, never ignore: an ignored suppression file reads as one. The empty root `.semgrepignore` only switches off Semgrep's built-in list, which skips every `test/` directory under the same reason. Still open: Checkov's flagless variables, and inline `nosemgrep` and `gitleaks:allow`."
---

**What happened.** A reviewer reported, and a throwaway `checkov==3.3.9` reproduced, that Checkov
reads `.checkov.yaml` and `.checkov.yml` from the directory named by `-d`, from the working
directory and from `$HOME`, even when `-f` names one file, and reads the environment variables
behind its own flags (`CKV_SKIP_CHECK` among them). A key found there takes effect unless the same
flag is on the command line. On a plan holding one `"Action": "*"` policy, the rendered-plan scan
reported 9 failures, and with `infra/.checkov.yml` holding `skip-check: [CKV_AWS_355]` it reported
8, that one gone. The coverage assertion fires only when NO IAM check ran, so a targeted skip
satisfies it. On a policy granting `s3:GetObject` on `"*"`, skipping the two IDs it raises left 7
IAM checks evaluated, a narrowed count of 0 and the blocking gate printing "no findings". The file
sits outside the three list files the gates name, so no reviewer reads it as a change to a gate.

**The `.tf` and Dockerfile gates failed closed, by accident.** Their numerator hard-errors when an
enforced ID is evaluated against nothing, which is what a `skip-check` of one produces, and the
message then blames a typo or a scanner rename. A `baseline` set in the file fails closed by
another road. One covering every failure leaves Checkov printing only its summary, which the scan
step's JSON check refuses; one leaving a failure standing drops `passed_checks` to zero. The keys
that were not measured need not touch whether an ID ran.

**No option turns discovery off.** `--config-file` is parsed BESIDE the discovered files: the
planted skip survived an explicit config that set only `framework`, and one that set
`skip-check: []`, because ConfigArgParse admits a file's key whenever the flag is absent from the
command line, and an empty list writes no flag. Being immune rather than refusing would need a copy
of `infra/` without the file, or the `--directory=` spelling that Checkov's discovery does not
parse, which is a quirk a patch release could remove. Either way it would also need a clean working
directory, an empty `$HOME` and no flag variables set, because `--directory=` was measured still
reading a config from the working directory.

**The rule.** A scan's configuration is its command line and the list files its gate names.
Whatever the scanner discovers is REFUSED, never ignored, because an ignored suppression file reads
as a suppression while suppressing nothing, the shape `checkov-plan-iam.sh` already refuses in a
stale accept line. Every Checkov scan runs through `.github/scripts/checkov-scan.sh`, which asks
Checkov, with the same arguments and `--show-config`, what configuration it would use, and refuses
any section of that report other than the command line and the defaults. It is a whitelist, so a
section a later version names differently is refused too, and asking the scanner rather than
listing the places it looks covers a discovery location that a version bump adds. The section
names are Checkov's own and pinned with it. Which sources get recorded is ConfigArgParse's, and
Checkov does not pin that, so a release that stopped recording one is the silent case the corpus
below exists for. A refusal writes
nothing to stdout, so each scan step's JSON check fails. `checkov-plan-iam.sh` now also refuses a
file that holds no Checkov result: plain `jq` reads an empty file as success, and it would
otherwise have narrowed a refused scan to a clean zero.

**What proves it.** The refusal never fires on a normal run, so
`.github/scripts/checkov-scan-test.sh` runs in each scanning job, ahead of the scans, against the
Checkov that job installed. It plants a config in the working directory, in the `-d` directory and
in `$HOME`, and sets `CKV_SKIP_CHECK`. For each, it asserts that the refusal names its source and
leaves nothing a caller could parse. With nothing planted, it asserts the fixture's `CKV_AWS_355`
is reported by its ID. Each check was planted once: seven mutations of the wrapper and the
numerator, and each reddened its own case for its own reason. `test_security_gates.py` holds the
wiring. A workflow line may say `checkov` only in a form that cannot run it: the gate's own
scripts by name, a scan output or list file, the pinned install, or the artifact's name. So a scan
is caught however it is spelled. A first draft matched command positions and missed an environment
prefix, `time`, `pipx run` and a container image. A table of lines is that sweep's positive
control. The Checkov Action is refused, and each job runs the corpus before its first scan, under
the same `if:`.

**The inline skip this entry first left open is refused by the numerators (2026-09-15).** An
inline `# checkov:skip=` comment moves an enforced finding to `skipped_checks` while the ID still
passes on another resource, and the enforced numerator read zero. The wrapper cannot see it,
because the comment is in a scanned file rather than the configuration, so both numerators now
read Checkov's own record of what it skipped and refuse a skipped finding their count would have
held, naming the check and the resource: an enforced ID for the `.tf` and Dockerfile gates, any
check on an IAM resource for the plan's. It is a hard error rather than a count because a skip is
a suppression, not a finding: a skip on a resource that would have passed is recorded as skipped
too. A skip the count would not have held changes nothing. The plan scan as the workflow runs it
records no skip, since Checkov reads a `.tf` file's comments into a plan scan only under
`--repo-root-for-plan-enrichment`. With that flag, a skip in a `.tf` beside the corpus's plan took
`CKV_AWS_355` off and the IAM count fell from 2 to 1, so the plan numerator refuses one too rather
than resting on a flag nothing checks. The corpus plants a skip for each gate and asserts silence
on one outside each count, and each check was planted once.

**Semgrep and gitleaks do it too (2026-09-15).** Against `semgrep==1.172.0` with the Lambdas
scan's invocation, on a fixture holding one `subprocess` call with `shell=True`, a root
`.semgrepignore` naming `lambdas/` took the count from 1 to 0, and a `lambdas/.semgrepignore`
naming a subdirectory did the same. `SEMGREP_BASELINE_COMMIT` did it too, and recorded no skip at
all. Each run exited 0 with no parse error. A `.semgrepignore` in `$HOME` is not read. Against
gitleaks 8.30.1 with the workflow's invocation, on a repository holding two committed credentials,
a `.gitleaks.toml` allowlist naming one of their files took the count from 2 to 1, one fingerprint
in a `.gitleaksignore` did the same, and the same allowlist from `GITLEAKS_CONFIG` or
`GITLEAKS_CONFIG_TOML` did the same. Each exited the way a scan with that many findings does. A
fifth route is git's, not gitleaks's, and the first review found it
by planting: gitleaks reads the history through `git log -p`, which prints "Binary files differ"
instead of the content of any path whose `diff` attribute is unset. A committed `.gitattributes`
holding `*.py -diff` or `*.py binary` took a single credential from 1 to 0, for every commit, and
gitleaks's own report of what it loaded is byte for byte the same.

**Their wrappers ask the tool that decides.** `semgrep-scan.sh` adds `--verbose`, which makes the
report list every target Semgrep skipped and why, and refuses a skip whose reason names an ignore
file. It matches on the word, so a reason renamed to another spelling that still says "ignore" is
refused as well; a rename that dropped the word would stop the corpus's plants being refused, which
fails the job there. Semgrep cannot report the
variables it reads, so every `SEMGREP_*` name is refused except the workflow's own
`SEMGREP_VERSION`. The pinned release holds no string by that name, and it is removed from
Semgrep's environment anyway, since a search of strings cannot see a name built at run time.
`gitleaks-scan.sh` asks two tools. Git is asked, with `git check-attr`, which `diff` attribute it
gives every path in the history, so every attribute source git reads is covered, a nested
`.gitattributes` and `.git/info/attributes` included, and a path it reports unset is refused. That
includes a file that is binary anyway, such as a `*.png binary` line, because telling the two apart
would mean reading every version of the path; the refusal says to write `-text -merge` where that
is what the line is for. The count of answers against the paths asked is that check's positive
control, since a loop over a misread answer finds nothing to refuse. The wrapper supplies `git` and
`.` itself and runs only from the repository's top level, so the repository git is asked about is
the one gitleaks scans, and `git check-attr`, which reads a path relative to where it runs, reads
the history's paths as the paths they are. Then gitleaks is asked, with the same
flags, at debug level. There it names its configuration's source and each ignore file it loads,
before the line saying which `git log` it runs. The wrapper refuses any line in that stretch it
does not know, and a log that never names the default configuration. The ask reads no commit
(`--log-opts=--max-count=0`): at debug level gitleaks prints decoded fragments of what it scans,
which `--redact` does not cover, so the real scan runs at its own level. Both wrappers own their
report path and delete it first, so a refused scan leaves nothing to count, and the Semgrep one
deletes it again on every exit but a scan that completed and was not refused. Its first draft
printed a refusal's list through `head`, and more skips than a pipe holds killed the script with
SIGPIPE before the report went. That closed a fail-open already in the workflow, where both
summary steps read a missing report as 0. They now read it as no count.

**Semgrep's built-in list is why the repository keeps an empty `.semgrepignore`.** With no root
file, Semgrep applies a default list under the same skip reason a pattern gets, and the list skips
every `test/` directory. At 77ae380a it was skipping all 15 files in `apps/portal/src/test/` while
the workflow's comment said test files are scanned. The file switches the list off, so any such
skip is a pattern somebody wrote. Scanning those files added no finding. `test_security_gates.py`
asserts that the file exists and holds no pattern, since a pattern that matches nothing yet reads
as a suppression until the day it matches.

**What proves them.** `semgrep-scan-test.sh` and `gitleaks-scan-test.sh` run in the scan job,
ahead of each scanner's scans, against the release that job installed. Each case starts from a
stale report that reads as clean. Semgrep's corpus plants a root pattern, a nested file, the root
file's absence, `SEMGREP_BASELINE_COMMIT` and five thousand ignored targets, and its clean case
asserts both fixture findings, one of them under `test/`. The gitleaks corpus plants each of its
four configuration sources and asserts that the refusal quotes gitleaks's own line about it,
because the refusal message names every source anyway. It plants a `-diff` or `binary` attribute
from a root `.gitattributes`, a nested one and `.git/info/attributes`, one naming a path only the
history still holds, and one with the scan started below the top level, and asserts the refusal
names the hidden path or the reason. Its clean cases, one with a `.gitattributes` naming only a
diff driver, assert both credentials by rule ID, that the real scan printed no debug line, and that
the wrapper left nothing in a temporary directory of its own. That last check first measured
nothing on a Mac, where `mktemp -d` without a template ignores `TMPDIR`; the wrapper now names one.
Stubs cover each log, report or attribute answer the installed release does not give. Every
refusal in the two wrappers, and every line that deletes a report or a temporary directory, was
planted once: twenty-two mutations, each reddening its own case, between green baseline runs. The
guards that stop on a missing argument or scanner were not, since no scan runs past them. Ten more
mutations went into the wiring, which now reads every
workflow for all three scanners through one table and runs each summary and gate step the way the
runner does: a refused scan, and a gate no step counted for, each fail for their reason, and a
clean report passes. One plant survived and removed code instead of earning a case: stripping
colour codes from gitleaks's log, which dropping each line's time already did.

**What the scanner cannot read is refused too (2026-09-15).** A review of the inline-skip change
reproduced three routes by which a finding leaves a gate with no skip at all. Each was re-measured
against 3.3.9 before anything was built. Two are closed here, and the third is recorded below.

The `.tf` gate's population was a claim. OpenTofu loads `*.tf.json`, `*.tofu` and `*.tofu.json`,
and a `.tofu` file shadows the `.tf` of its name, but the terraform framework parses `.tf` and
`.hcl`. A log group with no retention in any of those three shapes, beside a compliant one in
`main.tf`, left `CKV_AWS_66` passing on the compliant one and the numerator at 0. An override file
is parsed, but OpenTofu merges it into the block it overrides while Checkov scores each block
alone. And `--skip-path '.terraform'` matched a substring of the path, so it also hid
`logs.terraform.tf`, while Checkov already skips a `.terraform` directory as it skips every hidden
one. The flag is gone. `checkov-tf-population.sh` runs in the scan's own step and refuses a tracked
file in any of those shapes anywhere in the repository, because a module source can name a
directory outside `infra/` and OpenTofu loads it. A refusal leaves the scan no JSON, and every
later step fails closed on that. A replay of the job's steps found two ways the gate still read a
count after a refusal: a report committed to the repository survived it, and a refusal resting on
errexit passed under `set +e`. So the step deletes the report first and exits by itself on a
refusal, and the wiring test pins both. Nothing here used any of the shapes. A second review found three
more ways past it, each reproduced end to end on a copy of `infra/`, and each is refused too. Git
quotes a path holding a non-ASCII character unless it is asked for raw paths, so
`infra/sécurité.tofu` passed every rule while OpenTofu loaded it; the check reads `ls-files -z`, as
*Read paths RAW* in the [change-detection entry](a-change-detection-gate-answers-three-ways-and-one-of-them-is-not-an.md) already said to. A variable file works the other way round: Checkov applies
an `*.auto.tfvars.json` beside a child module to that module, while OpenTofu reads one only where it
runs, and one turned `CKV_AWS_24` from failed to passed on a security group the plan still opened
to `0.0.0.0/0`, so every tracked `*.tfvars` and `*.tfvars.json` is refused. And OpenTofu downloads a
module called from outside the checkout, which Checkov reads only under
`--download-external-modules`: a git-sourced module declaring an SSH-open security group passed
with a count of 0. Checkov's `CKV_TF_1` scores every module call whose source does not start with
`./` or `../` and records nothing for one that does, so the enforced numerator refuses any
`CKV_TF_1` result, a skipped one included. Two alternatives were measured and rejected. Enforcing `checkov-enforced.txt` on the rendered-plan scan, which reads what
OpenTofu loads, would fail: on the plan scan of run 34903502457, `CKV_AWS_45` failed 12 times and
12 enforced IDs never ran. And adding the `terraform_json` framework would make the output a list of
reports, of which both numerators read only the first.

The plan gate scored a policy it could not see. A policy naming a resource created in the same
apply is `(known after apply)`, the plan omits it, and every IAM check Checkov still runs on the
resource passes. On a plan `tofu show -json` rendered, a role policy granting `s3:GetObject` on
`"*"` failed `CKV_AWS_288` and `CKV_AWS_355`, and the same grant beside a statement naming a new
queue ran two checks, both of which passed. This happened on #659: the results-conversion plane's
`pipe` and `sfn` policies were `(known after apply)`, and the gate scored them clean, so a finding
in them would first have blocked a later pull request that did not contain it. The plan numerator
now takes the plan as a third argument. It refuses, by address, an `aws_iam_*` resource being
created or replaced whose `policy` or `assume_role_policy` is unknown, and names one being updated
in place in a warning and the job summary. The two attributes are named rather than matched by a
suffix, because a real plan marks a new role's computed `inline_policy` unknown on every create,
which no hand-built fixture had, so the corpus's fixtures are trimmed from real plans.

The split was measured before it was chosen, by decision (2026-09-15), after a first draft that
refused every unknown document. Over the hundred pull-request plan runs 33009167982 to
34997976131 (2026-08-26 to 2026-09-15), a new document was unknown in 5 runs, all on the
results-conversion and feedback planes. An existing one went `jsonencode(...) -> (known after
apply)` on an in-place update in 27 runs across 22 branches, and 23 of those were the
observability module's sweep role and policies: the module has
`depends_on = [module.base]`, which defers the `aws_iam_policy_document` data sources they are built
from whenever `module.base` has a change pending, with their content unchanged. Nothing in such a
pull request can fix that, so refusing an update would block it for a document it did not touch.
For a new document, the fix is in the pull request. An ARN a policy's `Resource` names is built
from that resource's name in a local, so the plan knows it. A `Principal` must exist when IAM
writes the policy (the note beside `api_execution_role_arn` in `infra/main.tf`), so a role it names
needs an explicit dependency on that role, or lands in an earlier pull request, as does a resource
whose ARN AWS generates, such as a KMS key or a Cognito pool.

The corpus plants each refused file shape beside the ones allowed, and scans the allowed ones with
the workflow's flags, which is what proves that "allowed" means "read". It plants a module from git,
from the registry, pinned to a commit and under a skip of `CKV_TF_1`, and first asserts Checkov
recorded `CKV_TF_1` on each. It plants each unknown document beside the unknowns the refusal must
pass over: a computed `inline_policy`, a `policy_id`, a `policy_arn`, a queue policy and a data
source read at apply, and an update beside both orders of replacement. Thirty mutations of the three
scripts and seven of the wiring tests each reddened their own case.

**Not closed by this.** An inline suppression is still a route in Semgrep and gitleaks, where no
numerator reads what the scanner skipped. A `# nosemgrep` comment took a Semgrep finding off with no
trace in the report (2 findings became 1), and `--disable-nosem` brings it back. A `gitleaks:allow`
comment took a gitleaks finding off (1 became 0), and `--ignore-gitleaks-allow` brings it back.
The workflow passes neither flag.

A value Checkov cannot resolve can score the check UNKNOWN, which Checkov writes to no output
format, or PASSED. An SSM parameter's value, or a `var.x` with no default, as an ECR repository's
tag mutability left `CKV_AWS_51` scored only on a compliant repository beside it, and the numerator
at 0. `CKV_AWS_274` passes an `AdministratorAccess` ARN built from an unresolved
`data.aws_partition` and fails the literal one. The only way to see an UNKNOWN is to run Checkov
in-process and patch its internal `Report.add_record`, and a pass of the second kind is invisible
even to that. On `infra/` at `ae8008ce` the patch records none on an enforced Python check, and 79
by design on two enforced graph checks, `CKV2_AWS_40` on 58 IAM resources and `CKV2_AWS_56` on 21,
because the `.tf` scan cannot read a `templatefile()` policy; #797 has since taken `CKV2_AWS_40` off the list. A closure
would rest on Checkov's internals and need an exemption for such a check, or its removal from the
list, and it would refuse a change that leaves an
enforced setting unresolvable even when the deployed value is fine. It was recorded rather than
built, by decision (2026-09-15). Checkov also reads no `inline_policy` on an `aws_iam_role`, known
or unknown. On a rendered plan, a role whose inline policy allowed `*` on `*` scored the five role
checks, and all five passed. Nothing in `infra/` writes one, since roles take their policies from
`aws_iam_role_policy`. A refusal would have to tell a written inline policy from a new role's
computed one, and what an existing role's plan carries there was not measured. An unknown
document on an in-place update is still only named. #797 has since built the observability
documents without a data source, and run 35030771490 planned a change in `module.base` while
Checkov read the sweep policies with all nine checks, so what an update now leaves unknown is a
real edit: an existing policy gaining a new resource's ARN, as `module.api`'s did on both plane
pull requests, or a function a plane replaces by design. Refusing those too was offered and
declined by decision (2026-09-15), so they reach a warning, not a refusal. Nor is an unknown
`policy_arn` refused, though `CKV_AWS_274` reads it to catch an `AdministratorAccess` attachment. It
is unknown on every attachment of a customer-managed policy created in the same apply, which every
deploy-grant pull request makes, so refusing it would block them all. A review reached it through a
partition data source read at apply inside a module with `depends_on`, a shape
`test_depends_on_defers_no_data_source.py` now refuses.

The environment variables Checkov reads directly rather than through a flag are another route:
`--show-config` cannot report them, and a review measured
`CKV_IGNORED_DIRECTORIES` taking the finding of a resource in a subdirectory off a `-d` scan while
the wrapper exited 0. And code the pull request controls runs in both scanning jobs before Checkov
does: `npm ci` runs install scripts in the security scan job, and the plan job runs
`lambdas/fleet.py` and `lambda_plan_guard.py`. A step can write `$GITHUB_ENV` for every later step,
which is how a flagless variable above would arrive without a workflow edit. The review that found
this measured an install script doing so. A `SEMGREP_*` variable arriving that way is refused,
because the Semgrep wrapper reads the environment itself, and a `GITLEAKS_*` one because gitleaks
reports it. Git's own settings reach gitleaks as well: the attribute check covers every source of
attributes, but a setting that changes what `git log -p` prints by other means, such as a diff
driver's `textconv`, lives in git configuration, which only the workflow or code the job runs can
set. The same review measured a fake `checkov` placed earlier on `PATH` that stripped one module's
failures from a `-d` scan while this corpus still passed. That `$GITHUB_PATH` places it there for a
later step is inferred. No wrapper can see either, and none claims to. Each closes a file added in
good faith, not code written to defeat the gate, which a pull request that can edit the workflow
could do more simply. Nor is content closed: a file git detects as binary by itself, one with a
NUL byte near its start, is not scanned (measured, 1 finding became 0), and Semgrep passes a file
over its 1 MB default without a finding.

## History

### 2026-09-15

- **Changed:** The inline `# checkov:skip=` this entry first left open is now refused by both numerators when it hides a finding their count would have held.
- **Changed:** The rule extended to Semgrep and gitleaks, whose wrappers refuse ignore files, configuration sources, `SEMGREP_*` variables and `-diff` attributes.
- **Changed:** The rule extended to what Checkov cannot read: unparsed file shapes and a new IAM document unknown until apply are refused, while an unknown on an update is only named.

### 2026-09-14

- **Settled:** entered the register.
