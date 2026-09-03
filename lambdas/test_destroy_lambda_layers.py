"""The one-shot layer sweep, driven over the shapes that would make it report a false clean.

Three things can go wrong with a destroy whose subject cannot be enumerated, and every one of them
ships green:

* **The name list is short.** Terraform declares eight of the ten layers, so a list derived from it
  leaves two behind and every remaining assertion passes over the eight it did reach.
* **The deletion is unauthorised.** A name outside the deploy role's grant wildcards fails at
  `DeleteLayerVersion`, mid-run, after some layers are already swept.
* **The listing is one page.** `ListLayerVersions` answers 50 at a time and seven of the ten layers
  carry more, so an unpaginated read deletes a third of the versions and then finds the layers it
  did fully empty to be empty.

Attributes:
  SWEEP: The script under test, imported by path because `.github/scripts` is not a package.
  POLICIES: The deploy-role policy templates that carry the layer grants.
"""

import importlib.util
import io
import json
import pathlib
import re
from fnmatch import fnmatch

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SWEEP_PATH = ROOT / ".github" / "scripts" / "destroy_lambda_layers.py"

_spec = importlib.util.spec_from_file_location("destroy_lambda_layers", SWEEP_PATH)
SWEEP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SWEEP)

POLICIES = sorted((ROOT / "infra" / "modules" / "base" / "policies").glob("github-actions-deploy*.json.tftpl"))

PROJECT = "dat"
ENVIRONMENT = "prod"
REGION = "us-east-1"
ACCOUNT = "696000197480"


class _NotFound(Exception):
    """The API's answer for a layer whose last version has been deleted."""


class _Exceptions:
    """The `client.exceptions` namespace a boto3 Lambda client exposes.

    Attributes:
      ResourceNotFoundException: The class the sweep catches.
    """

    ResourceNotFoundException = _NotFound


class FakeLambda:
    """A Lambda client that serves versions from a dict and records what was deleted.

    Args:
      layers: Layer name to its published version numbers.
      page_size: How many versions one `list_layer_versions` call returns, so pagination can be
        driven without building 142 versions.
      keep: Version numbers to leave behind on delete, so a failed sweep can be simulated.
      raises_when_absent: Whether an unknown layer raises instead of answering an empty page.
        **Defaults to False because that is what the live API does** — measured, not assumed.
        An earlier fake raised unconditionally, which is the shape the production code was being
        fixed away from, so it agreed with the bug and every test stayed green. The True variant
        exists only to drive the exception branch the code still catches.

    Attributes:
      deleted: Every `(layer, version)` pair `delete_layer_version` was called with, in order.
      list_calls: How many times `list_layer_versions` was called.
    """

    exceptions = _Exceptions

    def __init__(self, layers, page_size=50, keep=(), raises_when_absent=False):
        self._layers = {name: list(versions) for name, versions in layers.items()}
        self._page_size = page_size
        self._keep = set(keep)
        self.raises_when_absent = raises_when_absent
        self.deleted = []
        self.list_calls = 0

    def list_layer_versions(self, LayerName, MaxItems=50, Marker=None):
        self.list_calls += 1
        if LayerName not in self._layers:
            if self.raises_when_absent:
                raise _NotFound(LayerName)
            return {"LayerVersions": []}
        versions = self._layers[LayerName]
        start = int(Marker) if Marker else 0
        page = versions[start : start + self._page_size]
        result = {"LayerVersions": [{"Version": v} for v in page]}
        if start + self._page_size < len(versions):
            result["NextMarker"] = str(start + self._page_size)
        return result

    def delete_layer_version(self, LayerName, VersionNumber):
        self.deleted.append((LayerName, VersionNumber))
        if VersionNumber not in self._keep:
            self._layers[LayerName].remove(VersionNumber)
        if not self._layers[LayerName]:
            del self._layers[LayerName]


