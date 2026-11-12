"""The control planes' deploy grants are one template and one map, and the map cannot drift.

Three things are held here. The map's keys are the root's calls into ``./modules/control-plane``,
in both directions, and its ``ceiling`` field is the calls that set one: a plane with no grant
fails its first apply, and a grant with no plane is a standing permission nobody uses. The
Python renderer every deploy-policy suite reads through renders what Terraform plans, byte for
byte, so those suites measure the document IAM receives. And the move from eight templates kept
every plane's policy name, description and statements.

Attributes:
  BASELINE_COMMIT: The last commit with the eight per-plane templates, which the equivalence
    proof renders the old documents from.
  VALUES: A value for every template variable, of the shape the real render produces.
  MODULE_SOURCE: The source a root call names when it builds a control plane.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import plane_grants
import pytest
import tf_blocks

ROOT = pathlib.Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"
BASE = INFRA / "modules" / "base"
BASELINE_COMMIT = "4bcb629e"
MODULE_SOURCE = '"./modules/control-plane"'
VALUES = {
    "account_id": "123456789012",
    "project_name": "dat",
    "aws_region": "us-east-1",
    "archive_bucket_name": "dat-prod-archive",
    "shared_space_bucket_arn": "arn:aws:s3:::dat-prod-shared-space",
}


def _root_calls() -> dict[str, str]:
    """Every root module call that builds a control plane, keyed by the plane's ``name``.

    Args:
      None.

    Returns:
      Each plane's name mapped to its call's body.

    Raises:
      AssertionError: When two calls name the same plane, or a call's name is not a literal.
    """
    calls: dict[str, str] = {}
    for path in sorted(INFRA.glob("*.tf")):
        for body in tf_blocks.module_calls(path.read_text(encoding="utf-8")).values():
            try:
                source = tf_blocks.argument(body[1:-1], "source")
            except ValueError:
                continue
            if source != MODULE_SOURCE:
                continue
            name = tf_blocks.argument(body[1:-1], "name")
            assert re.fullmatch(r'"[a-z0-9-]+"', name), f"{path.name} names a plane `{name}`"
            assert name.strip('"') not in calls, f"two root calls build the plane {name}"
            calls[name.strip('"')] = body
    return calls


def _git_show(path: str) -> str:
    """A file's text at the baseline commit.

    Args:
      path: The repo-relative path.

    Returns:
      The file's contents at ``BASELINE_COMMIT``.

    Raises:
      AssertionError: When git fails, including on a shallow checkout that lacks the commit — a
        missing baseline must fail rather than skip.
    """
    git = shutil.which("git") or "git"
    result = subprocess.run(  # noqa: S603
        [git, "show", f"{BASELINE_COMMIT}:{path}"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"git show {BASELINE_COMMIT}:{path} failed: {result.stderr.strip()}"
    return result.stdout


def _moves() -> dict[str, dict[str, str]]:
    """The ``moved`` blocks that carried the eight policies into the map, keyed by kind.

    Args:
      None.

    Returns:
      For each of the policy and the attachment, the old resource name mapped to the map key it
      moved to.

    Raises:
      None.
    """
    text = tf_blocks.strip_comments((INFRA / "moved.tf").read_text(encoding="utf-8"))
    moves: dict[str, dict[str, str]] = {"aws_iam_policy": {}, "aws_iam_role_policy_attachment": {}}
    for kind, old, slug in re.findall(
        r"moved\s*\{\s*from\s*=\s*module\.base\.(aws_iam_policy|aws_iam_role_policy_attachment)"
        r'\.(\w+)\s*to\s*=\s*module\.base\.\1\.control_plane\["([a-z0-9-]+)"\]\s*\}',
        text,
    ):
        moves[kind][old] = slug
    return moves


def _canonical(statements: list[dict]) -> set[str]:
    """Statements as comparable strings, with list order removed where IAM ignores it.

    Args:
      statements: A document's statement list.

    Returns:
      One sorted-key JSON string per statement.

    Raises:
      None.
    """
    result = set()
    for statement in statements:
        copy = dict(statement)
        for field in ("Action", "Resource"):
            if isinstance(copy.get(field), list):
                copy[field] = sorted(copy[field])
        result.add(json.dumps(copy, sort_keys=True))
    return result


def _baseline_block(old: str) -> str:
    """The baseline commit's ``aws_iam_policy`` block for one of the eight retired resources.

    Args:
      old: The retired resource's name.

    Returns:
      The block's body, braces excluded.

    Raises:
      KeyError: When the baseline declares no such resource.
    """
    blocks = tf_blocks.blocks(_git_show("infra/modules/base/iam.tf"), "aws_iam_policy")
    return blocks[old][1:-1]


# ── FR-002: the map cannot disagree with the planes ──────────────────────────


def test_the_map_holds_exactly_the_planes_the_root_builds() -> None:
    """A plane with no grant fails its first apply; a grant with no plane is a permission nobody uses."""
    built = set(_root_calls())
    granted = set(plane_grants.grants())

    assert len(built) >= 8, f"found {len(built)} control-plane calls — the sweep read the wrong tree"
    assert not built - granted, f"{sorted(built - granted)} are built but have no deploy grant in the map"
    assert not granted - built, f"{sorted(granted - built)} have a deploy grant but no root call builds them"


def test_a_plane_carries_the_timeout_rule_grant_exactly_when_its_call_sets_a_ceiling() -> None:
    """A ceiling creates the TIMED_OUT rule, and the rule's create is denied without the grant."""
    mismatched = []
    for name, body in _root_calls().items():
        try:
            tf_blocks.argument(body[1:-1], "ceiling")
            sets_ceiling = True
        except ValueError:
            sets_ceiling = False
        if plane_grants.grants()[name].ceiling != sets_ceiling:
            mismatched.append(f"{name}: call sets ceiling={sets_ceiling}, map says {not sets_ceiling}")

    assert not mismatched, mismatched


