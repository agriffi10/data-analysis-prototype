"""The deploy workflows' agreements about reading Terraform state, and about what they run.

Two workflows now init the same backend and resolve their configuration from it, and a
third and a fourth already declare an OpenTofu version. Every assertion here is DERIVED
from the workflow directory rather than written against a list: a further consumer is
coming, and a check that counted to three would keep passing while the fourth drifted.

The tests at the end are about ``paths:`` filters. Most hold a workflow's filters to its own
file and to the files its ``run:`` blocks name. A filter that omits one lets a pull request
edit that file — a blocking gate, or the list of findings it accepts — and merge without the
gate ever executing. A file only a script reaches, a module it imports or a table it reads,
is not derived: those filter entries are kept by hand. One holds the opposite: the two image
deploys must carry no filter on their push at all, and a filter naming exactly the right
files would pass every other check here.

Attributes:
  ROOT: The repository root.
  WORKFLOWS: The directory every assertion here derives its subject from.
  RESOLVE_STEP: The resolve step's name, used to find every workflow that has one.
  RETIRED_VARIABLES: Repository variables this spec replaced with Terraform outputs. A
    reference to one that survives in any workflow is reading a value nobody maintains.
  SURVIVING_VARIABLE: A variable that is still a genuine input, used as the positive
    control for the sweep below.
  README: The workflow directory's setup guide, whose Step 3 table documents every variable.
  VARIABLES: The root Terraform variable declarations, the source of the name defaults.
  TOFU_RUN: A `run` script invoking a plan or an apply, global options such as `-chdir` allowed
    before the subcommand — the steps where Terraform reads its inputs from the environment.
  GUARD_LINE: The whole first line of such a step: the TF_VAR guard, run before `tofu`.
  NAME_KEYS: The environment keys workflows build resource names from, mapped to the Terraform
    variable whose default each must equal.
  VARIABLE_READ: A workflow reading an Actions variable, in either expression syntax.
  GUARD: The guard script, imported by path so the declared-variable parse here is its own.
  PATH_WORD: A maximal run of the characters a repository path is spelled with. Each one
    found in a ``run:`` block is a candidate, and it counts only if it names a tracked file.
  CD_TARGET: A directory a ``run:`` block changes into, which becomes another base its
    words are resolved from.
  WORKSPACE_PREFIX: The one variable whose value is the repository root, as it survives
    word-splitting when written ``$GITHUB_WORKSPACE/…``.
  PATH_FILTERED: Workflows known to carry a ``paths:`` filter, so a derivation that stopped
    finding filters fails instead of agreeing over nothing.
  KNOWN_REFERENCES: Files each named workflow's steps are known to run, one per way the
    derivation reaches a file: a ``../`` path resolved from a step's ``working-directory``,
    a path from the repository root, and a file outside ``.github/`` selected only by a
    ``dir/**`` entry.
  UNSELECTED_PATH: A tracked file the infrastructure workflow's filter must NOT select, so a
    matcher that selected everything could not pass.
  SPELLING_CORPUS_FILES: The tracked set the spelling corpus resolves against.
  UNFILTERED_ON_PUSH: The image deploys, which must run on every push to ``main``; the test
    that holds them gives the reason for each.
"""

import functools
import importlib.util
import pathlib
import posixpath
import re
import shlex
import shutil
import subprocess
from typing import Any

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
RESOLVE_STEP = "- name: Resolve the configuration from Terraform state"
README = WORKFLOWS / "README.md"
VARIABLES = ROOT / "infra" / "variables.tf"
TOFU_RUN = re.compile(r"\btofu\s+(?:-\S+\s+)*(plan|apply)\b")
GUARD_LINE = re.compile(r"python3 (?:\S+/)?\.github/scripts/tf_var_guard\.py")
LOCK_OFF_VALUES = frozenset({"0", "f", "F", "false", "FALSE", "False"})
LOCK_FLAG = re.compile(r"(?<![\w-])--?lock(?:-timeout)?(?![\w-])")
DURATION_PART = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|ms|s|m|h)")
UNIT_SECONDS = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0, "m": 60.0, "h": 3600.0}
MIN_LOCK_WAIT_SECONDS = 60
SHELL_OPERATOR_CHARACTERS = frozenset("();<>|&")
LOCK_FLAG_NAMES = frozenset({"-lock", "-lock-timeout"})
SHELL_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\+?)=(.*)", re.DOTALL)
SHELL_EXPANSION = re.compile(r"[$`]")
SHELL_VARIABLE_WORD = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
CONCURRENCY_KEY = re.compile(
    r"\$\{\{\s*github\.event_name == '([a-z_]+)' && format\('([^']*)', github\.ref\) \|\| '([^']*)'\s*\}\}"
)
CONTEXT_SUBSTITUTION = re.compile(r"\$\{\{\s*github\.(ref|workflow)\s*\}\}")
INFRA_EVENTS = frozenset({"pull_request", "push", "workflow_dispatch"})
APPLYING_EVENTS = frozenset({"push", "workflow_dispatch"})
SAMPLE_REFS = ("refs/heads/main", "refs/heads/elsewhere", "refs/pull/7/merge", "refs/pull/8/merge")
NAME_KEYS = {"PROJECT": "project_name", "PROJECT_NAME": "project_name", "ENVIRONMENT": "environment"}
VARIABLE_READ = re.compile(r"vars\.([A-Za-z_][A-Za-z0-9_]*)|vars\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]")

_spec = importlib.util.spec_from_file_location("tf_var_guard", ROOT / ".github" / "scripts" / "tf_var_guard.py")
GUARD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GUARD)

RETIRED_VARIABLES = (
    "API_BASE_URL",
    "VITE_COGNITO_USER_POOL_ID",
    "VITE_COGNITO_USER_POOL_CLIENT_ID",
    "VITE_COGNITO_DOMAIN",
    "VITE_S3_USER_SPACE_BUCKET",
    "VITE_S3_SHARED_SPACE_BUCKET",
)
SURVIVING_VARIABLE = "AWS_REGION"

PATH_WORD = re.compile(r"[A-Za-z0-9_./-]+")
CD_TARGET = re.compile(r"(?:^|[\s;&|(])(?:cd|pushd)\s+['\"]?([A-Za-z0-9_./-]+)")
WORKSPACE_PREFIX = "GITHUB_WORKSPACE/"
PATH_FILTERED = frozenset(
    {"deploy-config.yml", "deploy-infra.yml", "deploy-lambdas.yml", "lambda-image.yml", "spa-image.yml"}
)
KNOWN_REFERENCES = (
    ("deploy-infra.yml", ".github/checkov-plan-accepted.txt"),
    ("deploy-infra.yml", ".github/scripts/apply-gate.sh"),
    ("deploy-config.yml", "config/feature-flags.json"),
)
UNSELECTED_PATH = "docs/architecture.md"
SPELLING_CORPUS_FILES = frozenset({".github/scripts/x.sh", "lambdas/fleet.py"})
UNFILTERED_ON_PUSH = frozenset({"deploy-lambda-image.yml", "deploy-spa-image.yml"})


def _workflows() -> list[pathlib.Path]:
    """Every workflow file, under either extension GitHub reads, refusing an empty directory.

    Args:
      None.

    Returns:
      The workflow paths, sorted.

    Raises:
      AssertionError: If the directory holds no workflow, which would make every sweep
        below report agreement over nothing.
    """
    found = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert found, "no workflows found — every assertion in this module would be vacuous"
    return found