def _terraform_layer_suffixes():
    """Every layer name Terraform still declares, reduced to its suffix.

    The suffix comes from the literal tail of the VALUE, never from the local's own name:
    `shared-spaces/locals.tf` calls its local `common_layer_name`, so a name-derived suffix would
    be `common` and would match nothing.

    Returns:
      The set of suffixes.

    Raises:
      None.
    """
    pattern = re.compile(
        r"\w*layer_name\s*=\s*\"\$\{var\.project_name\}-\$\{var\.environment\}-([a-z0-9-]+)\""
    )
    suffixes = set()
    for locals_tf in (ROOT / "infra" / "modules").glob("*/locals.tf"):
        suffixes.update(pattern.findall(locals_tf.read_text(encoding="utf-8")))
    return suffixes


def _grants_for(action):
    """The `Resource` ARN patterns granting one Lambda action, rendered.

    Args:
      action: The IAM action, e.g. `lambda:DeleteLayerVersion`.

    Returns:
      A list of ARN patterns with the template's two variables substituted.

    Raises:
      None.
    """
    patterns = []
    for policy in POLICIES:
        rendered = (
            policy.read_text(encoding="utf-8")
            .replace("${project_name}", PROJECT)
            .replace("${aws_region}", REGION)
        )
        for statement in json.loads(rendered)["Statement"]:
            actions = statement["Action"]
            actions = [actions] if isinstance(actions, str) else actions
            if action not in actions:
                continue
            resource = statement["Resource"]
            patterns.extend([resource] if isinstance(resource, str) else resource)
    return patterns


def test_the_name_list_is_longer_than_terraform_and_says_by_exactly_which_two():
    """Terraform is not the source of this list, and the guard is what stops it becoming one.

    Every suffix Terraform declares must be swept, or a layer with a live local goes unswept. The
    reverse containment is the load-bearing half: the two Terraform has never named are asserted
    BY NAME, so replacing this list with a Terraform derivation reddens here instead of silently
    stranding 253 versions.
    """
    declared = _terraform_layer_suffixes()
    assert declared, "parsed no layer names out of infra/modules/*/locals.tf — the regex is stale"

    swept = set(SWEEP.LAYER_SUFFIXES)
    assert declared <= swept, f"Terraform declares layers the sweep does not delete: {declared - swept}"
    assert swept - declared == SWEEP.TERRAFORM_ORPHANS == {
        "control-plane-common",
        "table-builder-common",
    }, (
        "the sweep's extra names are no longer exactly the two Terraform never declared — either a "
        "local was added for one of them, or a name was added here that Terraform could have given"
    )


def test_both_calls_the_sweep_makes_are_covered_by_a_grant():
    """The sweep LISTS before it deletes, and the two authorize against different ARN shapes.

    `ListLayerVersions` authorizes against the UNVERSIONED layer ARN and `DeleteLayerVersion`
    against the versioned one — two separate `Resource` lines in each template. Checking only
    the delete would stay green while a run died at its very first list, before touching
    anything, which is the opposite of the failure it looks like it is guarding.
    """
    for action, arn_of in (
        ("lambda:ListLayerVersions", lambda n: f"arn:aws:lambda:{REGION}:{ACCOUNT}:layer:{n}"),
        ("lambda:DeleteLayerVersion", lambda n: f"arn:aws:lambda:{REGION}:{ACCOUNT}:layer:{n}:1"),
    ):
        patterns = _grants_for(action)
        assert patterns, f"no {action} grant found — the render or the glob is wrong"
        assert "*" not in patterns, (
            f"a bare `*` grant for {action} matches every ARN, making this test tautological"
        )

        for name in SWEEP.layer_names(PROJECT, ENVIRONMENT):
            arn = arn_of(name)
            assert any(fnmatch(arn, p) for p in patterns), f"{name} is granted no {action}"

        bogus = arn_of(f"{PROJECT}-{ENVIRONMENT}-not-a-layer")
        assert not any(fnmatch(bogus, p) for p in patterns), (
            f"the {action} grants match a layer that does not exist, so matching proves nothing"
        )