def test_every_extras_template_the_map_names_exists() -> None:
    """Otherwise the first sign is ``templatefile()``'s error at plan, which is right but late."""
    missing = sorted(
        f"{slug} names {grant.extras}"
        for slug, grant in plane_grants.grants().items()
        if grant.extras and not (plane_grants.POLICY_DIR / grant.extras).is_file()
    )

    assert not missing, f"extras templates the map names but the policy directory lacks: {missing}"


def test_both_resources_iterate_the_whole_map() -> None:
    """A filtered ``for_each`` drops a plane from IAM while every rendered-document suite sees all eight."""
    iam = plane_grants.IAM.read_text(encoding="utf-8")
    policy = tf_blocks.blocks(iam, "aws_iam_policy")["control_plane"][1:-1]
    attachment = tf_blocks.blocks(iam, "aws_iam_role_policy_attachment")["control_plane"][1:-1]
    expression = re.sub(r"\s+", " ", tf_blocks.argument(policy, "policy"))

    assert tf_blocks.argument(policy, "for_each") == "local.control_plane_grants"
    assert tf_blocks.argument(attachment, "for_each") == "local.control_plane_grants"
    assert tf_blocks.argument(attachment, "policy_arn") == "aws_iam_policy.control_plane[each.key].arn"
    assert tf_blocks.argument(policy, "name") == '"${var.project_name}-${each.value.name}"'
    assert tf_blocks.argument(policy, "description") == "each.value.description"
    assert f"/policies/{plane_grants.CORE.name}" in expression and "each.value.extras" in expression


