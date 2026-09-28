"""The archive name rule, run against the corpus the browser runs too.

The browser states the rule in TypeScript and cannot import this module, so the two are held
together by ``archive_name_corpus.json``: every raw input and what the rule must make of it. A
constant mirror would miss the likelier drift — a ``.trim()`` or a ``\\s`` that strips U+00A0
agrees with every constant here and disagrees with this module.
"""

import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arcommon import names
from cpcommon.errors import TerminalError

_CORPUS = json.loads(
    (pathlib.Path(__file__).resolve().parent / "archive_name_corpus.json").read_text()
)["cases"]


def _expanded(case):
    repeat = case.get("repeat", 1)
    normalized = case["normalized"]
    return case["raw"] * repeat, None if normalized is None else normalized * repeat


@pytest.mark.parametrize("case", _CORPUS, ids=lambda case: case["why"])
def test_the_rule_makes_of_each_raw_name_what_the_corpus_says(case):
    raw, expected = _expanded(case)

    outcome = None if names.refusal(raw) else names.normalize(raw)

    assert outcome == expected


def test_the_corpus_exercises_both_refusals_and_both_kinds_of_acceptance():
    """A corpus of only refusals, or only kept names, would pass against a rule that did one thing."""
    outcomes = [_expanded(case)[1] for case in _CORPUS]
    reasons = {names.refusal(_expanded(case)[0]) for case in _CORPUS}

    assert reasons == {None, "character", "length"}
    assert "" in outcomes
    assert any(outcome for outcome in outcomes)


def test_the_plane_takes_a_normalised_name_as_it_came():
    assert names.validated_name("Q1 reports") == "Q1 reports"


@pytest.mark.parametrize(
    "value",
    [7, "", " Q1", "Q1\u0007", "\U0001F600" * 101],
    ids=["not-a-string", "empty", "not-normalised", "bell", "101-astral"],
)
def test_the_plane_refuses_what_the_browser_would_never_send(value):
    """The browser normalises and omits an empty name, so anything else did not come from it."""
    with pytest.raises(TerminalError) as err:
        names.validated_name(value)

    assert err.value.reason == "invalid_name"
