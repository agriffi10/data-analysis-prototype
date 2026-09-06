"""Every space-bucket statement naming a moving folder has a ``system_settings/`` twin that GRANTS THE SAME.

Three folders — ``athenaresults/``, ``archive/`` and ``shared_tables/`` — are moving under a real
``system_settings/`` prefix, and every Allow and Deny that names one is being duplicated onto the
new path before anything is written there. ``test_app_managed_template_population`` pins WHICH
files and anchors name a folder; it cannot see whether a sibling says the same thing as the
statement it twins. A Deny duplicated with two of its three actions denies less than its original
and reads, to a per-file population count, as present.

So this reads the statements: for every Resource naming a moving folder at the old anchor, a
statement in the same document must carry an equal ``Effect``, an equal ``Action`` SET, and the
twin Resource. A narrowed sibling, a flipped Effect and a missing sibling each redden it.

**Rendered and parsed, not grepped.** A placeholder can expand into something a text scan does not
recognise, and these documents must parse as JSON to be policies at all. The renderer substitutes
``$${`` first — Terraform's escape for a literal ``${``, which is how the principal-tag references
survive templating — and every substituted value KEEPS ITS VARIABLE NAME, because
``admin_bucket_arn`` is the marker that separates the bucket whose ``archive/`` moves from the one
whose does not.

**The admin-bucket marker is applied per RESOURCE, never per statement.** The population test can
apply it per LINE only because each resource sits on its own line; once this test parses the JSON
the lines are gone. ``modules/archive/policies/execution.json.tftpl``'s
``NeverDeletePortalManagedObjects`` holds ``${admin_bucket_arn}/*`` in the SAME array as four
space-bucket resources, so a per-statement marker would drop the two ``archive/*`` Denies this
whole arc exists to duplicate — and the per-file positive control would still pass on the
neighbouring statement.

**The counts below are the positive control, and they are hand-measured.** An empty collector
agrees with every possible sibling, and ``all([])`` is true. The unit counted is a
``(Sid, Resource)`` PAIR rather than a distinct resource string: the analytics template names the
same results path in two statements, and each of those needs its own sibling.

**The count is also the half the population test structurally cannot supply, so do not read it as
redundant.** That test compares a per-file SET of anchor/folder pairs, and most of these templates
name the same pair twice — once per bucket. Deleting ONE of the two leaves the set identical, so a
sibling removed from the user-space bucket while the shared one survives is invisible there.
Measured: two such deletions pass the population test and redden this one.

Attributes:
  INFRA: The Terraform tree the templates live in.
  MOVING: The three folders that move.
  ADMIN_BUCKET: The substring marking a Resource as the admin bucket's, whose ``archive/`` is a
    different fact and must NOT gain a sibling.
  SYSTEM_SETTINGS: The prefix the three are moving under.
  RENDERED: The templates that carry no ``%{ … }`` directive, with the number of old-anchor
    ``(Sid, Resource)`` pairs each holds. Measured by hand; the classifier re-measures on every run.
    The results-conversion plane joined this table on a rebase rather than when the file was
    written — it landed on the trunk mid-review naming all three moving folders — which is the case
    the reconciliation below exists for: without it, a plane arriving between two specs would be
    pinned by the population test and sibling-checked by nothing.
  TEXT_CHECKED: The one template that carries ``%{ for }`` loops and so is not JSON until Terraform
    renders it, with the Sids whose siblings are asserted as text.
"""

import json
import pathlib
import re

from cpcommon.app_managed import (
    ATHENA_RESULTS_FOLDER,
    RECEIPT_FOLDER,
    SHARED_TABLES_FOLDER,
)

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"

MOVING = (ATHENA_RESULTS_FOLDER, RECEIPT_FOLDER, SHARED_TABLES_FOLDER)

ADMIN_BUCKET = "admin_bucket_arn"

SYSTEM_SETTINGS = "system_settings"