def test_the_propagation_guard_re_fires_for_every_plane_grant() -> None:
    """A sleep with no trigger runs once, and ``replace_triggered_by`` alone misses a create on the tofu CI runs.

    So a plane added after the sleep exists would get no pause, which is the archive's first-apply
    failure again; keyed to every plane's policy body, a new, changed or removed grant replaces it.
    """
    sleep = tf_blocks.blocks(plane_grants.IAM.read_text(encoding="utf-8"), "time_sleep")["wait_for_plane_grants"][1:-1]

    assert re.sub(r"\s+", " ", tf_blocks.argument(sleep, "triggers")) == (
        "{ for plane, grant in aws_iam_policy.control_plane : plane => grant.policy }"
    )
    assert tf_blocks.argument(sleep, "depends_on") == "[aws_iam_role_policy_attachment.control_plane]"


# ── The renderer every deploy-policy suite reads through ─────────────────────


def _hcl_string(value: str) -> str:
    """A string as an HCL literal: JSON's escapes, plus HCL's two template sequences.

    Args:
      value: The string.

    Returns:
      The quoted literal.

    Raises:
      None.
    """
    return json.dumps(value).replace("${", "$${").replace("%{", "%%{")


def test_the_renderer_produces_what_terraform_plans() -> None:
    """Plans ``modules/base`` under mocked providers and compares each planned ``policy`` to the renderer's.

    The comparison is against the resource itself, not a re-typed expression, so a change to how
    ``aws_iam_policy.control_plane`` composes its document reddens this before any suite reading
    through the renderer can measure the wrong text.
    """
    tofu = shutil.which("tofu")
    assert tofu, "OpenTofu is not on PATH — this comparison cannot be skipped into passing"
    expected = {slug: plane_grants.encoded(doc) for slug, doc in plane_grants.documents(VALUES).items()}
    variables = {
        **VALUES,
        "github_repo": "o/r",
        "state_bucket": "dat-prod-tf-state",
        "state_lock_table": "dat-prod-tf-state-lock",
        "user_space_bucket_arn": "arn:aws:s3:::dat-prod-user-space",
        "portal_role_arn": "arn:aws:iam::123456789012:role/dat-portal-user-role",
        "lambda_artifacts_bucket_arn": "arn:aws:s3:::dat-lambda-artifacts",
        "athena_admin_bucket_arn": "arn:aws:s3:::dat-prod-athena-admin",
        "verification_trail_bucket_name": "dat-prod-archive-audit",
        "route53_zone_id": "Z0123456789ABCDEFGHIJ",
    }
    lines = [
        'mock_provider "aws" {',
        '  mock_resource "aws_iam_policy" { defaults = { arn = "arn:aws:iam::123456789012:policy/mock" } }',
        '  mock_resource "aws_iam_role" { defaults = { arn = "arn:aws:iam::123456789012:role/mock" } }',
        '  mock_resource "aws_iam_openid_connect_provider" {',
        '    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/mock" }',
        "  }",
        "}",
        'mock_provider "time" {}',
        'mock_provider "tls" {}',
        "",
        "variables {",
    ]
    lines += [f"  {name} = {_hcl_string(value)}" for name, value in variables.items()]
    lines += ["}", "", 'run "render" {', "  command = plan"]
    for slug, text in expected.items():
        lines += [
            "  assert {",
            f"    condition     = aws_iam_policy.control_plane[{_hcl_string(slug)}].policy == {_hcl_string(text)}",
            f"    error_message = {_hcl_string(f'{slug} plans a different document from the renderer')}",
            "  }",
        ]
    lines += [
        "  assert {",
        f"    condition     = length(aws_iam_policy.control_plane) == {len(expected)}",
        f"    error_message = {_hcl_string('the plan renders a different number of plane policies')}",
        "  }",
        "}",
    ]
    environment = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "TF_IN_AUTOMATION": "1"}
    with tempfile.TemporaryDirectory() as scratch:
        module = pathlib.Path(scratch) / "base"
        shutil.copytree(BASE, module, ignore=shutil.ignore_patterns(".terraform*"))
        (module / "tests").mkdir()
        (module / "tests" / "render.tftest.hcl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        setup = subprocess.run(  # noqa: S603
            [tofu, "init", "-backend=false", "-input=false"],
            cwd=module, env=environment, capture_output=True, text=True, check=False,
        )
        assert setup.returncode == 0, f"tofu init failed:\n{setup.stdout}\n{setup.stderr}"
        result = subprocess.run(  # noqa: S603
            [tofu, "test", "-no-color"], cwd=module, env=environment, capture_output=True, text=True, check=False
        )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "1 passed, 0 failed" in output, output