def test_a_layer_that_survives_its_deletions_fails_the_sweep():
    """The re-list is the only check that can fail, so it is the one worth breaking on purpose.

    `DeleteLayerVersion` answers 204 for a version that was never there, so a sweep that deleted
    nothing and a sweep that deleted everything are indistinguishable from their delete calls
    alone.
    """
    client = FakeLambda({"dat-prod-archive-common": [1, 2, 3]}, keep={3})

    with pytest.raises(RuntimeError, match=r"dat-prod-archive-common still lists versions \[3\]"):
        SWEEP.destroy(client, ("dat-prod-archive-common",), 3)

    assert client.deleted == [
        ("dat-prod-archive-common", 1),
        ("dat-prod-archive-common", 2),
        ("dat-prod-archive-common", 3),
    ], "it must attempt every version before judging the layer, not stop at the first survivor"


def test_a_run_that_dies_part_way_still_says_which_layers_it_swept(capsys):
    """The verdict prints only after every layer, so a partial sweep would otherwise leave no record.

    The deletion cannot be undone. An operator whose job died on layer six needs to know that five
    are gone, and the step log is the only place that can tell them before the verdict exists.
    """
    client = FakeLambda(
        {"dat-prod-archive-common": [1, 2], "dat-prod-file-ops-common": [1]}, keep={1}
    )

    with pytest.raises(RuntimeError):
        SWEEP.destroy(client, ("dat-prod-archive-common", "dat-prod-file-ops-common"), 3)

    progress = capsys.readouterr().err
    assert "swept dat-prod-archive-common: 2 deleted, 1 REMAINING" in progress, (
        f"the failing layer went unreported, so a re-run cannot know where it stopped: {progress!r}"
    )

    # And a layer that DID sweep says so, which is the half the operator acts on.
    ok = FakeLambda({"dat-prod-file-ops-common": [1, 2]})
    SWEEP.destroy(ok, ("dat-prod-file-ops-common",), 2)
    assert "swept dat-prod-file-ops-common: 2 deleted, GONE" in capsys.readouterr().err


def test_the_listing_spans_pages():
    """Seven of the ten layers hold more versions than one page returns.

    An unpaginated read deletes the first 50 of 142 and then re-lists — and the re-list is
    paginated the same wrong way, so it reads the next 50 as if they were the first and the layer
    reports as swept.
    """
    client = FakeLambda({"dat-prod-shared-space-common": list(range(1, 143))}, page_size=50)

    found = SWEEP.versions_of(client, "dat-prod-shared-space-common")

    assert found == list(range(1, 143)), f"read {len(found)} of 142 versions — pagination is broken"
    assert client.list_calls == 3, (
        "142 versions at 50 a page is three calls — the last page is short and sets no marker"
    )


def test_report_mode_deletes_nothing_through_the_entry_point():
    """Driven through `main`, because the wiring is where a mode input gets ignored.

    Asserting that `report()` issues no delete tests a function that only lists. What can actually
    break is `main` calling `destroy` regardless of `--mode`, or the workflow passing a mode the
    parser never reads.
    """
    client = FakeLambda({f"dat-prod-{s}": [1, 2] for s in SWEEP.LAYER_SUFFIXES})
    captured = io.StringIO()

    original_client, original_stdout = SWEEP._client, SWEEP.sys.stdout
    SWEEP._client = lambda region: client
    SWEEP.sys.stdout = captured
    try:
        code = SWEEP.main(
            ["--mode", "report", "--project", PROJECT, "--environment", ENVIRONMENT, "--region", REGION]
        )
    finally:
        SWEEP._client, SWEEP.sys.stdout = original_client, original_stdout

    assert code == 0
    assert client.deleted == [], "report mode deleted something"
    verdict = json.loads(captured.getvalue())
    assert verdict["mode"] == "report"
    assert verdict["versions"] == 20, "it must report what it found, not an empty sweep"
    assert verdict["absent"] == [], "no layer was missing, so none should be listed absent"


