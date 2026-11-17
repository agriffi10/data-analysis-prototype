"""Only the deploy role may create a role, rewrite a role's trust or pass a role to a service.

The deployed session key's policy names the web task role by ``aws:PrincipalArn``, which matches a
role by name. A principal that could create a role under that name while the web tier is off, rewrite
its trust, or hand it to something that runs as it, could read every session's refresh token. Among
the principals the IaC builds, only the deploy role may do any of the three, and this holds it: no
policy under ``infra/`` outside the deploy role's own templates names an action matching one of them,
wildcards and case variants included.

Two matchers, so an action that reaches a policy indirectly is not a blind spot. Every quoted
``iam:`` string anywhere in a scanned file is matched, wherever it sits, which catches a literal fed
to a template through ``jsonencode`` or a local. Every value of an action key (``Action``,
``NotAction``, ``actions``, ``not_actions``, in either JSON or HCL form) is matched too, which catches
``"*"`` and service-less wildcards. A ``NotAction`` grants what its list does not match. An action
value that is not a literal fails unless it is on ``INDIRECT_ACTIONS``, whose source is checked
instead. The effect is not read, so a ``Deny`` naming one of the three is flagged too: none exists,
and refusing it is the safe direction.

Attributes:
  INFRA: The IaC tree.
  TARGETS: The actions that let a principal obtain a role's identity, lower-cased as IAM compares them.
  DEPLOY_TEMPLATES: The deploy role's own policy templates, relative to ``INFRA``; they are expected
    to grant these actions, scoped to the roles the IaC builds.
  SCANNED: The suffixes read as possible policy sources.
  NOT_POLICY: The suffixes and names under ``infra/`` that hold no policy. A tracked file with any
    other suffix fails the test, so a policy written in a new form is not skipped silently.
  ACTION_KEY: An action key and its separator, in JSON (``"Action":``) or HCL (``Action =``,
    ``"Action" =``) form. Matched with case, as IAM reads a policy's element names; an ECR lifecycle
    rule's ``action`` and a state machine's ``action`` field are not policy elements.
  INDIRECT_ACTIONS: Each non-literal action value allowed, by file, with the file and the argument
    whose literals feed it.
"""

import fnmatch
import pathlib
import re
import shutil
import subprocess

import pytest
from tf_blocks import strip_comments

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
TARGETS = ("iam:createrole", "iam:updateassumerolepolicy", "iam:passrole")
DEPLOY_TEMPLATES = "modules/base/policies/github-actions-deploy*.json.tftpl"
SCANNED = {".tf", ".tftpl", ".json"}
NOT_POLICY = {".md", ".example", ".hcl", ".gitignore"}
ACTION_KEY = re.compile(
    r'(?<![\w"])"?(Action|NotAction|actions|not_actions)"?\s*[:=]\s*'
)
INDIRECT_ACTIONS = {
    "modules/control-plane/policies/sfn-permissions.json.tftpl": (
        "${child_execution_actions_json}",
        "modules/control-plane/iam.tf",
        "child_execution_actions_json",
    ),
}


def _matched(pattern: str) -> set[str]:
    """The targets one action pattern matches, compared as IAM compares them, without case.

    Args:
      pattern: An action as a policy writes it, wildcards included.

    Returns:
      The targets it grants.

    Raises:
      None.
    """
    return {
        target for target in TARGETS if fnmatch.fnmatchcase(target, pattern.lower())
    }


def _action_values(text: str) -> list[tuple[str, str, list[str] | None]]:
    """Reads every action key's value in a policy source, in JSON or HCL form.

    Args:
      text: The file's text, comments already blanked.

    Returns:
      For each key, its name, the value as written, and its strings, or None when the value is not
      a literal (a reference, an interpolation, or a list holding either).

    Raises:
      None.
    """
    found: list[tuple[str, str, list[str] | None]] = []
    for key in ACTION_KEY.finditer(text):
        rest = text[key.end() :]
        if rest.startswith("["):
            raw = rest[: rest.index("]") + 1]
            strings = re.findall(r'"([^"]*)"', raw)
            bare = re.sub(r'"[^"]*"|[\s,\[\]]', "", raw)
        elif rest.startswith('"'):
            raw = rest[: rest.index('"', 1) + 1]
            strings, bare = [raw[1:-1]], ""
        else:
            raw = rest.split("\n", 1)[0].strip().rstrip(",")
            strings, bare = [], raw
        literal = not bare and not any("${" in s for s in strings)
        found.append((key.group(1), raw, strings if literal else None))
    return found