def test_every_workflow_declaring_an_opentofu_version_declares_the_same_one() -> None:
    """The predicate is *declares a version*, not *runs `tofu init`*, and that is load-bearing.

    A workflow can read an output through ``resolve-config.sh`` without an init of its own,
    so an init-based predicate would exclude the very consumer this derivation exists to
    cover. ``ci.yml`` pins a version and runs no deploy at all, and is included for the same
    reason.

    The comparison is over the constraint strings AS DECLARED. They read ``~1.8``, which is a
    constraint and not a version, so "they agree" can only mean the declarations are one
    string — claiming they resolve to one version would be claiming something the workflow
    files cannot state.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If nothing declares a version, or two declarations differ.
    """
    declared: dict[str, set[str]] = {}
    for path in _workflows():
        versions = set(re.findall(r"^\s*tofu_version:\s*(\S+)\s*$", path.read_text(), re.MULTILINE))
        if versions:
            declared[path.name] = versions

    assert declared, "no workflow declares an OpenTofu version — this comparison has no subject"
    assert "deploy-infra.yml" in declared, "the infrastructure workflow stopped declaring a version"

    distinct = set().union(*declared.values())
    assert len(distinct) == 1, f"OpenTofu version declarations disagree: {declared}"


def test_every_tofu_init_names_the_same_backend_configuration() -> None:
    """One state, addressed one way, however many workflows read it.

    Derived rather than counted: the number of init sites is expected to grow, and a test
    asserting how many there are would have to be edited by the change that adds one — which
    is exactly when nobody re-derives what it was protecting.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If no init is found, or two of them name different backend keys.
    """
    per_file: dict[str, set[frozenset[str]]] = {}
    for path in _workflows():
        text = path.read_text()
        for block in re.findall(r"tofu init((?:\s*\\\s*\n\s*-backend-config=\"[^\"]+\")+)", text):
            keys = frozenset(re.findall(r'-backend-config="([a-z_]+)=', block))
            per_file.setdefault(path.name, set()).add(keys)

    assert per_file, "no `tofu init` with backend configuration found — no subject"
    assert "deploy-config.yml" in per_file, "deploy-config.yml does not init the backend"

    distinct = {keys for entries in per_file.values() for keys in entries}
    assert len(distinct) == 1, f"backend configurations disagree: {per_file}"
    assert distinct.pop() == frozenset({"bucket", "dynamodb_table", "region"})


def test_no_workflow_reads_a_retired_repository_variable() -> None:
    """The values moved to Terraform state; a surviving reference reads a stale copy.

    The positive control is the point of the second half. A sweep whose matcher had stopped
    matching would report every retired name absent and pass — the same shape as success —
    so it must first prove it can still find a variable that IS there.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the matcher finds nothing at all, or any retired name survives.
    """
    references: dict[str, set[str]] = {}
    for path in _workflows():
        found = _reads(path)
        if found:
            references[path.name] = found

    seen = set().union(*references.values()) if references else set()
    assert SURVIVING_VARIABLE in seen, (
        f"the sweep did not find {SURVIVING_VARIABLE}, which is still referenced — "
        "the matcher is broken, so its report of absences means nothing"
    )

    surviving = sorted(
        f"{name}:{variable}"
        for name, found in references.items()
        for variable in found
        if variable in RETIRED_VARIABLES
    )
    assert surviving == [], f"retired repository variables still read: {surviving}"


def test_the_resolve_refusal_lands_before_any_aws_write() -> None:
    """A failed resolve must leave every live surface exactly as it was.

    The credentials step moved above the resolve because reading remote state is an AWS
    call, and that is safe only because it is a READ. If a write ever preceded the resolve,
    a job could half-update a bucket and then fail on a value it could have checked first.

    Derived over EVERY workflow that resolves, not written against one. Both deploy
    workflows resolve now and a third is expected, and the one that most needs this is
    ``deploy-config.yml``: it deleted its own empty-bucket guard in favour of the resolver,
    so it has no second line of defence between an unresolved destination and an
    ``aws s3 cp``.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If no workflow resolves, if one has no AWS write to order against,
        or if any write precedes its resolve.
    """
    resolvers = {path.name: path.read_text() for path in _workflows() if RESOLVE_STEP in path.read_text()}

    assert resolvers.keys() >= {"deploy-config.yml"}, (
        f"expected the publishing workflow to resolve, found {sorted(resolvers)}"
    )

    early: dict[str, list[str]] = {}
    for name, text in resolvers.items():
        resolve_at = text.find(RESOLVE_STEP)
        writes = [
            (match.start(), match.group(0).strip())
            for match in re.finditer(
                r"^\s+aws (?:s3 (?:cp|sync)|cloudfront create-invalidation)[^\n]*", text, re.MULTILINE
            )
        ]
        assert writes, f"no AWS writes found in {name} — the ordering claim has no subject there"

        preceding = [command for position, command in writes if position < resolve_at]
        if preceding:
            early[name] = preceding

    assert early == {}, f"AWS writes precede the configuration resolve: {early}"



def _reads(path: pathlib.Path) -> set[str]:
    """Every Actions variable a workflow reads, upper-cased as GitHub stores the name.

    Both expression syntaxes count — ``vars.NAME`` and ``vars['NAME']`` — and the lookup is
    case-insensitive, so a sweep keyed on one spelling would let the other through.

    Args:
      path: The workflow file.

    Returns:
      The variable names.

    Raises:
      None.
    """
    return {(dotted or indexed).upper() for dotted, indexed in VARIABLE_READ.findall(path.read_text(encoding="utf-8"))}


def _terraform_steps() -> list[tuple[str, dict, str | None, bool]]:
    """Every workflow step that runs a plan or an apply, refusing a population missing either.

    Args:
      None.

    Returns:
      For each step: the workflow's file name; the step as YAML loads it; the shell it runs under
      if anything overrides the default — the step itself, its job, or the workflow; and whether
      the step or its job continues on error.

    Raises:
      AssertionError: If no step plans or no step applies, which would make every assertion
        over these steps agree with nothing.
    """
    steps = []
    for path in _workflows():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        workflow_shell = ((document.get("defaults") or {}).get("run") or {}).get("shell")
        for job in (document.get("jobs") or {}).values():
            job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell") or workflow_shell
            steps.extend(
                (
                    path.name,
                    step,
                    step.get("shell") or job_shell,
                    bool(step.get("continue-on-error") or job.get("continue-on-error")),
                )
                for step in job.get("steps") or []
                if TOFU_RUN.search(step.get("run", ""))
            )
    kinds = {TOFU_RUN.search(step["run"]).group(1) for _, step, _, _ in steps}
    assert kinds == {"plan", "apply"}, f"expected a plan step and an apply step, found {sorted(kinds)}"
    return steps


def _declared(step: dict) -> set[str]:
    """The variables the module a step runs `tofu` in declares, refusing a module declaring none.

    Args:
      step: A plan or apply step, as YAML loads it.

    Returns:
      The declared names, spelled as OpenTofu matches them.

    Raises:
      AssertionError: If the step's working directory declares no variable, which would make
        every environment key read as undeclared for the wrong reason.
    """
    module = ROOT / step.get("working-directory", ".")
    names = GUARD.declared(module)
    assert "github_repo" in names, f"{module} declares no github_repo — the parse or the directory is wrong"
    return names


def _terraform_receives() -> set[str]:
    """The Terraform variables every plan and apply is handed from the Actions variable of that name.

    A key counts only when its suffix is exactly a declared variable, because OpenTofu matches the
    spelling case-sensitively and ignores anything else. A variable handed to one run and not the
    other is excluded: the apply is what builds, and a plan that disagrees with it reviews a
    deployment nobody will get.

    Args:
      None.

    Returns:
      The variable names, as declared.

    Raises:
      AssertionError: If `github_repo`, a required input every run is handed, is not found —
        the parse is broken and an empty set would refuse every read for the wrong reason.
    """
    per_step = []
    for _, step, _, _ in _terraform_steps():
        names = _declared(step)
        per_step.append(
            {
                key[len("TF_VAR_") :]
                for key, value in (step.get("env") or {}).items()
                if key.startswith("TF_VAR_")
                and key[len("TF_VAR_") :] in names
                and re.search(r"vars\.\s*" + re.escape(key) + r"\b", str(value), re.IGNORECASE)
            }
        )
    received = set.intersection(*per_step)
    assert "github_repo" in received, f"the parse lost github_repo; it found {sorted(received)}"
    return received


