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

import importlib.util
import pathlib
import posixpath
import re
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

    Only the two shapes these workflows use are understood — a literal path, and a
    ``dir/**`` prefix. Every entry is checked before any is matched, and anything else
    RAISES rather than being approximated: a matcher that quietly mishandles a shape reports
    a file as covered for the wrong reason, which is the failure this exists to catch.

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
        assert not re.search(r"[*?\[\]!+]", literal), (
            f"`{glob}` is a filter shape this test does not implement; teach the matcher "
            "rather than letting it approximate"
        )
    return any(
        path == glob or (glob.endswith("/**") and path.startswith(glob.removesuffix("**")))
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
