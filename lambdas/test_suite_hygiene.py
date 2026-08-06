"""Repo-wide properties of the Lambda SUITES themselves (SPEC-153 FR-007).

A test that asserts "something raised" passes against an ``ImportError`` at cold start, and
this fleet has already paid for that once: SPEC-137 broke sign-up for nine days with a
``ModuleNotFoundError``, in a handler whose own test only demanded that *an* exception
appear. So the assertion has to name what it expects.

Sits beside ``test_deploy_matrix.py`` — the other file here that reads the repo as data
rather than exercising a behaviour.
"""

import pathlib
import re

LAMBDAS = pathlib.Path(__file__).resolve().parent

#: Every suite file except this one — its own regex source would otherwise match.
_TEST_FILES = [p for p in sorted(LAMBDAS.rglob("test_*.py")) if p.name != pathlib.Path(__file__).name]

#: ``pytest.raises(Exception)`` with nothing else inside the parentheses. A ``match=``, a
#: narrower type, or a tuple of types all fall outside it.
_BARE_RAISES = re.compile(r"pytest\.raises\(\s*Exception\s*\)")


def test_the_suite_sweep_found_the_files():
    """Guards the guard: a glob that matches nothing makes the check below vacuous."""
    assert len(_TEST_FILES) >= 50, f"only found {len(_TEST_FILES)} test files under {LAMBDAS}"


def test_no_exception_assertion_accepts_anything_at_all():
    """Every ``pytest.raises(Exception)`` must say WHICH exception it means.

    ``match=`` is the normal answer. Where the assertion is deliberately about the type
    being *wrong* — "whatever propagates, it must not be a TransientError" — the ``match=``
    still pins that the propagated error is the one under test rather than an incidental
    failure on the way to it.
    """
    offenders = [
        f"{path.relative_to(LAMBDAS)}:{number}"
        for path in _TEST_FILES
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _BARE_RAISES.search(line)
    ]

    assert not offenders, (
        "pytest.raises(Exception) with no match= accepts an ImportError at cold start, "
        f"which is how SPEC-137 stayed invisible for nine days: {offenders}"
    )