def test_every_tf_var_a_tofu_step_sets_names_a_declared_variable() -> None:
    """OpenTofu ignores a `TF_VAR_` it has no variable for, so a misspelt key hands over nothing.

    The spelling is case-sensitive: `TF_VAR_SPA_SUBDOMAIN`, the name GitHub's settings page shows,
    is not `spa_subdomain`, and a plan given it builds from the default without a warning.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any plan or apply step sets a `TF_VAR_` key naming no declared variable.
    """
    undeclared = sorted(
        f"{workflow}: {step.get('name', 'unnamed step')}: {key}"
        for workflow, step, _, _ in _terraform_steps()
        for key in (step.get("env") or {})
        if key.startswith("TF_VAR_") and key[len("TF_VAR_") :] not in _declared(step)
    )
    assert undeclared == [], f"TF_VAR_ keys naming no declared variable: {undeclared}"


def test_every_tf_var_a_workflow_reads_is_handed_to_terraform() -> None:
    """A workflow reads a Terraform input only when Terraform is handed the same variable.

    The failure this pins was a set of name variables every deploy workflow built resource names
    from while no plan or apply received them: setting one would have pointed the workflows at
    resources Terraform never built, and every run in between reads green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any workflow reads a `TF_VAR_*` Actions variable that some plan or
        apply is not handed under its own name.
    """
    received = {name.upper() for name in _terraform_receives()}
    stray = sorted(
        f"{path.name}:{name}"
        for path in _workflows()
        for name in _reads(path)
        if name.startswith("TF_VAR_") and name[len("TF_VAR_") :] not in received
    )
    assert stray == [], f"workflows read TF_VAR_ variables Terraform is never handed: {stray}"


def test_every_plan_and_apply_runs_the_tf_var_guard_first() -> None:
    """The runtime half of the rule above has to be in the step, or it guards nothing.

    The guard reads the environment of the process that runs it, so run anywhere but the
    `tofu` step it compares nothing against what Terraform receives. It needs `toJSON(vars)` to
    see what is set, its own line with nothing after it so no `|| true` can swallow its exit, the
    default `bash -e` shell so that exit ends the step, and no `continue-on-error` to turn the
    ended step back into a green job.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plan or apply step does not start with the guard, does not pass it
        the variables, names a script path that does not exist, overrides the shell, or
        continues on error.
    """
    problems = []
    for workflow, step, shell, continues in _terraform_steps():
        where = f"{workflow}: {step.get('name', 'unnamed step')}"
        first = step["run"].strip().splitlines()[0].strip()
        if not GUARD_LINE.fullmatch(first):
            problems.append(f"{where} does not run the guard as its first line (found {first!r})")
        else:
            script = ROOT / step.get("working-directory", ".") / first.split(" ", 1)[1]
            if not script.resolve().is_file():
                problems.append(f"{where} runs {first.split(' ', 1)[1]}, which does not exist")
        if (step.get("env") or {}).get("REPO_VARS") != "${{ toJSON(vars) }}":
            problems.append(f"{where} does not pass REPO_VARS as toJSON(vars)")
        if shell is not None:
            problems.append(f"{where} runs under {shell!r}, not the default, so a failing guard may not end it")
        if continues:
            problems.append(f"{where} continues on error, so a failing guard leaves the job green")
    assert problems == [], problems


def _words(line: str) -> list[str]:
    """One line of shell split into words the way the shell reads them, comments and quotes removed.

    Args:
      line: One line of a `run` block, its continuations already joined.

    Returns:
      The words, with each run of shell operators (`&&`, `|`, `>&`, `;`) as a word of its own.

    Raises:
      ValueError: If the line's quoting is unbalanced.
    """
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _seconds(duration: str) -> float | None:
    """A Go duration such as `15m` or `1m30s` in seconds, as `-lock-timeout` reads it.

    Args:
      duration: The flag's value.

    Returns:
      The duration in seconds, or None when it is not a non-negative duration with a unit.

    Raises:
      None.
    """
    unsigned = duration.removeprefix("+")
    parts = DURATION_PART.findall(unsigned)
    if not parts or "".join(number + unit for number, unit in parts) != unsigned:
        return None
    return sum(float(number) * UNIT_SECONDS[unit] for number, unit in parts)


def _tofu_commands(words: list[str]) -> tuple[list[list[str]], list[str]]:
    """The arguments of each `tofu plan` or `tofu apply` in one line's words, and every other word.

    Args:
      words: One line, split by `_words`.

    Returns:
      For each plan or apply, the words after its subcommand up to the next shell operator; and
      the words that belong to none of them, so a plan or apply the parse did not read stays visible.

    Raises:
      None.
    """
    commands, rest = [], []
    position = 0
    while position < len(words):
        word = words[position]
        subcommand = position + 1
        while subcommand < len(words) and words[subcommand].startswith("-"):
            subcommand += 1
        is_tofu = word == "tofu" or word.endswith("/tofu")
        if is_tofu and subcommand < len(words) and words[subcommand] in ("plan", "apply"):
            end = subcommand + 1
            while end < len(words) and not set(words[end]) <= SHELL_OPERATOR_CHARACTERS:
                end += 1
            commands.append(words[subcommand + 1 : end])
            position = end
        else:
            rest.append(word)
            position += 1
    return commands, rest


def _flag_problems(arguments: list[str]) -> list[str]:
    """Why one plan's or apply's literal flags would not wait for the state lock, if they would not.

    Reads the flags as `tofu` does: `--flag` is `-flag`, a non-boolean flag takes `=value` or the
    next word, a bare `-lock` is true, and the last of a repeated flag wins.

    Args:
      arguments: The words after `plan` or `apply` that this can read.

    Returns:
      Each reason, empty when the command waits.

    Raises:
      None.
    """
    lock, timeout = "true", ""
    position = 0
    while position < len(arguments):
        flag = arguments[position]
        flag = flag[1:] if flag.startswith("--") else flag
        name, equals, value = flag.partition("=")
        if name == "-lock":
            lock = value if equals else "true"
        elif name == "-lock-timeout":
            if not equals:
                position += 1
                value = arguments[position] if position < len(arguments) else ""
            timeout = value
        position += 1
    problems = []
    if lock in LOCK_OFF_VALUES:
        problems.append("it skips the lock, so it reads state an apply may be changing")
    seconds = _seconds(timeout)
    if seconds is None or seconds < MIN_LOCK_WAIT_SECONDS:
        problems.append(
            "its last -lock-timeout is not a wait of a minute or more, so it fails on a lock it should wait for"
        )
    return problems


def _argument_problems(arguments: list[str], assignments: dict[str, list[str | None]]) -> list[str]:
    """Why one plan's or apply's arguments would not wait for the state lock, or cannot be read.

    Lock flags must be written literally on the command. A variable may stand for other flags when
    every value the step assigns it is literal and names no lock flag; a non-lock flag's value, or
    a word after a literal prefix, may expand. Anything else that expands is refused unread.

    Args:
      arguments: The words after `plan` or `apply`.
      assignments: Each variable the step assigns, mapped to its values, None for one not literal.

    Returns:
      Each reason, empty when the command waits.

    Raises:
      None.
    """
    readable, problems = [], []
    for word in arguments:
        if not SHELL_EXPANSION.search(word):
            readable.append(word)
            continue
        variable = SHELL_VARIABLE_WORD.fullmatch(word)
        name, equals, _ = (word[1:] if word.startswith("--") else word).partition("=")
        names_another_flag = bool(equals) and name.startswith("-") and name not in LOCK_FLAG_NAMES
        if variable:
            values = assignments.get(variable.group(1) or variable.group(2), [])
            if not values or None in values:
                problems.append(f"it passes {word!r}, whose value the step does not assign literally")
            elif any(LOCK_FLAG.search(value or "") for value in values):
                problems.append(f"it passes {word!r}, which can carry a lock flag; write lock flags on the command")
        elif (names_another_flag and not SHELL_EXPANSION.search(name)) or not word.startswith(("$", "`", "-")):
            readable.append(word)
        else:
            problems.append(f"it passes {word!r}, which this cannot read")
    return problems + _flag_problems(readable)


