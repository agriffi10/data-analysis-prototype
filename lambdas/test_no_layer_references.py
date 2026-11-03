"""Nothing that deploys this fleet names a Lambda layer any more.

The layers are destroyed and their grants are gone, so a surviving reference is either a grant
that authorises nothing, a name that resolves to nothing, or an instruction to a reader that is
no longer true. This is the criterion SPEC-214 FR-002 deferred to the grants PR, and the reason
it could not land earlier: it asserts an absence that was false until the destroy had run.

**Scope is workflows, scripts and Terraform — deliberately NOT markdown.** The criterion names
those three, and prose legitimately describes history: `.github/workflows/README.md` explains why
the layer machinery went, which is a sentence about the past rather than a live reference.

**The bare layer suffix is NOT the pattern to match, and this is the trap.** Eight of the ten
layer names are also `lambdas/*-common/` SOURCE DIRECTORY names, which still exist and are still
referenced — `ci.yml` path-filters on `lambdas/control-plane-common/requirements.txt`. Matching
the suffix alone reports 26 false hits and would have to be weakened until it caught nothing.
What is forbidden is the layer FORM: an ARN, a layer API verb, a `*_layer_name` declaration, or a
name qualified by project and environment.

Attributes:
  FORBIDDEN: One compiled pattern per form, keyed by what a hit would mean.
  SCANNED_SUFFIXES: The file kinds the criterion covers.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

SCANNED_SUFFIXES = {".yml", ".yaml", ".sh", ".py", ".json", ".tf", ".tftpl"}

# `lambdas/` is in scope because the fleet's two real build-and-deploy scripts live there —
# `fleet.py`, which every deploy workflow derives the fleet from, and `docker/assemble.py`, which is
# the deleted layer table's direct successor and so the likeliest place for a reference to regrow.
# This file is excluded from its own scan: its fixtures are layer references on purpose.
SCANNED_TREES = (".github", "scripts", "infra", "lambdas")

# The retired machinery, captured verbatim. Every file carries a trailing `.txt` so no linter or
# scanner treats it as this repository's source: these scripts lived in `.github/scripts/`, which
# semgrep does not scan, and vendoring them under `lambdas/` as `.py`/`.sh` would newly subject
# retired code to a BLOCKING scanner for no benefit. Excluded from the live scan (it is a fixture,
# not a reference) and asserted against instead: every file here must produce a NON-COMMENT hit. Three
# rounds of review each found a real layer form the patterns could not see, and each was closed by
# widening one — being pinned against the machinery itself is what stops a fourth round, because
# these files cannot drift from what a layer reference looks like. See its PROVENANCE.md.
CORPUS = pathlib.Path(__file__).resolve().parent / "fixtures" / "retired-layer-artifacts"

_SUFFIXES = (
    "archive-common|control-plane-common|data-quality-common|data-quality-polars|"
    "file-ops-common|file-send-common|shared-space-common|table-builder-common|"
    "table-builder-polars|table-share-common"
)

FORBIDDEN = {
    "a layer ARN": re.compile(r"arn:[a-z0-9-]*:lambda:[^\"'\s]*:layer:"),
    # Service-qualified and open-ended, because `\b(?:Publish|Delete|Get|List)LayerVersions?\b`
    # misses five of the nine: `\b` does not fire between `Version` and `ByArn` or `Policy`, and
    # Add/Remove are not Publish/Delete/Get/List. Qualifying on `lambda:` is what keeps ECR's
    # `GetDownloadUrlForLayer` and `BatchCheckLayerAvailability` out.
    "a layer IAM action": re.compile(r"lambda:[A-Za-z]*Layer[A-Za-z]*"),
    # The CODE form. Without this the gate reads prose and IAM only: run over the destroy script
    # this criterion exists to forbid, the patterns above hit three lines and ALL THREE are inside
    # docstrings — its executable half matched nothing, so stripping the comments would have walked
    # a working layer sweep straight past.
    "a layer API call": re.compile(
        r"\b(?:publish|delete|get|list|add|remove)_layer_versions?\b"
        r"|\blist_layers\b"
        # Quoted or bare, `=` or `:` — a JSON key's closing quote sits between the name and the
        # colon, which is why `\bLayerName\s*[=:]` scored zero on the layer TABLE itself.
        r"|[\"']?layer_?name[\"']?\s*[:=]"
        r"|\b(?:publish|delete|get|list|add|remove)-layer-versions?\b"
        r"|--layer-name\b"
        r"|\blist-layers\b"
        # The ATTACH, which is what `deploy-lambda.sh` actually did and no pattern named.
        r"|\bLayers\s*=|--layers\b"
        # The bare operation name: `client.meta.method_to_api_mapping["DeleteLayerVersion"]` is
        # not an IAM action string, so the `lambda:`-qualified pattern cannot see it.
        r"|\b(?:Publish|Delete|Get|List|Add|Remove)Layer[A-Za-z]*\b|\bListLayers\b",
        re.IGNORECASE,
    ),
    "a layer-name declaration": re.compile(r"\w*layer_name\s*="),
    # The TERRAFORM form. Layers coming back would most naturally arrive as a resource and an
    # attribute, and neither spells a layer ARN, an IAM action or an API call — so without this
    # the gate watches every way of MANAGING a layer and none of the ways of DECLARING one.
    "a layer Terraform declaration": re.compile(
        r"aws_lambda_layer_version"
        r"|::(?:Lambda|Serverless)::LayerVersion"
        r"|^\s*layers\s*="
        r"|\w*layer_arns?\s*=",
        re.MULTILINE,
    ),
    "a qualified layer name": re.compile(
        r"(?:\$\{var\.project_name\}|\$\{project_name\}|dat)-"
        r"(?:\$\{var\.environment\}|\$\{environment\}|\*|[a-z]+)-(?:" + _SUFFIXES + r")"
    ),
}


def _scanned_files():
    """Every file the criterion covers.

    Returns:
      A sorted list of paths under `.github/`, `scripts/` and `infra/`.

    Raises:
      None.
    """
    here = pathlib.Path(__file__).resolve()
    files = []
    for tree in SCANNED_TREES:
        files += [
            p
            for p in (ROOT / tree).rglob("*")
            if p.is_file()
            and p.suffix in SCANNED_SUFFIXES
            and p.resolve() != here
            and CORPUS not in p.resolve().parents
            # Dot-dirs BELOW the tree, not the tree itself — `.github` starts with a dot, and
            # excluding it silently emptied a third of the scan. `infra/.terraform/` is the
            # target: present on a machine that has run `tofu init` and absent in CI, so the
            # gate's file set would otherwise differ between the two.
            and not any(part.startswith(".") for part in p.relative_to(ROOT / tree).parts)
        ]
    return sorted(files)


def _hits_in(text):
    """Every forbidden form in one file's text, as `(line number, label, line)`.

    Extracted so the final test's collector is the same code a positive control drives. Inlined,
    replacing its `append` with a no-op left every test in this module green.

    Args:
      text: The file's contents.

    Returns:
      One tuple per hit.

    Raises:
      None.
    """
    return [
        (number, label, line.strip()[:90])
        for number, line in enumerate(text.split("\n"), 1)
        for label, pattern in FORBIDDEN.items()
        if pattern.search(line)
    ]


def test_the_scan_actually_reads_the_tree():
    """A collector that collects nothing makes every absence assertion below vacuous.

    `all(...)` over an empty sequence is True, so a wrong glob or a renamed directory would turn
    this suite green while proving nothing at all.
    """
    files = _scanned_files()
    assert len(files) > 200, f"scanned only {len(files)} files — the walk is wrong"

    # Asserted against a literal, not against SCANNED_TREES — deriving the expectation from the
    # constant under guard means deleting a tree passes. Same for the suffixes: dropping `.tftpl`
    # silently removes ~94 files, and `.tftpl` is where every layer IAM grant lived.
    assert SCANNED_TREES == (".github", "scripts", "infra", "lambdas")
    assert {".yml", ".yaml", ".sh", ".py", ".json", ".tf", ".tftpl"} == SCANNED_SUFFIXES

    trees = {p.relative_to(ROOT).parts[0] for p in files}
    assert trees == set(SCANNED_TREES), f"missed a tree: {trees}"

    # Per-tree minima, because a total is dominated by `lambdas/` and would not move if
    # `.github/` (23 files) or `scripts/` (8) shrank to one.
    for tree, floor in ((".github", 15), ("scripts", 5), ("infra", 60), ("lambdas", 200)):
        n = sum(1 for f in files if f.relative_to(ROOT).parts[0] == tree)
        assert n >= floor, f"{tree}: {n} files, expected at least {floor}"
    assert sum(1 for f in files if f.suffix == ".tftpl") >= 20, "the .tftpl population vanished"

    # The collector itself, driven — not an inline expression that stands in for it.
    planted = _hits_in('  "layerName": "control-plane-common",')
    assert len(planted) == 1 and planted[0][1] == "a layer API call", planted

    scanned = {p.relative_to(ROOT).as_posix() for p in files}
    for real in ("lambdas/fleet.py", "lambdas/docker/assemble.py"):
        assert real in scanned, f"{real} is a live deploy script and must be scanned"

    # A token that IS present, so the reader proves it can find things as well as not find them.
    assert any(
        "aws_lambda_function" in p.read_text(encoding="utf-8")
        for p in files
        if p.suffix == ".tf"
    ), "found no `aws_lambda_function` in infra/ — the files are being read but not searched"


def test_every_forbidden_form_is_matched_by_its_pattern():
    """A positive control per pattern: an absence proved by a regex that matches nothing is not one.

    Keyed by label and asserted exhaustively, so adding a sixth pattern without a sample fails
    here rather than joining the set as decoration.
    """
    samples = {
        "a layer ARN": "arn:aws:lambda:us-east-1:*:layer:dat-prod-archive-common:1",
        "a layer IAM action": '"lambda:DeleteLayerVersion",',
        "a layer API call": "        page = client.list_layer_versions(LayerName=name)",
        "a layer-name declaration": '  arcommon_layer_name = "x"',
        "a layer Terraform declaration": '  layers = [aws_lambda_layer_version.x.arn]',
        "a qualified layer name": '"${project_name}-*-archive-common"',
    }
    assert set(samples) == set(FORBIDDEN), "every pattern needs a sample it must match"
    for label, pattern in FORBIDDEN.items():
        assert pattern.search(samples[label]), f"{label}: the pattern matches its own example"


def test_the_gate_sees_a_layer_sweep_written_as_CODE_not_only_as_prose():
    """The defect this test was rewritten for, pinned as a fixture rather than as reasoning.

    Run over the one-shot destroy script this arc deleted, the ARN/IAM/declaration patterns hit
    three lines and **all three are docstrings**. Its executable half — the boto3 calls that do
    the deleting — matched nothing, so a copy with its comments stripped would have passed a gate
    whose whole purpose is to forbid it.
    """
    executable_half = [
        "    page = client.list_layer_versions(**kwargs)",
        "    client.delete_layer_version(LayerName=name, VersionNumber=version)",
        '    aws lambda delete-layer-version --layer-name "$LAYER" --version-number 1',
        "    client.publish_layer_version(LayerName=name, Content={})",
        "    aws lambda list-layers --region us-east-1",
        '  resource "aws_lambda_layer_version" "cpcommon" {',
        "  layers = [aws_lambda_layer_version.cpcommon.arn]",
    ]
    for line in executable_half:
        assert any(p.search(line) for p in FORBIDDEN.values()), (
            f"no pattern sees this, so the gate would pass a working layer sweep: {line!r}"
        )


def test_every_lambda_layer_iam_action_is_caught_not_just_the_four_that_were_granted():
    """The grants held four of the nine actions; a regrown one need not.

    `\\b(?:Publish|Delete|Get|List)LayerVersions?\\b` misses five — `\\b` does not fire between
    `Version` and `ByArn` or `Policy`, and Add/Remove are in neither alternation.
    """
    for action in (
        "PublishLayerVersion", "DeleteLayerVersion", "GetLayerVersion", "ListLayerVersions",
        "GetLayerVersionByArn", "GetLayerVersionPolicy", "AddLayerVersionPermission",
        "RemoveLayerVersionPermission", "ListLayers",
    ):
        assert FORBIDDEN["a layer IAM action"].search(f'"lambda:{action}"'), action

    # ECR's own layer actions are a different service and must stay out.
    for other in ("ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"):
        assert not any(p.search(f'"{other}"') for p in FORBIDDEN.values()), other


def test_a_source_directory_name_is_not_treated_as_a_layer_reference():
    """The false-positive control, and the reason the bare suffix is not the pattern.

    Eight of the ten layer names are also directory names under `lambdas/`, and those directories
    still exist. A scan keyed on the suffix alone reddens on `ci.yml`'s path filters.
    """
    innocent = "            ^lambdas/control-plane-common/requirements\\.txt$"
    for label, pattern in FORBIDDEN.items():
        assert not pattern.search(innocent), f"{label} matches a source directory path"


def test_no_workflow_script_or_terraform_file_names_a_lambda_layer():
    """SPEC-214 FR-002's criterion, and the last thing the arc owed."""
    hits = [
        f"{path.relative_to(ROOT)}:{number} names {label}: {line}"
        for path in _scanned_files()
        for number, label, line in _hits_in(path.read_text(encoding="utf-8"))
    ]

    assert not hits, "the layers are destroyed; these still reference one:\n" + "\n".join(hits)