RENDERED = {
    "modules/analytics/policies/portal-role-analytics.json.tftpl": 2,
    "modules/archive/policies/execution.json.tftpl": 6,
    "modules/data/policies/portal-role-permissions.json.tftpl": 1,
    "modules/data-quality/policies/execution.json.tftpl": 2,
    "modules/file-ops/policies/execution.json.tftpl": 8,
    "modules/results-conversion/policies/execution.json.tftpl": 7,
    "modules/table-builder/policies/execution.json.tftpl": 2,
    "modules/table-share/policies/execution.json.tftpl": 4,
}

TEXT_CHECKED = {
    "modules/shared-spaces/policies/portal-role-shared-space.json.tftpl": (
        "SharedResultsNoDelete",
        "SharedArchiveReceiptsAreNotUserWritable",
    )
}

_ESCAPE = "\x00ESCAPED_INTERPOLATION\x00"
_VARIABLE = re.compile(r"\$\{([a-z_][a-z0-9_]*)\}")
_OLD_ANCHOR = re.compile(rf"/({'|'.join(MOVING)})/")


def _render(text: str) -> str:
    """Substitutes a template's interpolations for values that keep their variable names.

    ``$${`` is Terraform's escape for a literal ``${`` and is protected first, so
    ``$${aws:PrincipalTag/username}`` survives as the reference a rendered policy carries rather
    than being read as a variable this function knows nothing about.

    Args:
      text: The template's source.

    Returns:
      The rendered document, ready to parse.

    Raises:
      None.
    """
    protected = text.replace("$${", _ESCAPE)
    substituted = _VARIABLE.sub(lambda match: f"RENDERED-{match.group(1)}", protected)
    return substituted.replace(_ESCAPE, "${")


def _twin(resource: str) -> str:
    """Returns the ``system_settings/`` sibling of a resource anchored at the old depth.

    Args:
      resource: A Resource naming a moving folder directly under its anchor.

    Returns:
      The same Resource with one ``system_settings/`` segment inserted before the folder.

    Raises:
      None.
    """
    return _OLD_ANCHOR.sub(lambda match: f"/{SYSTEM_SETTINGS}/{match.group(1)}/", resource, count=1)


def _resources(statement: dict) -> list[str]:
    """Returns one statement's Resource entries, whichever shape it was written in.

    Args:
      statement: One parsed policy statement.

    Returns:
      The Resource strings.

    Raises:
      None.
    """
    resource = statement.get("Resource", [])
    return [resource] if isinstance(resource, str) else list(resource)


def _actions(statement: dict) -> frozenset[str]:
    """Returns one statement's Action set, whichever shape it was written in.

    Args:
      statement: One parsed policy statement.

    Returns:
      The actions, as a set, so a reordered list is not a difference.

    Raises:
      None.
    """
    action = statement.get("Action", [])
    return frozenset([action] if isinstance(action, str) else action)


def _old_anchor_pairs(document: dict) -> list[tuple[str, str]]:
    """Collects every space-bucket ``(Sid, Resource)`` still anchored at the old depth.

    The admin-bucket marker is applied to the RESOURCE, not to the statement holding it — see the
    module docstring for the statement that mixes both buckets in one array.

    Args:
      document: The parsed policy.

    Returns:
      The pairs, in document order.

    Raises:
      None.
    """
    pairs = []
    for statement in document["Statement"]:
        for resource in _resources(statement):
            if ADMIN_BUCKET in resource or f"/{SYSTEM_SETTINGS}/" in resource:
                continue
            if _OLD_ANCHOR.search(resource):
                pairs.append((statement["Sid"], resource))
    return pairs