@pytest.mark.parametrize(
    ("template", "values", "reason"),
    [
        ("$${x}", {}, "escape"),
        ("%%{ if a ~}", {}, "escape"),
        ("%{ for a in b ~}x%{ endfor ~}", {}, "directives this renderer does not mirror"),
        ("%{ if a ~}x%{ endif ~}", {"a": "false"}, "not a bool"),
        ("%{ if a ~}%{ if b ~}x%{ endif ~}%{ endif ~}", {"a": True, "b": True}, "nests"),
        ("%{ if a ~}x", {"a": True}, "leaves an `if` open"),
        ("x%{ endif ~}", {}, "never opened"),
        ("[\n  %{~ if a ~}\n  1\n%{ endif }]", {"a": True}, "leading `%{~`"),
        ("${a.b}", {}, "not a plain variable"),
        ("${missing}", {}, "not a variable this template receives"),
    ],
    ids=["dollar-escape", "percent-escape", "for", "string-condition", "nested", "open", "unopened",
         "attribute", "missing", "left-strip"],
)
def test_the_renderer_refuses_what_it_cannot_mirror(template: str, values: dict, reason: str) -> None:
    """Each refusal by its reason, because a bare ``raises(ValueError)`` is satisfied by its neighbour."""
    with pytest.raises(ValueError, match=re.escape(reason)):
        plane_grants.render(template, values)


def test_the_renderer_refuses_to_interpolate_a_value_that_is_not_a_string() -> None:
    """Terraform would print ``true``; a renderer that did the same would hide a field read as the wrong kind."""
    with pytest.raises(TypeError, match="not a string"):
        plane_grants.render("${a}", {"a": True})


#: Every expected value below was produced by ``templatefile()`` on OpenTofu, not written by hand:
#: a hand-written expectation is the renderer's own belief restated, and the first version's agreed
#: with Terraform only because its fixtures had no indentation and one newline each.
@pytest.mark.parametrize(
    ("template", "values", "rendered"),
    [
        ("[\n%{ if a ~}\n  1,\n%{ endif ~}\n  2]", {"a": True}, "[\n  1,\n  2]"),
        ("[\n%{ if a ~}\n  1,\n%{ endif ~}\n  2]", {"a": False}, "[\n  2]"),
        ("[%{ if a ~}  x%{ endif }]", {"a": True}, "[x]"),
        ("[%{ if a ~} \t \n\n  x%{ endif }]", {"a": True}, "[\n  x]"),
        ("[%{ if a ~}\n\n\n  b%{ endif }]", {"a": True}, "[\n\n  b]"),
        ("[%{ if a ~} \r\n x%{ endif }]", {"a": True}, "[ x]"),
        ("[%{ if a ~}x\x1f%{ endif ~}\x1f y]", {"a": True}, "[x\x1f\x1f y]"),
        ("$%{ if a ~}{x}%{ endif ~}", {"a": True, "x": "X"}, "${x}"),
        ("${a}-${ a }", {"a": "x"}, "x-x"),
    ],
    ids=["true-branch", "false-branch", "strips-spaces", "strips-one-newline", "keeps-a-second-newline",
         "strips-crlf", "keeps-control-characters", "no-interpolation-across-a-directive", "interpolation"],
)
def test_the_renderer_renders_the_subset_it_mirrors(template: str, values: dict, rendered: str) -> None:
    """The positive half of the refusals: each refused shape is refused, and these render as Terraform does."""
    assert plane_grants.render(template, values) == rendered


