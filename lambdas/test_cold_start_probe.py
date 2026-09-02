"""The cold-start probe's population is derived from the deploy role's own grants.

`Deploy Lambdas` invokes a sample of the fleet after pointing it, to prove the deployed artefact
starts. What that sample IS cannot be a hand-written list: the fleet Terraform declares holds all
86 names and no notion of "one verb per plane plus each standalone", so the sample would be an
artefact nobody could check, drifting the moment a plane or a standalone was added.

**It is derived from the IAM instead, and the asymmetry is the whole reason.** A probe naming a
function the deploy role cannot invoke fails loudly the first time it runs — `AccessDenied`. A
**grant with no probe is invisible**: a grant is added, the probe keeps naming the same functions,
and the two drift with nothing red. So the comparison is set equality in both directions, against
the `lambda:InvokeFunction` statements in the deploy role's policies.

**What it therefore does NOT cover, said plainly rather than left to be discovered:** a plane that
ships with no invoke grant at all. Its functions are then in neither set, the equality holds
trivially, and the probe simply does not reach them. That is a coverage gap and not a wrong green —
71 of the 86 are unprobed by design — and it is recorded with the others in `docs/testing/owed.md`.
Chasing it here would mean a hand-written map of plane to function prefix, which is the artefact
this derivation exists to avoid.

The population is often described as "one function per plane plus each standalone". That is nearly
true and worth stating exactly: six planes are represented by their `validate-authorize` verb, and
**shared-spaces is represented by `shared-space-backfill-ever-active`** — an operator entry point
rather than a verb, chosen because it defaults to a read-only mode and so is safe to invoke.

The policies are **parsed, not grepped**. They are JSON carrying `${…}` placeholders, and the
placeholders contain braces — which is how the first version of this sweep silently missed
`github-actions-deploy.json.tftpl`, the one file whose name has no suffix, and reported 13 grants
where there are 15. Both halves of that are guarded below.

Attributes:
  POLICIES: The deploy role's policy templates.
  PROBES: The committed probe population and its exemptions.
  Nothing else here needs naming: the universe a grant pattern resolves against is the fleet
  Terraform declares, read through `fleet.function_names`.
"""

import fnmatch
import json
import pathlib
import re

import fleet
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICIES = ROOT / "infra" / "modules" / "base" / "policies"
PROBES = ROOT / ".github" / "lambda-probes.json"


def _deployed() -> list[str]:
    """Every deployed function name.

    Args:
      None.

    Returns:
      The names from the deploy table.

    Raises:
      None.
    """
    return fleet.function_names(ROOT)


def _granted() -> set[str]:
    """The functions the deploy role may invoke, resolved to deployed names.

    Args:
      None.

    Returns:
      The resolved population.

    Raises:
      AssertionError: If a policy will not parse, if a pattern matches everything, or if one
        matches no deployed function — each of which would quietly shrink or inflate this set.
    """
    deployed = _deployed()
    resolved: set[str] = set()
    statements = 0

    # `github-actions-deploy*`, not `github-actions-deploy-*`. The base policy has no suffix, and
    # it is where both Cognito triggers' grants live — a hyphen here drops two functions from the
    # population and every assertion below still passes.
    for path in sorted(POLICIES.glob("github-actions-deploy*.json.tftpl")):
        rendered = re.sub(r"\$\{[a-z_]+\}", "PLACEHOLDER", path.read_text(encoding="utf-8"))
        try:
            document = json.loads(rendered)
        except ValueError as exc:  # pragma: no cover - a malformed policy fails the apply first
            raise AssertionError(f"{path.name} does not parse as a policy: {exc}") from exc

        for statement in document["Statement"]:
            actions = statement["Action"]
            actions = [actions] if isinstance(actions, str) else actions
            if "lambda:InvokeFunction" not in actions:
                continue
            targets = statement["Resource"]
            for target in [targets] if isinstance(targets, str) else targets:
                statements += 1
                pattern = (
                    target.split(":function:")[1]
                    .replace("PLACEHOLDER-*-", "")
                    .replace("PLACEHOLDER", "*")
                )
                assert pattern.strip("*"), (
                    f"{path.name}: {target} resolves to a pattern that matches every function, so "
                    "the derived population below would be the whole fleet and say nothing"
                )
                matched = {name for name in deployed if fnmatch.fnmatch(name, pattern)}
                assert matched, (
                    f"{path.name}: {target} matches no deployed function. Either the grant is dead "
                    "or the deploy table lost a row"
                )
                resolved |= matched

    # NO COUNT FLOOR HERE, deliberately. One was tried at eight, and it could not catch the very
    # bug this module's docstring describes: the suffixed-only glob yields 13 statements where
    # there are 15, and 13 clears any floor worth writing. What catches it is the set equality
    # below — the two Cognito triggers become probed-but-not-granted — and a hard-coded number
    # beside a real check only hides which one is doing the work.
    return resolved