def test_an_empty_project_or_environment_is_refused():
    """Defends DIRECT invocation, and says so — the workflow cannot reach this.

    `${{ vars.TF_VAR_project_name || 'dat' }}` substitutes the default for an empty repository
    variable as well as an unset one, since GitHub expressions treat `''` as falsy. So the
    workflow never passes an empty string, and a guard justified on that path would be
    describing a failure it cannot see. What the workflow CAN produce is a plausible but wrong
    non-empty value, and the version-count gate is what catches that.
    """
    with pytest.raises(ValueError, match="non-empty"):
        SWEEP.layer_names("", ENVIRONMENT)
    with pytest.raises(ValueError, match="non-empty"):
        SWEEP.layer_names(PROJECT, "")


def test_a_wrong_project_cannot_sweep_because_the_count_disagrees():
    """The finding this guard exists for: deleting nothing must not look like deleting everything.

    An absent layer and a just-emptied one are the same API answer, so a wrong project or
    environment would sweep ten layers that do not exist, find no survivors and exit 0 — after
    which the grants come off and 923 real versions are stranded. The IAM grants do not contain
    this: they wildcard the environment segment, so `dat-dev-*` is authorised to delete.
    """
    client = FakeLambda({})  # every name resolves to a layer that does not exist

    with pytest.raises(RuntimeError, match=r"expected 923 versions .* and found 0"):
        SWEEP.destroy(client, SWEEP.layer_names(PROJECT, ENVIRONMENT), 923)

    assert client.deleted == [], "it must refuse before deleting, not after"


def test_an_absent_layer_is_not_reported_as_an_empty_one():
    """`None` and `[]` are different answers, and collapsing them is what hides a wrong name."""
    client = FakeLambda({"dat-prod-archive-common": [1]})

    assert SWEEP.versions_of(client, "dat-prod-archive-common") == [1]
    assert SWEEP.versions_of(client, "dat-prod-nope") is None, (
        "a layer that does not exist must be distinguishable from one that was just emptied"
    )
    assert SWEEP.total_versions({"a": None, "b": [1, 2]}) == 2


def test_apply_without_the_expected_count_is_refused_by_the_parser():
    """Supplying the count is impossible without having run the report, which is the whole point.

    Without this, report-before-apply is an instruction in a header comment, and the one mode
    that cannot be undone is the one relying on the operator having read it.
    """
    with pytest.raises(SystemExit):
        SWEEP.main(
            ["--mode", "apply", "--project", PROJECT, "--environment", ENVIRONMENT, "--region", REGION]
        )


def test_apply_mode_deletes_every_version_through_the_entry_point():
    """The mode-to-verb wiring, which is the mutation the report-mode test cannot see.

    Swapping `destroy` for `report` in `main`'s apply branch leaves a verdict of the same shape
    carrying the same version count, so the summary would report a completed sweep having
    deleted nothing — and the next PR then removes the grants, putting the versions out of
    reach for good. Only driving the entry point in apply mode distinguishes the two.
    """
    layers = {f"dat-prod-{s}": [1, 2] for s in SWEEP.LAYER_SUFFIXES}
    client = FakeLambda(layers)
    captured = io.StringIO()

    original_client, original_stdout = SWEEP._client, SWEEP.sys.stdout
    SWEEP._client = lambda region: client
    SWEEP.sys.stdout = captured
    try:
        code = SWEEP.main(
            [
                "--mode", "apply", "--project", PROJECT, "--environment", ENVIRONMENT,
                "--region", REGION, "--expect-versions", "20",
            ]
        )
    finally:
        SWEEP._client, SWEEP.sys.stdout = original_client, original_stdout

    assert code == 0
    assert len(client.deleted) == 20, (
        f"apply deleted {len(client.deleted)} of 20 versions — `main` is not wired to `destroy`"
    )
    assert sorted(client.deleted) == sorted((n, v) for n, vs in layers.items() for v in vs)
    verdict = json.loads(captured.getvalue())
    assert verdict["mode"] == "apply"
    assert verdict["versions"] == 20
    assert verdict["provedAbsent"] == sorted(layers), "every layer must be proved empty by name"


