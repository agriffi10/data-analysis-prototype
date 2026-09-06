"""Pins the IAM templates that name one of the three moving app-managed folders, per file.

Three folders — ``athenaresults/``, ``archive/`` and ``shared_tables/`` — are about to move under
``system_settings/``. Every Allow and Deny that names one must gain a sibling naming the new path
before the move, and missing one is the arc's silent failure: a Deny that stops matching denies
nobody and reports nothing. So the population is pinned here, spelled out as literals, and a file
joining or leaving it — or gaining a second folder — reddens this test rather than the cutover.

**Measured, not derived.** The expected tables below were written by hand from a grep on the day
this test was added; the classifier re-measures on every run and the two are compared. A test whose
expectation came from the same rule it checks would pass on a deletion. (The hand measurement is
not dated: the classifier re-measures on every run, so the tables are as current as the last green.)

**``archive`` is three facts, and the classifier separates one of them.** ``${admin_bucket_arn}/archive/*``
is the archive plane's control-plane scratch prefix, in the admin bucket — it does NOT move, and it
is pinned in its own table so a sibling is never added to it by mistake. Everything else naming a
folder segment is in a space bucket and moves.

Attributes:
  INFRA: The Terraform tree the templates live in.
  SEGMENT: A path-shaped occurrence of a moving folder — the ANCHORING segment (opening the string
    or following a slash), a slash, an optional ``system_settings/``, the name, a trailing slash.
    The anchor is captured and pinned WITH the folder and with whichever prefix separates them, so
    a personal sibling measures as ``username}/system_settings/archive`` and a shared one as
    ``*/system_settings/archive`` — a sibling written under the wrong anchor is a different pair
    from the right one, and a path replaced IN PLACE reddens the table rather than contributing the
    same pair twice. The optional group is what keeps the two homes distinguishable: without it the
    new path would measure as ``system_settings/archive``, reporting the prefix as the anchor and
    agreeing with a sibling hung under any space at all. A bucket or module name containing the
    word, and an ASL comment, do not match.
  ADMIN_BUCKET: The substring that marks a Resource as the admin bucket's, which is fact 3.
  SPACE_BUCKET_POPULATION: Measured by hand when this test was written. Per template, the
    ``<preceding segment>/<folder>`` pairs it names in a space bucket. ``*`` is the shared-space
    wildcard; ``username}`` and ``${principal_tag_key}}`` are the tails of the two personal-space
    principal-tag anchors, captured up to the slash.
  ADMIN_BUCKET_POPULATION: Measured by hand when this test was written. Per template, the
    admin-bucket ``archive/`` scratch prefix — the one that must NOT move.
"""

import pathlib
import re

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"

SEGMENT = re.compile(r"(?<=[\"/])([^/\"\s]+)/((?:system_settings/)?)(athenaresults|archive|shared_tables)/")

ADMIN_BUCKET = "admin_bucket_arn"

SPACE_BUCKET_POPULATION = {
    "modules/analytics/policies/portal-role-analytics.json.tftpl": frozenset(
        {"${principal_tag_key}}/athenaresults", "${principal_tag_key}}/system_settings/athenaresults"}
    ),
    "modules/archive/policies/execution.json.tftpl": frozenset(
        {"*/athenaresults", "*/archive", "*/system_settings/athenaresults", "*/system_settings/archive"}
    ),
    "modules/data-quality/policies/execution.json.tftpl": frozenset(
        {"*/athenaresults", "*/system_settings/athenaresults"}
    ),
    "modules/data/policies/portal-role-permissions.json.tftpl": frozenset(
        {"username}/archive", "username}/system_settings/archive"}
    ),
    "modules/file-ops/policies/execution.json.tftpl": frozenset(
        {"*/athenaresults", "*/archive", "*/system_settings/athenaresults", "*/system_settings/archive"}
    ),
    "modules/results-conversion/policies/execution.json.tftpl": frozenset(
        {
            "*/athenaresults",
            "*/archive",
            "*/shared_tables",
            "*/system_settings/athenaresults",
            "*/system_settings/archive",
            "*/system_settings/shared_tables",
        }
    ),
    "modules/shared-spaces/policies/portal-role-shared-space.json.tftpl": frozenset(
        {"*/athenaresults", "*/archive", "*/system_settings/athenaresults", "*/system_settings/archive"}
    ),
    "modules/table-builder/policies/execution.json.tftpl": frozenset(
        {"*/athenaresults", "*/system_settings/athenaresults"}
    ),
    "modules/table-share/policies/execution.json.tftpl": frozenset(
        {
            "*/athenaresults",
            "*/shared_tables",
            "*/system_settings/athenaresults",
            "*/system_settings/shared_tables",
        }
    ),
}

ADMIN_BUCKET_POPULATION = {
    "modules/archive/policies/execution.json.tftpl": frozenset({"${admin_bucket_arn}/archive"}),
    "modules/archive/policies/sfn-permissions.json.tftpl": frozenset({"${admin_bucket_arn}/archive"}),
}


def _measure() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]], int]:
    """Classifies every path-shaped folder segment in every template by the bucket it addresses.

    Args:
      None.

    Returns:
      The space-bucket population, the admin-bucket population, and how many templates were read.

    Raises:
      None.
    """
    space: dict[str, set[str]] = {}
    admin: dict[str, set[str]] = {}
    templates = sorted(INFRA.rglob("*.tftpl"))
    for path in templates:
        rel = path.relative_to(INFRA).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            for match in SEGMENT.finditer(line):
                bucket = admin if ADMIN_BUCKET in line else space
                bucket.setdefault(rel, set()).add(f"{match.group(1)}/{match.group(2)}{match.group(3)}")
    return (
        {k: frozenset(v) for k, v in space.items()},
        {k: frozenset(v) for k, v in admin.items()},
        len(templates),
    )


def test_the_classifier_read_the_tree_and_saw_every_folder():
    """Guards the guard: an empty scan, or a folder no template names, makes the tables vacuous."""
    space, _, count = _measure()
    assert count >= 40, f"only {count} templates under {INFRA}; the glob has stopped matching"
    named = frozenset(pair.rsplit("/", 1)[1] for pair in frozenset().union(*space.values()))
    assert named == frozenset({"athenaresults", "archive", "shared_tables"}), named


def test_the_space_bucket_templates_naming_a_moving_folder_are_exactly_these():
    """Per file AND per folder: a template gaining a second folder must redden this, not just appear."""
    space, _, _ = _measure()
    assert space == SPACE_BUCKET_POPULATION, {
        "joined": sorted(set(space) - set(SPACE_BUCKET_POPULATION)),
        "left": sorted(set(SPACE_BUCKET_POPULATION) - set(space)),
        "changed": sorted(k for k in set(space) & set(SPACE_BUCKET_POPULATION) if space[k] != SPACE_BUCKET_POPULATION[k]),
    }


def test_the_admin_bucket_archive_prefix_is_exactly_these_and_must_not_move():
    """Fact 3 of ``archive``. A sibling statement added here would be a grant onto a prefix nobody writes."""
    _, admin, _ = _measure()
    assert admin == ADMIN_BUCKET_POPULATION