def _lock_problems(run: str) -> list[str]:
    """Why a `run` block's `tofu plan` or `tofu apply` would not wait for the state lock, if it would not.

    A pull request's plan queues in a concurrency group of its own, so a plan and an apply can start
    together, and under the default `-lock-timeout` of 0s `tofu` fails whichever reaches the lock
    second: a lost apply when that is the apply. A skipped lock never blocks an apply, but the plan
    is then computed while one changes what it refreshes against. A minute is the floor because a
    plan holds the lock for about that long. It reads a small language and refuses the rest: a plan
    or apply it cannot parse as a command, such as one inside `$(...)` or `bash -c`, is refused
    rather than passed, since shell has more spellings than any check can read.

    Args:
      run: A step's `run` block.

    Returns:
      Each reason, empty when every plan and apply in the block waits.

    Raises:
      None.
    """
    if "tofu" not in run:
        return []
    problems: list[str] = []
    assignments: dict[str, list[str | None]] = {}
    lines = []
    for line in run.replace("\\\n", " ").splitlines():
        try:
            words = _words(line)
        except ValueError:
            if TOFU_RUN.search(line):
                problems.append(f"{line.strip()!r} cannot be read as shell")
            continue
        lines.append(words)
        for word in words:
            assignment = SHELL_ASSIGNMENT.fullmatch(word)
            if assignment:
                name, append, value = assignment.groups()
                literal = not append and not SHELL_EXPANSION.search(value)
                assignments.setdefault(name, []).append(value if literal else None)
    for words in lines:
        commands, rest = _tofu_commands(words)
        if TOFU_RUN.search(" ".join(rest)):
            problems.append(f"{' '.join(words)!r} runs a plan or apply this cannot read as a command")
        for arguments in commands:
            problems.extend(_argument_problems(arguments, assignments))
    return list(dict.fromkeys(problems))


def _cli_arguments_problems(document: dict[Any, Any]) -> list[str]:
    """Each place a workflow hands `tofu` flags through `TF_CLI_ARGS` that may change the state lock.

    `TF_CLI_ARGS` and `TF_CLI_ARGS_<command>` add flags to a command from the environment, out of
    sight of a check that reads the command line. They are read only from an `env` block, where the
    value is plain: one there naming a lock flag or taking its value from elsewhere is refused, as is
    an `env` built from an expression and any step that sets one in its `run` block.

    Args:
      document: The workflow, as `yaml.safe_load` returns it.

    Returns:
      Each refusal, empty when no such variable can change the lock.

    Raises:
      None.
    """
    jobs = [job for job in (document.get("jobs") or {}).values() if isinstance(job, dict)]
    steps = [step for job in jobs for step in job.get("steps") or [] if isinstance(step, dict)]
    problems = []
    for level in [document, *jobs, *steps]:
        env = level.get("env")
        if env is not None and not isinstance(env, dict):
            problems.append(f"env {env!r} is built from an expression, so a TF_CLI_ARGS in it cannot be read")
            continue
        for key, value in (env or {}).items():
            unreadable = LOCK_FLAG.search(str(value)) or SHELL_EXPANSION.search(str(value))
            if str(key).startswith("TF_CLI_ARGS") and unreadable:
                problems.append(f"env {key}: {value!r}")
    for step in steps:
        for line in str(step.get("run", "")).replace("\\\n", " ").splitlines():
            if "TF_CLI_ARGS" not in line:
                continue
            try:
                named = any("TF_CLI_ARGS" in word for word in _words(line))
            except ValueError:
                named = True
            if named:
                problems.append(f"run: {line.strip()!r} sets TF_CLI_ARGS where this cannot read it; use an env block")
    return problems


