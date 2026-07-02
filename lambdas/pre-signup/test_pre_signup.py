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
def _raises(match=None):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - test helper
        if match is not None:
            assert match in str(exc), f"expected {match!r} in {str(exc)!r}"
        return
    raise AssertionError("expected handler to raise, but it did not")


def test_valid_username_and_email_passes():
    event = _event(username="alice", email="alice@example.com")
    assert handler(event, None) is event


def test_valid_username_with_digits_and_underscore_passes():
    # Catalog-safe identifier: starts with a letter, then letters/digits/underscore.
    event = _event(username="alice_42", email="alice@example.com")
    assert handler(event, None) is event


def test_too_short_username_rejected():
    with _raises("Username must be"):
        handler(_event(username="ab"), None)  # 2 chars, minimum is 3


def test_uppercase_username_rejected():
    # Lowercase only: Glue/Athena identifiers fold case.
    with _raises("Username must be"):
        handler(_event(username="Alice"), None)


def test_leading_digit_username_rejected():
    # Must start with a letter (catalog-safe identifier rule).
    with _raises("Username must be"):
        handler(_event(username="1alice"), None)


def test_email_style_username_rejected():
    # `@ . -` are not catalog-safe and are rejected.
    with _raises("Username must be"):
        handler(_event(username="alice@corp"), None)
    with _raises("Username must be"):
        handler(_event(username="alice.smith"), None)
    with _raises("Username must be"):
        handler(_event(username="alice-smith"), None)


def test_disposable_domain_rejected():
    with _raises("temporary email"):
        handler(_event(email="bot@mailinator.com"), None)


def test_uppercase_disposable_domain_normalised():
    with _raises("temporary email"):
        handler(_event(email="Bot@MAILINATOR.COM"), None)


def test_empty_email_passes_defensively():
    # No email attribute at all — the domain check is skipped, not an error.
    event = _event(username="alice", email=None)
    assert handler(event, None) is event


def test_username_check_runs_before_email_check():
    # A bad username from a disposable domain is caught by the username rule first.
    with _raises("Username must be"):
        handler(_event(username="x/y", email="x@mailinator.com"), None)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(fns)} passed")