def test_the_parsed_templates_hold_exactly_the_measured_old_anchor_pairs() -> None:
    """The positive control. An empty collector agrees with every possible sibling.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a template no longer renders, no longer parses, or holds a different
        number of old-anchor pairs than was measured.
    """
    measured = {}
    for relative in RENDERED:
        path = INFRA / relative
        assert "%{" not in path.read_text(), (
            f"{relative} gained a Terraform directive, so it is no longer JSON after this "
            "renderer runs and belongs in TEXT_CHECKED"
        )
        document = json.loads(_render(path.read_text()))
        measured[relative] = len(_old_anchor_pairs(document))

    assert measured == RENDERED


def test_every_old_anchor_resource_has_a_sibling_granting_THE_SAME() -> None:
    """The claim a population count cannot make: the twin says what its original says.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any old-anchor Resource has no statement naming its twin with an equal
        Effect and an equal Action set.
    """
    unmatched = []
    for relative in RENDERED:
        document = json.loads(_render((INFRA / relative).read_text()))
        for sid, resource in _old_anchor_pairs(document):
            original = next(s for s in document["Statement"] if s["Sid"] == sid)
            wanted = _twin(resource)
            if not any(
                wanted in _resources(candidate)
                and candidate["Effect"] == original["Effect"]
                and _actions(candidate) == _actions(original)
                and candidate.get("Condition") == original.get("Condition")
                for candidate in document["Statement"]
            ):
                unmatched.append(f"{relative}: {sid} names {resource} with no equal-grant twin at {wanted}")

    assert unmatched == [], unmatched


def test_this_module_checks_EVERY_template_the_population_test_pins() -> None:
    """The two hand-written tables must cover the same files, or a template is pinned but unchecked.

    ``test_app_managed_template_population`` measures which templates name a moving folder in a
    space bucket; this module asserts those templates carry equal-granting twins. They agree today,
    and nothing made them agree — so a ninth template joining the population would redden that test
    with a ``joined`` entry, be added to ITS table, and never be sibling-checked here.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two populations differ.
    """
    from test_app_managed_template_population import SPACE_BUCKET_POPULATION

    assert set(RENDERED) | set(TEXT_CHECKED) == set(SPACE_BUCKET_POPULATION), {
        "pinned but not sibling-checked": sorted(set(SPACE_BUCKET_POPULATION) - set(RENDERED) - set(TEXT_CHECKED)),
        "sibling-checked but not pinned": sorted(set(RENDERED) | set(TEXT_CHECKED) - set(SPACE_BUCKET_POPULATION)),
    }


