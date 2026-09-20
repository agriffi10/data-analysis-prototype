"""The results-conversion enqueue route: a shape-only door in front of one authority.

The route refuses what is not the contract's shape and nothing else. Every length and content
cap lives in the plane's validate-authorize, so the assertions here are about the door being
exactly as thin as the other ten: the closed format vocabulary, unknown and missing keys at
either depth, and the absence of any byte cap of the route's own.
"""

import ast
import json
import pathlib

import pytest
import router
from apicommon import contract
from cpcommon import results
from routes import athena

_ROUTE = next(r for r in contract.ENQUEUE_ROUTES if r.id == "resultsConversion.enqueue")
_BODY = {
    "requestId": "00000000-0000-4000-8000-0000000000c0",
    "queryExecutionId": "11111111-2222-4333-8444-555555555555",
    "format": "parquet",
    "destination": {"space": {"kind": "personal", "name": "alice"}, "prefix": "reports/", "filename": "q1.parquet"},
    "onConflict": "refuse",
    "submittedAt": "2026-09-05T12:00:00.000Z",
}


def _code(body) -> str | None:
    return contract.validate_request(_ROUTE, body)


def test_a_well_formed_body_passes_the_door():
    assert _code(_BODY) is None


def test_csv_is_accepted_and_a_format_with_no_writer_is_still_refused():
    """`csv` used to be refused here, because the plane had no CSV writer and the synchronous
    copy produced the object instead. It has one now — reached when the file is to carry a
    subset of the result's columns, which a copy cannot produce — so the vocabulary is four, and
    the positive control beside it is a name that still has no writer."""
    assert _code({**_BODY, "format": "csv"}) is None
    assert _code({**_BODY, "format": "tsv"}) is not None


@pytest.mark.parametrize(
    "chosen",
    [[2, 0], [0], list(range(1500))],
    ids=["reordered-subset", "one-column", "at-the-bound"],
)
def test_a_chosen_column_list_is_a_body_this_route_accepts(chosen):
    assert _code({**_BODY, "columnIndexes": chosen}) is None


def test_a_chosen_column_list_over_the_bound_is_refused_before_a_message_is_built():
    """The length is the API's, not the plane's: the list rides every link of the chain, and a
    verb bound would be applied only after the Pipe had already started an execution with it."""
    from apicommon import bounds

    over = {**_BODY, "columnIndexes": list(range(1501))}
    breached = bounds.over_bound(_ROUTE, over)

    assert breached is not None and breached.path == "columnIndexes"
    assert bounds.over_bound(_ROUTE, {**_BODY, "columnIndexes": list(range(1500))}) is None


@pytest.mark.parametrize(
    "body",
    [
        {**_BODY, "extra": 1},
        {**_BODY, "destination": {**_BODY["destination"], "extra": 1}},
        {k: v for k, v in _BODY.items() if k != "submittedAt"},
        {**_BODY, "destination": {k: v for k, v in _BODY["destination"].items() if k != "filename"}},
        {**_BODY, "onConflict": "ask"},
        {**_BODY, "destination": {**_BODY["destination"], "prefix": 7}},
    ],
    ids=["unknown-top", "unknown-nested", "missing-top", "missing-nested", "bad-conflict", "wrong-type"],
)
def test_an_unknown_missing_or_mistyped_key_is_refused_at_either_depth(body):
    assert _code(body) is not None


def test_the_route_declares_no_body_cap_of_its_own():
    """The only byte cap on the send path is the queue's, applied by the shared sender; a second
    one here would silently invalidate the argument that the timeout door needs no DescribeExecution."""
    source = (pathlib.Path(__file__).parent / "routes" / "enqueue.py").read_text(encoding="utf-8")
    numbers = [n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool)]
    assert numbers == [], f"routes/enqueue.py carries numeric constants: {numbers}"
    handler = router.HANDLERS["resultsConversion.enqueue"]
    assert handler.__name__ == "resultsConversion_enqueue"
    # `traceparent` is stamped on every enqueue route and chooses no behaviour; what this
    # assertion is about is that this route stamps nothing that does.
    assert _ROUTE.queue == "results-conversion" and _ROUTE.stamped == frozenset({"traceparent"}) and _ROUTE.plane == "api"


def test_the_apis_output_location_is_the_shared_user_results_prefix(monkeypatch):
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")
    assert athena.output_location("alice") == results.user_results_prefix("dat-prod-user-space", "alice")
    assert athena.output_location("alice") == "s3://dat-prod-user-space/alice/system_settings/athenaresults/"


def test_the_generated_typescript_carries_the_closed_format_vocabulary():
    """The union is matched to its TERMINATOR, and that is the whole point of the semicolon.

    This read `"format: 'parquet' | 'json' | 'xlsx'" in generated` while the vocabulary was three,
    and appending a fourth member left that substring intact — so the assertion went vacuous
    rather than red on exactly the change it exists to notice. Anchored on the `;` that ends the
    property, a member added or removed cannot leave it passing.
    """
    generated = (pathlib.Path(__file__).resolve().parents[2] / "apps" / "portal" / "src" / "types" / "apiContract.generated.ts").read_text(encoding="utf-8")
    assert "format: 'parquet' | 'json' | 'xlsx' | 'csv';" in generated
    assert "columnIndexes?: number[]" in generated
    assert "'resultsConversion.enqueue': {method: 'POST', path: '/v1/enqueue/results-conversion'" in generated
    assert json.dumps(_BODY)  # the body above is what the browser will send, serialisable as-is
