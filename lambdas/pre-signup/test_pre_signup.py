"""Unit tests for the pre-signup trigger.

Runs under pytest or as a plain script (`python3 test_pre_signup.py`); the JS CI does
not run a Python interpreter.
"""

from contextlib import contextmanager

from pre_signup import handler


def _event(username="alice", email="alice@example.com"):
    attrs = {}
    if email is not None:
        attrs["email"] = email
    return {"userName": username, "request": {"userAttributes": attrs}}


@contextmanager
def _raises(match):
    """Assert the handler raises, and that the message says WHY.

    ``match`` is REQUIRED (SPEC-153 FR-007). The handler raises bare ``Exception`` on
    purpose — Cognito shows the user only the message — so the type carries no information
    and a match-less assertion accepts anything at all, ``ImportError`` included. That is
    not hypothetical for this file: SPEC-137 broke sign-up for nine days with a
    ``ModuleNotFoundError`` at cold start, in exactly this handler, and an assertion that
    only demanded "something was raised" would have gone on passing throughout.
    """
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - test helper
        assert match in str(exc), f"expected {match!r} in {str(exc)!r}"
        return
    raise AssertionError("expected handler to raise, but it did not")


def test_valid_username_and_email_passes():
    event = _event(username="alice", email="alice@example.com")
    assert handler(event, None) is event


def test_uppercase_username_rejected():
    # Lowercase only: Glue/Athena identifiers fold case.
    with _raises("Username must be"):
        handler(_event(username="Alice"), None)


def test_disposable_domain_rejected():
    with _raises("temporary email"):
        handler(_event(email="bot@mailinator.com"), None)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(fns)} passed")