def _offenders_in(relative: str, text: str) -> list[str]:
    """Names each way one file grants a principal a role's identity.

    Args:
      relative: The file's path under the scanned root, as ``/``-separated text.
      text: The file's text.

    Returns:
      One message per grant, each naming the file and the pattern.

    Raises:
      None.
    """
    if relative.endswith(".tf"):
        text = strip_comments(text)
    offenders = [
        f"{relative} names {quoted!r}"
        for quoted in re.findall(r'"(iam:[^"]*)"', text, re.IGNORECASE)
        if _matched(quoted)
    ]
    for key, raw, strings in _action_values(text):
        if strings is None:
            if INDIRECT_ACTIONS.get(relative, ("",))[0] != raw:
                offenders.append(
                    f"{relative} gives {key} a value this test cannot read: {raw}"
                )
            continue
        granted = set().union(*(_matched(s) for s in strings)) if strings else set()
        if key.lower().startswith("not"):
            granted = set(TARGETS) - granted
        offenders.extend(
            f"{relative} grants {target} through {key} {raw}"
            for target in sorted(granted)
        )
    return offenders


def _offenders(root: pathlib.Path, files: list[str]) -> list[str]:
    """Scans a tree's policy sources outside the deploy role's templates.

    Args:
      root: The scanned root, standing for ``infra/``.
      files: The files under it, relative and ``/``-separated.

    Returns:
      A message for each grant found, and for each file whose suffix is neither scanned nor known
      to hold no policy.

    Raises:
      None.
    """
    offenders: list[str] = []
    for relative in files:
        suffix = (
            pathlib.PurePosixPath(relative).suffix
            or pathlib.PurePosixPath(relative).name
        )
        if suffix in NOT_POLICY:
            continue
        if suffix not in SCANNED:
            offenders.append(
                f"{relative} has a suffix this scan does not know; scan it or list it in NOT_POLICY"
            )
        elif not fnmatch.fnmatchcase(relative, DEPLOY_TEMPLATES):
            offenders.extend(_offenders_in(relative, (root / relative).read_text()))
    return offenders