APPLY_BLOCK = (
    'REFRESH_FLAG=""\n'
    'if [ "${{ inputs.skip_refresh }}" = "true" ]; then\n'
    '  REFRESH_FLAG="-refresh=false"\n'
    "fi\n"
    "tofu apply -auto-approve -lock-timeout=10m $REFRESH_FLAG\n"
)
NO_WAIT = "not a wait of a minute"
NO_LOCK = "skips the lock"
UNREAD = "cannot read"
NOT_LITERAL = "does not assign literally"
CARRIES = "can carry a lock flag"
NOT_A_COMMAND = "cannot read as a command"


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        pytest.param("set -o pipefail && tofu plan -lock-timeout=15m -out=tfplan 2>&1 | tee x", None, id="plan"),
        pytest.param(APPLY_BLOCK, None, id="apply-with-a-variable-assigned-in-the-step"),
        pytest.param("tofu plan -lock-timeout 15m", None, id="value-as-the-next-word"),
        pytest.param("tofu plan --lock-timeout=15m", None, id="double-dash"),
        pytest.param("tofu plan -lock-timeout=1m30s", None, id="compound-duration"),
        pytest.param("tofu plan -lock-timeout=+15m", None, id="signed-duration"),
        pytest.param("tofu plan -lock-timeout=60s", None, id="exactly-a-minute"),
        pytest.param('tofu plan -lock-timeout="10m"', None, id="quoted-value"),
        pytest.param("tofu plan -lock=TRUE -lock=1 -lock-timeout=15m", None, id="lock-on-spelled-otherwise"),
        pytest.param("tofu plan -lock -lock-timeout=15m", None, id="bare-lock-is-on"),
        pytest.param("tofu plan -lock=false -lock=true -lock-timeout=15m", None, id="last-lock-wins-on"),
        pytest.param("tofu plan \\\n  -lock-timeout=15m", None, id="timeout-on-a-continuation"),
        pytest.param("tofu -chdir=infra \\\n  plan -lock-timeout=15m", None, id="global-flag-on-a-continuation"),
        pytest.param("/usr/local/bin/tofu plan -lock-timeout=15m", None, id="tofu-by-path"),
        pytest.param('tofu plan -lock-timeout=15m -var "tag=$TAG" -out="$PLAN"', None, id="expanded-non-lock-values"),
        pytest.param("tofu plan -lock-timeout=15m|tee -lock=false", None, id="an-operator-ends-the-command"),
        pytest.param("# tofu plan -lock=false\ntofu plan -lock-timeout=15m", None, id="a-comment-is-not-a-command"),
        pytest.param("tofu init -backend=false\ntofu output -raw name", None, id="no-plan-or-apply"),
        pytest.param("tofu plan -out=tfplan", NO_WAIT, id="no-timeout"),
        pytest.param("tofu -chdir=infra plan -out=tfplan", NO_WAIT, id="no-timeout-after-a-global-flag"),
        pytest.param("tofu apply -lock-timeout=0s", NO_WAIT, id="zero"),
        pytest.param("tofu apply -lock-timeout=59s", NO_WAIT, id="under-a-minute"),
        pytest.param("tofu apply -lock-timeout=0", NO_WAIT, id="bare-zero"),
        pytest.param("tofu apply -lock-timeout=-15m", NO_WAIT, id="negative"),
        pytest.param("tofu apply -lock-timeout=15minutes", NO_WAIT, id="not-a-duration"),
        pytest.param("tofu apply -lock-timeout=10m -lock-timeout 0s", NO_WAIT, id="last-flag-zero"),
        pytest.param("tofu apply -lock-timeout=10m --lock-timeout=0s", NO_WAIT, id="last-flag-zero-double-dash"),
        pytest.param("tofu apply -auto-approve  # -lock-timeout=10m", NO_WAIT, id="timeout-in-a-comment"),
        pytest.param("tofu plan -lock-timeout=15m -lock=false", NO_LOCK, id="lock-false"),
        pytest.param("tofu plan -lock-timeout=15m --lock=false", NO_LOCK, id="lock-false-double-dash"),
        pytest.param("tofu plan -lock-timeout=15m -lock=0", NO_LOCK, id="lock-zero"),
        pytest.param("tofu plan -lock-timeout=15m -lock=F", NO_LOCK, id="lock-f"),
        pytest.param("tofu plan -lock-timeout=15m -lock=False", NO_LOCK, id="lock-capital-false"),
        pytest.param("tofu plan -lock-timeout=15m -lock=FALSE", NO_LOCK, id="lock-upper-false"),
        pytest.param("tofu plan -lock-timeout=15m -lock=true -lock=false", NO_LOCK, id="last-lock-wins-off"),
        pytest.param("tofu apply -lock-timeout=10m \\\n  -lock=false", NO_LOCK, id="lock-off-on-a-continuation"),
        pytest.param('F="-lock=false"\ntofu apply -lock-timeout=10m $F', CARRIES, id="lock-off-in-a-variable"),
        pytest.param('F="-x"\nF="-lock=false"\ntofu apply -lock-timeout=10m $F', CARRIES, id="last-assignment"),
        pytest.param('F="-lock=false"\nF="-x"\ntofu apply -lock-timeout=10m $F', CARRIES, id="first-assignment"),
        pytest.param("[ -n x ] && T=-lock-timeout=15m\ntofu plan $T", CARRIES, id="timeout-in-a-variable"),
        pytest.param("tofu apply -lock-timeout=10m $EXTRA", NOT_LITERAL, id="variable-from-elsewhere"),
        pytest.param('A="${{ inputs.args }}"\ntofu plan -lock-timeout=15m $A', NOT_LITERAL, id="assigned-expression"),
        pytest.param('A="-x $B"\ntofu plan -lock-timeout=15m $A', NOT_LITERAL, id="assigned-a-variable"),
        pytest.param("A=$(cat f)\ntofu plan -lock-timeout=15m $A", NOT_LITERAL, id="assigned-a-substitution"),
        pytest.param('A="-x"\nA+=" -lock=false"\ntofu plan -lock-timeout=15m $A', NOT_LITERAL, id="appended-to"),
        pytest.param("tofu apply -lock-timeout=$WAIT", UNREAD, id="lock-flag-from-a-variable"),
        pytest.param("tofu plan -lock-timeout=${{ vars.WAIT }}", UNREAD, id="lock-flag-from-an-expression"),
        pytest.param("tofu plan -lock-timeout=15m ${{ inputs.args }}", UNREAD, id="an-expression-as-arguments"),
        pytest.param("tofu plan -lock-timeout=15m $(cat flags)", UNREAD, id="a-substitution-as-arguments"),
        pytest.param('tofu plan -lock-timeout=15m "$@"', UNREAD, id="the-script-arguments"),
        pytest.param('PLAN="$(tofu plan -lock=false 2>&1)"', NOT_A_COMMAND, id="captured-in-a-substitution"),
        pytest.param('echo "$(tofu apply -auto-approve)"', NOT_A_COMMAND, id="echoed-substitution"),
        pytest.param("X=`tofu plan`", NOT_A_COMMAND, id="backticks"),
        pytest.param("bash -c 'tofu plan -lock=false'", NOT_A_COMMAND, id="another-shell"),
        pytest.param("tofu plan -var='{", "cannot be read as shell", id="unbalanced-quote"),
    ],
)
def test_the_lock_check_reads_each_spelling_of_a_wait(run: str, expected: str | None) -> None:
    """The lock check refuses each spelling that leaves a plan or an apply not waiting or unread, and only those.

    Args:
      run: A `run` block.
      expected: A phrase a refusal must carry, or None for a block that waits.

    Returns:
      None.

    Raises:
      AssertionError: If the check misses the block's reason or refuses a block that waits.
    """
    problems = _lock_problems(run)
    if expected is None:
        assert problems == [], problems
    else:
        assert any(expected in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("step", "job", "workflow", "refused"),
    [
        pytest.param({"run": "tofu plan"}, None, {"env": {"TF_CLI_ARGS_plan": "-lock=false"}}, True, id="workflow-env"),
        pytest.param(
            {"run": "tofu plan"}, {"env": {"TF_CLI_ARGS": "${{ vars.FLAGS }}"}}, {},
            True,
            id="job-env-elsewhere",
        ),
        pytest.param(
            {"run": "tofu plan", "env": {"TF_CLI_ARGS_plan": "-x\n-lock=0"}}, None, {},
            True,
            id="step-env-block",
        ),
        pytest.param({"run": "tofu plan"}, {"env": "${{ fromJSON(vars.ENV) }}"}, {}, True, id="env-from-an-expression"),
        pytest.param(
            {"run": 'echo "TF_CLI_ARGS_apply=-lock=0" >> "$GITHUB_ENV"'}, None, {},
            True,
            id="written-by-a-step",
        ),
        pytest.param({"run": "printf 'TF_CLI_ARGS_plan=%s' -lock=false >> f"}, None, {}, True, id="printf-by-a-step"),
        pytest.param({"run": 'export TF_CLI_ARGS_apply="$FLAGS"'}, None, {}, True, id="exported-from-a-variable"),
        pytest.param({"run": "echo 'TF_CLI_ARGS_plan=-x"}, None, {}, True, id="unbalanced-quote"),
        pytest.param(
            {"run": "tofu plan", "env": {"TF_CLI_ARGS_plan": "-parallelism=20"}}, None, {},
            False,
            id="no-lock-flag",
        ),
        pytest.param(
            {"run": "# never set TF_CLI_ARGS: it could pass -lock=false\ntofu plan"}, None, {},
            False,
            id="comment",
        ),
    ],
)
def test_the_environment_check_reads_each_way_tofu_is_handed_a_lock_flag(
    step: dict[str, Any], job: dict[str, Any] | None, workflow: dict[str, Any], refused: bool
) -> None:
    """The environment check refuses a `TF_CLI_ARGS` that may carry a lock flag or cannot be read, and only that.

    Args:
      step: The one step's keys.
      job: The job's keys other than its steps.
      workflow: Top-level keys such as `env`.
      refused: Whether the check must refuse the workflow.

    Returns:
      None.

    Raises:
      AssertionError: If the check misses the variable or refuses one with no lock flag.
    """
    problems = _cli_arguments_problems(_one_step_workflow(step, job, **workflow))
    assert bool(problems) is refused, problems


def test_every_plan_and_apply_waits_for_the_state_lock() -> None:
    """Every `tofu plan` and `tofu apply` any workflow step runs waits for the state lock, and no environment undoes it.

    Every step is read, not only those a plan or apply regex selects, so a command the selection
    would miss is still refused.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plan or apply does not wait or cannot be read, or a workflow hands `tofu`
        a `TF_CLI_ARGS` that may change the lock.
    """
    problems = []
    planned = 0
    for path in _workflows():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (document.get("jobs") or {}).values():
            for step in (job or {}).get("steps") or []:
                run = str(step.get("run", ""))
                for line in run.replace("\\\n", " ").splitlines():
                    if "tofu" in line:
                        try:
                            planned += len(_tofu_commands(_words(line))[0])
                        except ValueError:
                            pass
                where = f"{path.name}: {step.get('name', 'unnamed step')}"
                problems.extend(f"{where}: {problem}" for problem in _lock_problems(run))
        problems.extend(f"{path.name}: {problem}" for problem in _cli_arguments_problems(document))
    assert planned >= 2, f"found {planned} plan or apply commands; the read has lost them"
    assert problems == [], problems