def _executable_lines(path):
    """A file's lines with comments and docstring bodies dropped.

    The distinction is the whole point of the corpus assertion: the first version of this gate
    found three hits in the destroy script and all three were docstrings, so a copy with its
    comments stripped would have passed the check written to forbid it.

    Args:
      path: The fixture file.

    Returns:
      `(line number, line)` for each line that is not a comment or inside a docstring.

    Raises:
      None.
    """
    lines = []
    in_doc = False
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        stripped = line.strip()
        if path.name.endswith(".py.txt"):
            fences = stripped.count('"""')
            if in_doc:
                if fences:
                    in_doc = False
                continue
            if stripped.startswith(('"""', 'r"""')) and fences < 2:
                in_doc = True
                continue
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((number, line))
    return lines


def test_every_retired_artefact_is_caught_on_a_line_that_is_not_a_comment():
    """The gate is pinned against the machinery it exists to forbid, not against invented samples.

    This is the structural answer to a defect that recurred three times: each review found a real
    layer form the patterns could not see, each was closed by widening one pattern, and the next
    round found another. Widening again would have been a fourth instance. A corpus of the actual
    deleted artefacts cannot drift from what a layer reference looks like, because it IS what one
    looked like.

    Two of these scored **zero** against the version of this gate that shipped before the corpus:
    `lambda-layers.json`, because a JSON key's closing quote sits between the name and the colon,
    and `deploy-lambda.sh`, because the attach is `--layers` and no pattern named it.
    """
    artefacts = sorted(CORPUS.glob("*.txt"))
    assert len(artefacts) == 4, f"the corpus is {len(artefacts)} files, expected 4: {artefacts}"

    for artefact in artefacts:
        executable = _executable_lines(artefact)
        assert executable, f"{artefact.name}: stripped to nothing, so the assertion is vacuous"

        caught = [
            (number, label)
            for number, line in executable
            for label, pattern in FORBIDDEN.items()
            if pattern.search(line)
        ]
        assert caught, (
            f"{artefact.name}: {len(executable)} executable lines and NOT ONE is seen by any "
            "pattern — this is the machinery the gate exists to forbid, so it could come back "
            "verbatim and the suite would stay green"
        )


def test_the_corpus_is_excluded_from_the_live_scan():
    """It is a fixture of layer references; scanning it would redden the gate permanently."""
    scanned = {p.resolve() for p in _scanned_files()}
    for artefact in CORPUS.iterdir():
        assert artefact.resolve() not in scanned, f"{artefact.name} is being scanned as live code"