def test_only_the_three_MOVING_folders_appear_under_system_settings() -> None:
    """A second home is admitted for the three folders that move, and for nothing else.

    The spec puts a second home for a non-moving folder out of scope, and the sweeps beside this
    one cannot see the violation: the population test's pattern matches only the three moving
    names, and the equal-grant comparison only ever looks at resources that already name one. The
    Sid-keyed content assertions cover the three portal-role templates, so the gap is the five
    EXECUTION templates, where a ``system_settings/user_settings/*`` grant is read by nothing.

    Written over the whole tree rather than over the five, because the rule is about the prefix and
    not about a file: whatever ends up under ``system_settings/`` is one of these three.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the scan reaches nothing, or a path names anything else beneath the new
        prefix.
    """
    seen = 0
    offenders = []
    for path in sorted(INFRA.rglob("*.tftpl")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            for match in re.finditer(rf"/{SYSTEM_SETTINGS}/([^/\"\s]+)/", line):
                seen += 1
                if match.group(1) not in MOVING:
                    offenders.append(
                        f"{path.relative_to(INFRA).as_posix()}:{number}: {match.group(1)!r} is not one "
                        f"of the folders that move, so it gets no second home"
                    )

    assert seen >= 20, (
        f"only {seen} paths sit under {SYSTEM_SETTINGS}/, so this absence is about an empty scan "
        "rather than about the tree"
    )
    assert offenders == [], offenders


def test_the_admin_bucket_archive_prefix_gained_no_sibling() -> None:
    """Fact 3 of ``archive``: the control-plane scratch prefix does not move and must not be twinned.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the scan reaches nothing, or any Resource names the admin bucket beneath
        ``system_settings/``.
    """
    offenders = []
    marked = 0
    for path in sorted(INFRA.rglob("*.tftpl")):
        for line in path.read_text().splitlines():
            if ADMIN_BUCKET not in line:
                continue
            marked += 1
            if f"/{SYSTEM_SETTINGS}/" in line:
                offenders.append(f"{path.relative_to(INFRA).as_posix()}: {line.strip()}")

    assert marked >= 10, (
        f"only {marked} lines name the admin bucket, so the absence below is about an empty scan "
        "rather than about the tree — the glob or the marker has stopped matching"
    )
    assert offenders == [], offenders


def test_the_looping_template_carries_its_siblings_as_text() -> None:
    """The one looping template renders to JSON only through Terraform, so its siblings are read as text.

    Its ``%{ for }`` loops are what put it here. The assertion is the same one the parsed
    templates get — same Effect, same actions, the twin Resource — expressed over the statement's
    own text, which is how ``archiveWriteLock.test.ts`` already reads this file.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a named Sid, its sibling, or the sibling's agreement is missing.
    """
    for relative, sids in TEXT_CHECKED.items():
        body = (INFRA / relative).read_text()
        for sid in sids:
            original = _statement_text(body, sid)
            sibling = _statement_text(body, f"{sid}{'SystemSettings'}")

            assert _effect_of(original) == _effect_of(sibling), f"{sid}: the sibling's Effect differs"
            assert _action_lines(original) == _action_lines(sibling), f"{sid}: the sibling's actions differ"
            assert ('"Condition"' in original) == ('"Condition"' in sibling), (
                f"{sid}: one of the pair is conditioned and the other is not — a Deny that applies "
                "only under a condition refuses less than the one it twins"
            )

            resources = _resource_strings(original)
            assert resources, f"{sid} names no Resource, so this comparison is vacuous"
            assert _resource_strings(sibling) == [_twin(one) for one in resources], (
                f"{sid}: the sibling does not name the system_settings twin of every Resource"
            )


def _statement_text(body: str, sid: str) -> str:
    """Returns the text of one statement, cut at the next ``Sid``.

    Args:
      body: The template's source.
      sid: The statement's Sid, matched with its closing quote so a longer name cannot capture it.

    Returns:
      The statement's text.

    Raises:
      AssertionError: If no statement carries that Sid.
    """
    start = body.find(f'"Sid": "{sid}"')
    assert start > -1, f"no {sid} statement"
    following = body.find('"Sid"', start + 1)
    return body[start : None if following == -1 else following]


def _effect_of(statement: str) -> str:
    """Returns a statement's Effect, read from its text.

    Args:
      statement: The statement's text.

    Returns:
      ``Allow`` or ``Deny``.

    Raises:
      AssertionError: If the statement names no Effect.
    """
    found = re.search(r'"Effect":\s*"(\w+)"', statement)
    assert found, "the statement names no Effect"
    return found.group(1)


def _action_lines(statement: str) -> frozenset[str]:
    """Returns the actions a statement names, read from its text.

    Args:
      statement: The statement's text.

    Returns:
      The action strings.

    Raises:
      None.
    """
    block = re.search(r'"Action":\s*(\[[^\]]*\]|"[^"]*")', statement, re.DOTALL)
    return frozenset(re.findall(r'"([^"]+)"', block.group(1))) if block else frozenset()


def _resource_strings(statement: str) -> list[str]:
    """Returns the resources a statement names, read from its text.

    Args:
      statement: The statement's text.

    Returns:
      The Resource strings, in the order written.

    Raises:
      None.
    """
    block = re.search(r'"Resource":\s*(\[[^\]]*\]|"[^"]*")', statement, re.DOTALL)
    return re.findall(r'"([^"]+)"', block.group(1)) if block else []