def _concurrency_group(expression: str, *, event: str, ref: str, workflow: str) -> str:
    """The concurrency group one run queues in, evaluated for its event, ref and workflow name.

    Substitutes `github.ref` and `github.workflow` where a group interpolates them, and evaluates
    the one whole-value expression shape `deploy-infra.yml` uses, `cond && format(...) || 'literal'`,
    with GitHub's semantics: the `format` value when the event matches and it is not empty, the
    literal otherwise. GitHub compares group names without case, so the result is lowercased.

    Args:
      expression: A `concurrency.group` value.
      event: The run's `github.event_name`.
      ref: The run's `github.ref`.
      workflow: The run's `github.workflow`, its workflow's name.

    Returns:
      The group's name for that run, lowercased.

    Raises:
      AssertionError: If the group is an expression of another shape, which this cannot evaluate.
    """
    contexts = {"ref": ref, "workflow": workflow}
    text = CONTEXT_SUBSTITUTION.sub(lambda match: contexts[match.group(1)], expression).strip()
    if "${{" not in text:
        return text.lower()
    shape = CONCURRENCY_KEY.fullmatch(text)
    assert shape, f"_concurrency_group cannot read the group {expression!r}; teach it this shape"
    matched_event, template, otherwise = shape.groups()
    chosen = template.replace("{0}", ref)
    return (chosen if event == matched_event and chosen else otherwise).lower()