def test_an_empty_expected_count_reads_as_not_supplied():
    """The workflow passes `--expect-versions` unconditionally so it never expands an empty array.

    `"${arr[@]}"` on an empty array is an unbound-variable error under `set -u` on bash 3.2 and
    fine on 4.4+, so the array form works on today's runner and silently depends on its bash
    version — and the empty case is the DEFAULT `report` path, not an edge one.
    """
    assert SWEEP.optional_count("") is None
    assert SWEEP.optional_count("   ") is None
    assert SWEEP.optional_count("923") == 923

    with pytest.raises(SWEEP.argparse.ArgumentTypeError):
        SWEEP.optional_count("not-a-number")
    with pytest.raises(SWEEP.argparse.ArgumentTypeError):
        SWEEP.optional_count("-1")

    # And the refusal still fires when apply is given the empty value, which is what the
    # workflow sends if the operator dispatches apply without filling the field in.
    with pytest.raises(SystemExit):
        SWEEP.main(
            [
                "--mode", "apply", "--project", PROJECT, "--environment", ENVIRONMENT,
                "--region", REGION, "--expect-versions", "",
            ]
        )


def test_an_emptied_layer_reports_gone_through_the_empty_page_the_real_api_sends():
    """The post-delete re-list is the sweep's real production path, and it is an EMPTY PAGE.

    The live service answers a layer with no versions `{"LayerVersions": []}` and raises nothing.
    A `versions_of` that only returned `None` from the exception branch would hand this path a
    `[]`, the survivor check would fire on the FIRST layer, and an irreversible sweep would abort
    part-way with `still lists versions []`. The fake defaults to the empty page for exactly this
    reason — an earlier one raised, which agreed with the bug.
    """
    client = FakeLambda({"dat-prod-archive-common": [1, 2, 3]})

    deleted = SWEEP.destroy(client, ("dat-prod-archive-common",), 3)

    assert deleted == {"dat-prod-archive-common": [1, 2, 3]}
    assert SWEEP.versions_of(client, "dat-prod-archive-common") is None, (
        "an emptied layer must read as absent through the empty page, not as an empty list"
    )


def test_the_exception_branch_is_still_driven():
    """The API models `ResourceNotFoundException` on this call, so the catch stays and is tested."""
    client = FakeLambda({}, raises_when_absent=True)
    assert SWEEP.versions_of(client, "dat-prod-archive-common") is None


def test_main_feeds_the_operators_count_into_the_gate():
    """The gate compares the OPERATOR's number to the live total, not the live total to itself.

    Rebuilding the expectation inside `main` from a fresh report would compare a number to
    itself and pass on everything, while `destroy`'s own test still pinned the comparison.
    """
    client = FakeLambda({f"dat-prod-{s}": [1, 2] for s in SWEEP.LAYER_SUFFIXES})  # live total 20

    original = SWEEP._client
    SWEEP._client = lambda region: client
    try:
        with pytest.raises(RuntimeError, match=r"expected 999 versions .* and found 20"):
            SWEEP.main(
                [
                    "--mode", "apply", "--project", PROJECT, "--environment", ENVIRONMENT,
                    "--region", REGION, "--expect-versions", "999",
                ]
            )
    finally:
        SWEEP._client = original

    assert client.deleted == [], "it must refuse before deleting anything"


def test_a_zero_expectation_is_refused_because_zero_is_what_a_wrong_name_set_reports():
    """The gate's own blind spot: a wrong project reports 0, and 0 == 0 would pass.

    An operator copying the report's number, exactly as the workflow's input description tells
    them to, would hand `apply` a zero that matches the zero it finds — sweeping ten layers that
    do not exist and exiting 0 with `provedAbsent` naming all ten.
    """
    with pytest.raises(SystemExit):
        SWEEP.main(
            [
                "--mode", "apply", "--project", "wrongproj", "--environment", ENVIRONMENT,
                "--region", REGION, "--expect-versions", "0",
            ]
        )


def test_more_versions_than_expected_is_refused_too():
    """`!=`, not `<`. A name set resolving to MORE than the report saw is also a wrong name set."""
    client = FakeLambda({"dat-prod-archive-common": [1, 2, 3]})

    with pytest.raises(RuntimeError, match=r"expected 2 versions .* and found 3"):
        SWEEP.destroy(client, ("dat-prod-archive-common",), 2)

    assert client.deleted == []