def _tracked() -> list[str]:
    """Lists the files git tracks under ``infra/``, relative to it.

    Returns:
      The paths, ``/``-separated.

    Raises:
      subprocess.CalledProcessError: If git cannot list them, which must fail rather than read as
        an empty tree.
    """
    git = shutil.which("git") or "git"
    listed = subprocess.run(  # noqa: S603
        [git, "ls-files", "-z", "--", "."],
        cwd=INFRA,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [path for path in listed.split("\0") if path]


def test_no_policy_outside_the_deploy_roles_templates_grants_a_roles_identity() -> None:
    """A second principal able to become the task role could read every session's refresh token."""
    files = _tracked()
    assert len(files) > 100, f"git listed {len(files)} files under infra/"
    assert _offenders(INFRA, files) == []


def test_the_matcher_reads_the_deploy_roles_own_grant_of_create_role() -> None:
    """A matcher that reads nothing would pass the sweep above on any tree."""
    templates = [
        path for path in _tracked() if fnmatch.fnmatchcase(path, DEPLOY_TEMPLATES)
    ]
    granting = [
        path
        for path in templates
        for _key, _raw, strings in _action_values((INFRA / path).read_text())
        if strings and any("iam:createrole" in _matched(s) for s in strings)
    ]
    assert granting, f"no deploy-role template grants iam:CreateRole among {templates}"


def test_each_indirect_action_is_fed_only_literals_that_grant_no_role() -> None:
    """An allowed interpolation would otherwise carry any action past the sweep."""
    for template, (_raw, source, argument) in INDIRECT_ACTIONS.items():
        assert (INFRA / template).is_file(), (
            f"{template} no longer exists; drop it from INDIRECT_ACTIONS"
        )
        text = strip_comments((INFRA / source).read_text())
        fed = re.search(
            rf"^\s*{argument}\s*=\s*\((.*?)^\s*\)", text, re.MULTILINE | re.DOTALL
        )
        assert fed, (
            f"{source} no longer builds {argument} as a parenthesised expression"
        )
        strings = re.findall(r'"([^"]*)"', fed.group(1))
        assert strings and all(
            s.startswith("states:") and not _matched(s) for s in strings
        ), strings


@pytest.mark.parametrize(
    "action", ["iam:CreateRole", "iam:Pass*", "iam:*", "IAM:passrole"]
)
@pytest.mark.parametrize(
    ("name", "body"),
    [
        (
            "policy.json.tftpl",
            '{"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "ACTION"], "Resource": "*"}]}',
        ),
        (
            "main.tf",
            'policy = jsonencode({\n  Statement = [{\n    Action = ["ACTION"]\n    Resource = "*"\n  }]\n})\n',
        ),
    ],
)
def test_a_planted_grant_fails_naming_the_file(
    tmp_path: pathlib.Path, action: str, name: str, body: str
) -> None:
    """Each of the three spellings, planted in a template and in an inline jsonencode, is found."""
    (tmp_path / "modules" / "x").mkdir(parents=True)
    (tmp_path / "modules" / "x" / name).write_text(body.replace("ACTION", action))
    offenders = _offenders(tmp_path, [f"modules/x/{name}"])
    assert offenders and all(o.startswith(f"modules/x/{name} ") for o in offenders)
    assert any(action in o for o in offenders), offenders


@pytest.mark.parametrize(
    ("relative", "body", "expected"),
    [
        (
            "modules/x/p.json.tftpl",
            '{"Action": "*", "Resource": "*"}',
            "grants iam:createrole through Action",
        ),
        (
            "modules/x/p.json.tftpl",
            '{"NotAction": ["s3:*"], "Resource": "*"}',
            "grants iam:passrole through NotAction",
        ),
        ("modules/x/main.tf", 'actions = ["iam:Create*"]\n', "names 'iam:Create*'"),
        (
            "modules/x/main.tf",
            'locals {\n  a = jsonencode(["iam:PassRole"])\n}\n',
            "names 'iam:PassRole'",
        ),
        (
            "modules/x/main.tf",
            "Action = local.actions\n",
            "a value this test cannot read: local.actions",
        ),
        ("modules/x/p.json.tpl", "{}", "has a suffix this scan does not know"),
        (
            "modules/base/policies/other.json.tftpl",
            '{"Action": ["iam:PassRole"]}',
            "names 'iam:PassRole'",
        ),
    ],
)
def test_a_grant_in_another_form_is_refused_for_its_reason(
    tmp_path: pathlib.Path, relative: str, body: str, expected: str
) -> None:
    """A wildcard, a NotAction, a data-source list, a fed literal, a reference and a new suffix."""
    (tmp_path / relative).parent.mkdir(parents=True)
    (tmp_path / relative).write_text(body)
    offenders = _offenders(tmp_path, [relative])
    assert any(expected in o for o in offenders), offenders


@pytest.mark.parametrize(
    ("relative", "body"),
    [
        ("modules/x/p.json.tftpl", '{"Action": ["s3:GetObject"], "Resource": "*"}'),
        (
            "modules/x/p.json.tftpl",
            '{"Principal": {"AWS": "arn:aws:iam::111122223333:root"}, "Action": "kms:*"}',
        ),
        ("modules/x/p.json.tftpl", '{"Action": ["iam:GetRole", "iam:ListRoles"]}'),
        (
            "modules/x/main.tf",
            '# Action = ["iam:*"]\nalarm_actions = [aws_sns_topic.x.arn]\n',
        ),
        ("modules/x/ecr.tf", 'rules = [{ action = { type = "expire" } }]\n'),
        (
            "modules/base/policies/github-actions-deploy-x.json.tftpl",
            '{"Action": ["iam:CreateRole", "iam:*"]}',
        ),
        ("modules/x/README.md", 'The deploy role holds "iam:PassRole".'),
    ],
)
def test_what_grants_no_role_passes(
    tmp_path: pathlib.Path, relative: str, body: str
) -> None:
    """A resource wildcard, a principal ARN, other IAM reads, a comment, the deploy role's own
    template and prose are not grants."""
    (tmp_path / relative).parent.mkdir(parents=True)
    (tmp_path / relative).write_text(body)
    assert _offenders(tmp_path, [relative]) == []