@functools.cache
def _workflow_document(path: pathlib.Path) -> dict[Any, Any]:
    """One workflow file parsed once, since the group checks read each many times over.

    Args:
      path: The workflow file.

    Returns:
      The workflow as `yaml.safe_load` returns it; callers must not change it.

    Raises:
      None.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _groups(path: pathlib.Path, *, event: str, ref: str) -> set[str]:
    """Every concurrency group a run of one workflow can queue in, at workflow and job level.

    Args:
      path: The workflow file.
      event: The run's event.
      ref: The run's ref.

    Returns:
      The evaluated group names, lowercased.

    Raises:
      AssertionError: If a group is an expression this cannot evaluate.
    """
    document = _workflow_document(path)
    workflow = document.get("name") or path.relative_to(ROOT).as_posix()
    jobs = (document.get("jobs") or {}).values()
    settings = [document.get("concurrency"), *((job or {}).get("concurrency") for job in jobs)]
    groups = set()
    for setting in settings:
        if setting:
            expression = setting.get("group") if isinstance(setting, dict) else setting
            groups.add(_concurrency_group(str(expression), event=event, ref=ref, workflow=workflow))
    return groups


def test_no_pull_request_run_queues_in_the_group_an_apply_queues_in() -> None:
    """A pull request's run never shares a concurrency group with an apply, and every apply shares one.

    GitHub keeps one pending run per group and cancels it when a newer run queues, whatever that
    run's event, so in a shared group a pull request opened while an apply waited cancelled the
    apply, and nothing re-ran it. Applies must still share one group, `deploy-infra`, so two never
    run at once: renaming it lets a run queued under the old name run beside one under the new.
    A trigger outside the three named here needs its group decided, since an event that does not
    apply would evict a pending apply from `deploy-infra`, and a job-level group would queue that
    job beside the workflow-level one. `cancel-in-progress` stays off, since cancelling a running
    plan can leave the state lock held.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the triggers change, a job declares its own group, a pull request's run
        shares the apply group or another pull request's group, an applying event queues anywhere
        but `deploy-infra`, or runs are cancelled in progress.
    """
    path = WORKFLOWS / "deploy-infra.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["concurrency"].get("cancel-in-progress") is False, "a run in progress could be cancelled"
    events = set(document.get(True, document.get("on")))
    assert events == INFRA_EVENTS, f"the triggers are {sorted(events)}; decide the group of each new one"
    nested = sorted(name for name, job in document["jobs"].items() if "concurrency" in (job or {}))
    assert nested == [], f"jobs {nested} declare their own concurrency group"
    applying = {
        group
        for event in APPLYING_EVENTS
        for ref in SAMPLE_REFS[:2]
        for group in _groups(path, event=event, ref=ref)
    }
    planning = [_groups(path, event="pull_request", ref=ref) for ref in SAMPLE_REFS[2:]]
    assert applying == {"deploy-infra"}, f"applying events queue in {sorted(applying)}, not in deploy-infra alone"
    assert not applying & (planning[0] | planning[1]), f"a pull request queues with the applies, in {planning}"
    assert not planning[0] & planning[1], f"two pull requests share {planning[0]}, so one evicts the other"


def test_no_other_workflow_queues_in_a_group_deploy_infra_uses() -> None:
    """No other workflow's run can land in a group a plan or an apply queues in.

    GitHub's group names are shared by every workflow in the repository and compared without case,
    so another workflow's run in `deploy-infra` would evict a pending apply, and one in a pull
    request's plan group, such as CI's group with `cancel-in-progress` on, could cancel a running
    plan that holds the state lock.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any other workflow's group, for any sampled event and ref, is one
        `deploy-infra.yml` uses for the same ref.
    """
    infra = WORKFLOWS / "deploy-infra.yml"
    clashes = []
    for ref in SAMPLE_REFS:
        ours = {group for event in INFRA_EVENTS for group in _groups(infra, event=event, ref=ref)}
        for path in _workflows():
            if path != infra:
                for event in INFRA_EVENTS:
                    theirs = _groups(path, event=event, ref=ref)
                    clashes.extend(f"{path.name} on {ref}: {group}" for group in theirs & ours)
    assert clashes == [], clashes


def test_workflow_name_literals_are_the_terraform_defaults() -> None:
    """Workflows write Terraform's name defaults out, so the two must be the same values.

    They used to read an Actions variable with the default as a fallback, which is the coupling
    the tests above now forbid; a literal keeps the agreement, and only this keeps it honest if
    a default in ``infra/variables.tf`` ever moves.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a default cannot be read, if no workflow names either value, or if any
        workflow's value differs from its default.
    """
    text = VARIABLES.read_text(encoding="utf-8")
    defaults = {}
    for variable in set(NAME_KEYS.values()):
        block = re.search(r'^variable\s+"' + variable + r'"\s*\{\n(.*?)^\}', text, re.MULTILINE | re.DOTALL)
        match = block and re.search(r'^\s*default\s*=\s*"([^"]+)"', block.group(1), re.MULTILINE)
        assert match, f"infra/variables.tf declares no string default for {variable}"
        defaults[variable] = match.group(1)

    sites = []
    for path in _workflows():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        blocks = [document.get("env") or {}]
        for job in (document.get("jobs") or {}).values():
            blocks.append(job.get("env") or {})
            blocks.extend(step.get("env") or {} for step in job.get("steps") or [])
        sites.extend(
            (path.name, key, str(value)) for block in blocks for key, value in block.items() if key in NAME_KEYS
        )

    assert {NAME_KEYS[key] for _, key, _ in sites} == set(defaults), (
        f"the sweep found no workflow naming one of {sorted(defaults)} — the matcher is broken"
    )
    wrong = sorted(
        f"{workflow}:{key}={value}" for workflow, key, value in sites if value != defaults[NAME_KEYS[key]]
    )
    assert wrong == [], f"workflow names that are not infra/variables.tf's defaults {defaults}: {wrong}"


def test_every_variable_a_workflow_reads_has_a_row_in_the_setup_table() -> None:
    """The setup guide's table claims to be every variable a workflow reads, so hold it to that.

    It drifted both ways before: four name overrides one workflow read never got a row, and a
    row outlived the last workflow that read its variable. Only the first direction is checked —
    a row for a variable nothing reads may be there to say it must stay unset.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the sweep finds no read at all, or a variable some workflow reads has
        no row in Step 3's table.
    """
    read = set().union(*(_reads(path) for path in _workflows()))
    assert SURVIVING_VARIABLE in read, f"the sweep did not find {SURVIVING_VARIABLE}; the matcher is broken"

    section = README.read_text(encoding="utf-8").split("### Step 3", 1)[1].split("\n### ", 1)[0]
    documented = {
        name.upper()
        for line in section.splitlines()
        if line.startswith("|")
        for name in re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", line.split("|")[1])
    }
    assert sorted(read - documented) == [], "variables read with no row in the README's Step 3 table"


def _tracked_files() -> frozenset[str]:
    """Every file git tracks, which is exactly what a CI checkout holds.

    The index rather than the disk, because a local plan or scan leaves generated files
    beside the ones a step reads, and a step naming one would then demand a filter entry
    for a file CI never has. ``-z`` because git C-quotes a path that is not plain ASCII.

    Args:
      None.

    Returns:
      The repository-relative paths.

    Raises:
      AssertionError: If the listing misses a file it must hold, which would make every
        reference below read as absent rather than unfiltered.
    """
    git = shutil.which("git") or "git"
    listing = subprocess.run(  # noqa: S603
        [git, "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    tracked = frozenset(name for name in listing.stdout.split("\0") if name)
    assert ".github/workflows/deploy-infra.yml" in tracked, "git ls-files returned no workflow"
    return tracked


def _path_filters(document: dict[Any, Any]) -> dict[str, list[str]]:
    """The ``paths:`` list of each event in a workflow that declares one.

    PyYAML reads the ``on:`` key as the boolean ``True``, so both spellings are tried.

    Args:
      document: The parsed workflow.

    Returns:
      Each filtered event's name mapped to its entries; empty for an unfiltered workflow.

    Raises:
      AssertionError: If an event uses ``paths-ignore``, whose selection is the inverse and
        which this derivation would otherwise skip as unfiltered.
    """
    triggers = document.get(True, document.get("on"))
    if not isinstance(triggers, dict):
        return {}
    filters = {}
    for event, config in triggers.items():
        if not isinstance(config, dict):
            continue
        assert "paths-ignore" not in config, (
            f"`{event}` uses paths-ignore; teach this derivation before relying on it"
        )
        if "paths" in config:
            filters[event] = config["paths"]
    return filters


def _filter_selects(globs: list[str], path: str) -> bool:
    """Whether a ``paths:`` list selects one repository path.

    Only the three shapes these workflows use are understood — a literal path, a ``dir/**``
    prefix, and a single ``*`` inside one path segment (``infra/plane-*.tf``), which GitHub
    matches against any characters but ``/``. Every entry is checked before any is matched,
    and anything else RAISES rather than being approximated: a matcher that quietly mishandles
    a shape reports a file as covered for the wrong reason, which is the failure this exists to
    catch.

    Args:
      globs: The filter's entries.
      path: A repository-relative path.

    Returns:
      True if some entry selects the path.

    Raises:
      AssertionError: If an entry uses a pattern character this matcher does not implement.
    """
    for glob in globs:
        literal = glob.removesuffix("/**")
        assert not re.search(r"[?\[\]!+]", literal) and "**" not in literal, (
            f"`{glob}` is a filter shape this test does not implement; teach the matcher "
            "rather than letting it approximate"
        )
    return any(
        path == glob
        or (glob.endswith("/**") and path.startswith(glob.removesuffix("**")))
        or (
            not glob.endswith("/**")
            and "*" in glob
            and re.fullmatch("[^/]*".join(re.escape(part) for part in glob.split("*")), path)
            is not None
        )
        for glob in globs
    )


def _candidates(word: str, bases: list[str]) -> set[str]:
    """The repository paths one word from a ``run:`` block could name.

    A word that starts with ``/`` is what ``${{ github.workspace }}/…`` and
    ``${GITHUB_WORKSPACE}/…`` leave once the expression is split off, and
    ``$GITHUB_WORKSPACE/…`` leaves the variable's name in front: both are read from the
    root. Any other word is read from every base.

    Args:
      word: A maximal run of path characters.
      bases: The directories the word may be relative to.

    Returns:
      The normalised paths the word could name.

    Raises:
      None.
    """
    if word.startswith("/"):
        return {posixpath.normpath(word.lstrip("/"))}
    if word.startswith(WORKSPACE_PREFIX):
        return {posixpath.normpath(word.removeprefix(WORKSPACE_PREFIX))}
    return {posixpath.normpath(posixpath.join(base, word)) for base in bases}


def _run_references(document: dict[Any, Any], tracked: frozenset[str]) -> dict[str, set[str]]:
    """Every tracked file a workflow's ``run:`` blocks name, and the steps that name it.

    A word is resolved from several bases, because ``../.github/scripts/x.sh`` run from
    ``infra/`` is the root's ``.github/`` and read from the root it is nothing. The bases are
    the step's working directory — its own, else its job's ``defaults``, else the workflow's —
    and every directory the block changes into with ``cd``. The ``env:`` values at every
    level are read with the block, since a path passed through a variable is still run.
    Full-line comments are dropped first, since no shell runs a line that starts with ``#``.

    Reading every word from every base can name a file the step never touches, and that
    fails toward a filter entry nobody needed rather than toward a gate that never ran.

    Only ``run:`` blocks and their ``env:`` are read. A file a script reaches on its own is
    not followed, and neither is a ``with:`` input such as an ``actions/github-script``
    ``script:``; a local action or reusable workflow is refused, because what it runs is
    invisible here. A path the workflow assembles rather than spells — from a matrix value, a
    variable the block sets, a glob, an expression in ``working-directory`` or a ``shell:``
    template — is not read either, so write the path out where the step uses it.

    Args:
      document: The parsed workflow.
      tracked: The files git tracks.

    Returns:
      Each referenced path mapped to the names of the steps that reference it.

    Raises:
      AssertionError: If a job or step uses a local action or reusable workflow.
    """
    workflow_directory = ((document.get("defaults") or {}).get("run") or {}).get("working-directory")
    found: dict[str, set[str]] = {}
    for job_name, job in document["jobs"].items():
        assert not str(job.get("uses", "")).startswith("./"), (
            f"job `{job_name}` calls a local reusable workflow; teach this derivation to follow it"
        )
        job_directory = ((job.get("defaults") or {}).get("run") or {}).get(
            "working-directory", workflow_directory
        )
        for step in job.get("steps", []):
            step_name = step.get("name", "<unnamed>")
            assert not str(step.get("uses", "")).startswith("./"), (
                f"step `{step_name}` uses a local action; teach this derivation to follow it"
            )
            if "run" not in step:
                continue
            directory = step.get("working-directory") or job_directory or "."
            code = "\n".join(
                line for line in step["run"].splitlines() if not line.lstrip().startswith("#")
            )
            bases = [directory, *(posixpath.join(directory, target) for target in CD_TARGET.findall(code))]
            variables = [str(value) for level in (document, job, step) for value in (level.get("env") or {}).values()]
            for word in PATH_WORD.findall("\n".join([code, *variables])):
                for candidate in _candidates(word, bases) & tracked:
                    found.setdefault(candidate, set()).add(step_name)
    return found


def test_every_path_filter_selects_the_files_its_workflow_runs() -> None:
    """A change to a file a filtered workflow runs must run that workflow.

    Derived from the ``run:`` blocks rather than listed: the infrastructure workflow's plan
    job ran its blocking Checkov gate, the gate's accept-list, the summary writer and the
    apply gate for as long as its filter named none of them, so a pull request editing the
    gate merged with the gate never executed. A list in this test would drift the same way.

    The workflow's own file is held to the same rule, which the infrastructure workflow's
    opening comment states first: an edit to the steps is an edit to what runs.

    Every filter is held to every reference, not only the event whose job runs it: each
    workflow's two lists are one list written twice, and reading ``if:`` expressions to split
    them per job would be parsing for no protection.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the derivation went vacuous, or any filter omits the workflow's own
        file or a file its steps run.
    """
    tracked = _tracked_files()
    derived: dict[str, tuple[dict[str, list[str]], dict[str, set[str]]]] = {}
    for path in _workflows():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        filters = _path_filters(document)
        if filters:
            references = _run_references(document, tracked)
            references.setdefault(path.relative_to(ROOT).as_posix(), set()).add("the workflow itself")
            derived[path.name] = (filters, references)

    assert derived.keys() >= PATH_FILTERED, (
        f"expected filters on {sorted(PATH_FILTERED)}, found them on {sorted(derived)} — "
        "the derivation stopped seeing them, so its agreement would be over nothing"
    )
    for workflow, reference in KNOWN_REFERENCES:
        assert reference in derived[workflow][1], (
            f"the derivation did not find {reference} in {workflow}, which runs it — the "
            "word match or the directory resolution is broken, so its report means nothing"
        )
    infra_filters = derived["deploy-infra.yml"][0]
    assert not any(_filter_selects(globs, UNSELECTED_PATH) for globs in infra_filters.values()), (
        f"the matcher selects {UNSELECTED_PATH}; it would report any file as covered"
    )

    missing = sorted(
        f"{workflow} `{event}` omits {reference} (named by: {', '.join(sorted(steps))})"
        for workflow, (filters, references) in derived.items()
        for event, globs in filters.items()
        for reference, steps in references.items()
        if not _filter_selects(globs, reference)
    )
    assert missing == [], "path filters omit files their workflow runs:\n  " + "\n  ".join(missing)


def test_the_image_deploys_carry_no_path_filter_on_their_push() -> None:
    """The two image deploys carry no ``paths:`` or ``paths-ignore:`` on their push.

    Adding the filter breaks nothing. The damage comes from a later push the filter skips,
    once it is already on ``main``, which is why the test above cannot see it: it reads only
    a filter that exists, and one naming its own file and every file its steps run passes it.

    The Lambda image is tagged with the commit, and two workflows firing on wider triggers
    wait for that tag: ``deploy-infra.yml`` polls the registry for it and fails after ten
    minutes, and ``deploy-lambdas.yml`` points every function at it. Filtering the build
    turns an infrastructure merge that touches no Lambda input into a red ``main``.

    The SPA deploy decides what to do from what the service is running: its commit, whether
    the family holds a newer revision, and whether the last rollout settled. Those reads are
    what point the service at a revision Terraform registered on its own and heal a deploy
    that failed, so a filter skips the pushes that would do either, and production keeps the
    old revision behind a green ``main``. The full reasoning for both is
    ``docs/decisions/infrastructure/``, "The SPA deploy decides from what is running".

    The push's branch is asserted first, since a workflow that no longer runs on a push to
    ``main`` has no filter there either. A job- or step-level ``if:`` that skips the build
    does the same damage and is not read: both workflows already gate their steps with
    ``if:``, and no mechanical line separates a gate that skips the build from those.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either workflow's push stops naming ``main`` among its branches, or
        gains a path filter.
    """
    pushes: dict[str, dict[str, Any]] = {}
    for name in sorted(UNFILTERED_ON_PUSH):
        document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        triggers = document.get(True, document.get("on"))
        push = triggers.get("push") if isinstance(triggers, dict) else None
        branches = (push.get("branches") or []) if isinstance(push, dict) else []
        assert "main" in ([branches] if isinstance(branches, str) else branches), (
            f"{name}'s push no longer names main among its branches, so finding no filter on "
            "it proves nothing"
        )
        pushes[name] = push

    filtered = sorted(
        f"{name} filters its push with `{key}`"
        for name, push in pushes.items()
        for key in ("paths", "paths-ignore")
        if key in push
    )
    assert filtered == [], (
        "an image deploy must run on every push to main, and a filter does its damage later, "
        "on main — this test's docstring says how, for each:\n  " + "\n  ".join(filtered)
    )


def _one_step_workflow(
    step: dict[str, Any], job: dict[str, Any] | None = None, **workflow: Any
) -> dict[Any, Any]:
    """A parsed workflow holding one job with one step, for the spelling corpus.

    Args:
      step: The step's keys, beside a fixed name.
      job: The job's keys other than its steps.
      **workflow: Top-level keys such as ``defaults`` or ``env``.

    Returns:
      The workflow, shaped as ``yaml.safe_load`` returns one.

    Raises:
      None.
    """
    return {**workflow, "jobs": {"only": {**(job or {}), "steps": [{"name": "the step", **step}]}}}


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param(
            _one_step_workflow({"working-directory": "infra", "run": "../.github/scripts/x.sh"}),
            {".github/scripts/x.sh"},
            id="relative-to-the-step-directory",
        ),
        pytest.param(
            _one_step_workflow(
                {"run": "../.github/scripts/x.sh"},
                job={"defaults": {"run": {"working-directory": "infra"}}},
            ),
            {".github/scripts/x.sh"},
            id="relative-to-the-job-default",
        ),
        pytest.param(
            _one_step_workflow(
                {"run": "../.github/scripts/x.sh"}, defaults={"run": {"working-directory": "infra"}}
            ),
            {".github/scripts/x.sh"},
            id="relative-to-the-workflow-default",
        ),
        pytest.param(
            _one_step_workflow(
                {"working-directory": "infra", "run": 'bash "${{ github.workspace }}/.github/scripts/x.sh"'}
            ),
            {".github/scripts/x.sh"},
            id="anchored-by-the-workspace-expression",
        ),
        pytest.param(
            _one_step_workflow(
                {"working-directory": "infra", "run": 'bash "$GITHUB_WORKSPACE/.github/scripts/x.sh"'}
            ),
            {".github/scripts/x.sh"},
            id="anchored-by-the-workspace-variable",
        ),
        pytest.param(
            _one_step_workflow({"run": "ROWS=$(cd infra && python3 ../lambdas/fleet.py --rows)"}),
            {"lambdas/fleet.py"},
            id="relative-to-a-cd-inside-the-block",
        ),
        pytest.param(
            _one_step_workflow({"env": {"SCRIPT": ".github/scripts/x.sh"}, "run": 'bash "$SCRIPT"'}),
            {".github/scripts/x.sh"},
            id="passed-through-the-step-env",
        ),
        pytest.param(
            _one_step_workflow({"run": 'bash "$SCRIPT"'}, env={"SCRIPT": ".github/scripts/x.sh"}),
            {".github/scripts/x.sh"},
            id="passed-through-the-workflow-env",
        ),
        pytest.param(
            _one_step_workflow({"run": "# calls .github/scripts/x.sh\necho done"}),
            set(),
            id="a-full-line-comment-names-nothing",
        ),
    ],
)
def test_the_derivation_reads_each_spelling_of_a_path(
    document: dict[Any, Any], expected: set[str]
) -> None:
    """Each way a step can name a file is found, and a comment naming one is not.

    The workflows use only some of these today, so a sweep over them cannot show that the
    rest are read; a spelling the derivation lost would let a filter omit that file in
    silence. The last case asserts silence, because a derivation that read comments would
    demand filter entries for files nothing runs.

    Args:
      document: A one-step workflow naming a file one way.
      expected: The tracked files the derivation must report.

    Returns:
      None.

    Raises:
      AssertionError: If the derivation misses the file, or reports one nothing runs.
    """
    assert set(_run_references(document, SPELLING_CORPUS_FILES)) == expected


def test_a_single_segment_star_matches_inside_one_segment_only() -> None:
    """The matcher's third shape, held both ways: a ``*`` that crossed ``/`` would report a file
    as covered by a filter GitHub never applies to it, which is the false green this file exists
    to catch."""
    assert _filter_selects(["infra/plane-*.tf"], "infra/plane-archive.tf")
    assert not _filter_selects(["infra/plane-*.tf"], "infra/plane-a/b.tf")
    assert not _filter_selects(["infra/plane-*.tf"], "infra/planes/archive/state-machine.tf")
    assert not _filter_selects(["infra/plane-*.tf"], "infra/plane-archive.tfvars")