def test_the_probe_covers_exactly_what_the_deploy_role_may_invoke() -> None:
    """Both directions, because only one of them fails on its own.

    A probe without a grant is an `AccessDenied` the first time it runs. A grant without a probe is
    silent — which is what an eighth plane, or a second standalone, would produce.
    """
    document = json.loads(PROBES.read_text(encoding="utf-8"))
    probed = set(document["probe"])
    exempt = set(document["exempt"])

    assert probed, "the probe list is empty, so the gate that reads it proves nothing"
    assert probed & exempt == set(), (
        f"{sorted(probed & exempt)} is both probed and exempt; one of the two is a leftover"
    )
    assert probed | exempt == _granted(), (
        f"probed-or-exempt is {sorted(probed | exempt)} but the deploy role may invoke "
        f"{sorted(_granted())}. A grant with no probe is the invisible half of this drift"
    )


def test_every_exemption_carries_a_reason_and_is_still_granted() -> None:
    """An exemption is a decision, so it is written down where the decision is made.

    It keeps its grant deliberately: the function is one an operator may still need to invoke by
    hand, and dropping the grant would make that a separate change nobody remembers to ask for.
    """
    document = json.loads(PROBES.read_text(encoding="utf-8"))
    granted = _granted()

    for name, reason in document["exempt"].items():
        assert name in granted, f"{name} is exempted from a probe it was never granted"
        assert len(reason) > 120, (
            f"{name}'s exemption reason is {len(reason)} characters. FR-006 asks for the reason, "
            "not the fact — this is the one place it is recorded"
        )


def test_every_probed_function_is_one_the_fleet_actually_deploys() -> None:
    """The other end of the chain: a probe name the deploy table does not carry is a typo that
    would fail at invoke time, long after the deploy it was meant to guard."""
    document = json.loads(PROBES.read_text(encoding="utf-8"))
    unknown = sorted(set(document["probe"]) - set(_deployed()))

    assert not unknown, f"{unknown} are probed but named by no row in the deploy table"


@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("*", "matches every function"),
        ("no-such-function-*", "matches no deployed function"),
    ],
)
def test_the_grant_sweep_refuses_a_pattern_that_would_make_it_vacuous(
    pattern: str, expected: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control. `[].every(...)` is true and a collector that collected nothing agrees
    with any absence, so the sweep's own refusals are exercised rather than assumed.

    **Matched by MESSAGE.** A bare `pytest.raises(AssertionError)` is satisfied by whichever
    assertion in `_granted` happens to fire first, so deleting the one under test would leave this
    green — the neighbouring branch catching the fixture.
    """
    policy = tmp_path / "github-actions-deploy-fake.json.tftpl"
    policy.write_text(
        json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "FakeProbeInvoke",
                        "Effect": "Allow",
                        "Action": "lambda:InvokeFunction",
                        "Resource": (
                            "arn:aws:lambda:${aws_region}:*:function:${project_name}-*-" + pattern
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(f"{__name__}.POLICIES", tmp_path)

    with pytest.raises(AssertionError, match=expected):
        _granted()