def test_the_encoder_refuses_a_number_jsonencode_writes_differently() -> None:
    """``json.dumps`` writes ``1.0`` where ``jsonencode`` writes ``1``, which a budget would miscount."""
    with pytest.raises(TypeError, match="jsonencode writes differently"):
        plane_grants.encoded({"Statement": [{"Condition": {"NumericLessThan": {"k": 1.0}}}]})


def test_the_renderer_passes_extras_only_the_variables_terraform_passes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terraform hands an extras template ``control_plane_grant_vars`` alone, so ``${plane}`` there is an error."""
    monkeypatch.setattr(plane_grants, "POLICY_DIR", tmp_path)
    (tmp_path / "extras.json.tftpl").write_text('{"Statement": [{"Sid": "${plane}"}]}', encoding="utf-8")
    grant = plane_grants.Grant("archive", "n", "d", "Archive", True, True, "extras.json.tftpl")

    with pytest.raises(ValueError, match="`\\$\\{plane\\}` is not a variable this template receives"):
        plane_grants.document(grant, {**VALUES, "plane": "archive"})


# ── FR-001: the move kept every plane's policy ───────────────────────────────


def test_every_plane_keeps_its_policy_name_and_description() -> None:
    """Both are ForceNew, and a replaced deploy-role policy is the refresh deadlock in deploy-role-iam.md.

    Permanent, unlike the statement comparison below: neither may ever change in place.
    """
    moves = _moves()["aws_iam_policy"]
    grants = plane_grants.grants()
    changed = []
    for old, slug in moves.items():
        block = _baseline_block(old)
        if tf_blocks.argument(block, "name") != f'"${{var.project_name}}-{grants[slug].name}"':
            changed.append(f"{slug}: name was {tf_blocks.argument(block, 'name')}")
        if json.loads(tf_blocks.argument(block, "description")) != grants[slug].description:
            changed.append(f"{slug}: description changed")

    assert set(moves.values()) == set(grants), (
        f"the moved blocks cover {sorted(moves.values())}, the map holds {sorted(grants)}"
    )
    assert not changed, changed


def test_every_retired_attachment_moved_to_the_same_plane_as_its_policy() -> None:
    """A policy moved to one key and its attachment to another is a destroy and a create in the plan."""
    moves = _moves()

    assert moves["aws_iam_role_policy_attachment"] == moves["aws_iam_policy"]
    assert len(moves["aws_iam_policy"]) == len(plane_grants.grants())


def test_every_plane_renders_the_statements_the_eight_templates_did() -> None:
    """The proof that one template replaced eight without changing a grant.

    The baseline's documents are rendered from ``BASELINE_COMMIT`` and compared as sets of
    statements, which is how the provider compares a policy. THE PR THAT FIRST CHANGES A PLANE'S
    GRANT ON PURPOSE DELETES THIS TEST, because from then its own plan is the proof; the name and
    description test above stays.
    """
    moves = _moves()["aws_iam_policy"]
    rendered = plane_grants.documents(VALUES)
    differences = []
    for old, slug in moves.items():
        block = _baseline_block(old)
        path = re.search(r'templatefile\("\$\{path\.module\}/(policies/[^"]+)"', block)
        assert path, f"the baseline's {old} renders no template"
        baseline = json.loads(plane_grants.render(_git_show(f"infra/modules/base/{path.group(1)}"), VALUES))
        before, after = _canonical(baseline["Statement"]), _canonical(rendered[slug]["Statement"])
        if before != after or len(baseline["Statement"]) != len(rendered[slug]["Statement"]):
            differences.append(f"{slug}: only before {sorted(before - after)}; only after {sorted(after - before)}")

    assert set(moves.values()) == set(rendered), "the comparison does not cover every plane"
    assert not differences, differences
