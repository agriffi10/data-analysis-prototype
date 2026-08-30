"""The trusted-actor reader: what it accepts, what it refuses, and what it may not become.

Every refusal is asserted by its REASON CODE, never by "something raised". The neighbouring
refusal in this module returns the same exception class, so a test that only caught the class
would pass against a reader that confused a malformed envelope with an unaccepted principal kind.

The JWT fixture is the load-bearing one. During the cutover every message carries both a verified
username in the block and a raw 900-character token in the flat field beside it, and both are
non-empty strings — so a presence check cannot tell them apart and a reader that fell back to the
field would pass every well-formed fixture here.
"""

import ast
import pathlib

import pytest
from cpcommon import actor as cpactor
from cpcommon.errors import TerminalError
from cpcommon.messages import UNSUPPORTED_ASSURANCE
from token_shapes import JWT_SHAPED

JWT = JWT_SHAPED


class DomainError(Exception):
    """Stands in for a plane whose Catch keys on its own exception type."""


def block(**overrides):
    """Builds an identity block, the API's shape by default.

    Args:
      **overrides: Fields to replace or, with a None value for a key, to drop.

    Returns:
      A message body carrying the block.

    Raises:
      None.
    """
    identity = {"actor": "alice", "delegated_by": None, "assurance": "interactive"}
    for key, value in overrides.items():
        if value is _DROP:
            identity.pop(key, None)
        else:
            identity[key] = value
    return {"identity": identity, "requestId": "req-1"}


_DROP = object()


def test_a_well_formed_block_yields_the_verified_actor():
    """The happy path, and the only shape the API mints today."""
    who = cpactor.trusted_actor(block())

    assert who.username == "alice"
    assert who.delegated_by is None
    assert who.assurance == cpactor.ASSURANCE_INTERACTIVE


@pytest.mark.parametrize(
    ("req", "case"),
    [
        ({"requestId": "r"}, "block absent"),
        ({"identity": None}, "block null"),
        ({"identity": "alice"}, "block is a string"),
        ({"identity": ["alice"]}, "block is a list"),
        ("not-a-mapping", "body is not a mapping"),
    ],
)
def test_a_missing_or_malformed_block_is_unauthorized_and_names_the_block(req, case):
    """The refusal names the missing block, not anything about a token.

    A pre-cutover message is the case this really covers, and the honest thing to tell an operator
    reading the record is that no identity arrived — not that a token failed to verify, which
    would send them looking at a verifier that no longer exists.
    """
    with pytest.raises(TerminalError) as raised:
        cpactor.trusted_actor(req)

    assert raised.value.reason == "unauthorized", case
    assert "identity block" in raised.value.detail, case


@pytest.mark.parametrize(
    ("value", "case"),
    [
        (_DROP, "actor absent"),
        (None, "actor null"),
        (123, "actor is an int"),
        ({"username": "alice"}, "actor is a mapping"),
        ("", "actor empty"),
        ("   ", "actor whitespace"),
        ("Alice", "actor uppercase"),
        ("al", "actor too short"),
        ("a" * 64, "actor too long"),
        ("alice-smith", "actor carries a hyphen"),
        ("1alice", "actor starts with a digit"),
        ("alice\n", "actor with a trailing newline"),
        (JWT, "actor is a raw JWT"),
    ],
)
def test_an_actor_that_is_not_a_catalog_safe_username_is_refused(value, case):
    """The shape rule is the guard, not a comment beside a presence check.

    ``actor is a raw JWT`` is why the rule is a regex: nothing the API mints can produce one, and
    a reader that only checked presence would accept it and go on to build an S3 prefix, a Glue
    database name and a notification recipient out of it.
    """
    with pytest.raises(TerminalError) as raised:
        cpactor.trusted_actor(block(actor=value))

    assert raised.value.reason == "unauthorized", case


@pytest.mark.parametrize("field", ["username", "user", "owner", "sub", "actor"])
def test_no_other_field_is_consulted_when_the_block_is_missing(field):
    """Asserted per name, because the failure mode is a well-meaning fallback added later.

    ``actor`` is the dangerous one and it is in the list twice over: it is the flat field four
    planes carry the raw token in during the cutover, so a fallback resolves to a JWT rather than
    to nothing, and nothing about the result looks wrong until a prefix is built from it.
    """
    with pytest.raises(TerminalError) as raised:
        cpactor.trusted_actor({field: "mallory", "requestId": "r"})

    assert raised.value.reason == "unauthorized"
    assert "mallory" not in raised.value.detail


def test_the_flat_actor_is_ignored_whether_or_not_the_block_is_present():
    """Asserted both ways, so a fallback cannot hide behind an incomplete fixture.

    With the block present the flat field must lose; with it absent the flat field must not win by
    default. One assertion alone passes against a reader that prefers the block but still falls
    back, which is exactly the reader that breaks on the first stale message.
    """
    both = {**block(), "actor": JWT}
    assert cpactor.trusted_actor(both).username == "alice"

    with pytest.raises(TerminalError) as raised:
        cpactor.trusted_actor({"actor": JWT, "requestId": "r"})
    assert raised.value.reason == "unauthorized"


@pytest.mark.parametrize(
    ("overrides", "case"),
    [
        ({"assurance": "delegated"}, "the reserved but unminted value"),
        ({"assurance": ""}, "empty"),
        ({"assurance": None}, "null"),
        ({"assurance": 1}, "not a string"),
        ({"assurance": _DROP}, "absent"),
        ({"assurance": "INTERACTIVE"}, "wrong case"),
    ],
)
def test_an_assurance_outside_the_accepted_set_is_refused_distinctly(overrides, case):
    """Distinct from ``unauthorized``: the plane understood the request and declined to act.

    ``absent`` is in the list deliberately. A missing assurance reading as ``interactive`` would
    make the field's fail-closed property decorative — the day a machine-facing door mints a
    principal, an omitted field is the shape most likely to arrive.
    """
    with pytest.raises(TerminalError) as raised:
        cpactor.trusted_actor(block(**overrides))

    assert raised.value.reason == UNSUPPORTED_ASSURANCE, case
    assert raised.value.reason != "unauthorized", case


@pytest.mark.parametrize(
    ("overrides", "case"),
    [
        ({"delegated_by": "svc-x"}, "a delegated actor"),
        ({"delegated_by": _DROP}, "the key omitted"),
    ],
)
def test_delegated_by_must_be_present_and_null(overrides, case):
    """The API stamps an explicit null, so an absent key is a malformed block, not a default.

    A non-null value is refused while the accepted set holds only ``interactive``: the two fields
    cannot disagree, and a delegated actor arriving under an interactive assurance is the exact
    confusion the pair exists to prevent.
    """
    with pytest.raises(TerminalError) as raised:
        cpactor.trusted_actor(block(**overrides))

    assert raised.value.reason == UNSUPPORTED_ASSURANCE, case


def test_a_caller_supplied_exception_type_carries_the_refusal():
    """A plane whose Catch keys on its own type gets that type, with the reason still readable.

    ``unauthorized`` keeps the bare detail those planes have always raised. Anything else prefixes
    the code, because the caller's type carries a string and nothing else — without the prefix an
    assurance refusal on those two planes would be indistinguishable from a malformed envelope in
    every record anyone can read.
    """
    with pytest.raises(DomainError) as unauth:
        cpactor.trusted_actor({"requestId": "r"}, exc=DomainError)
    assert "identity block" in str(unauth.value)
    assert not str(unauth.value).startswith("unauthorized:")

    with pytest.raises(DomainError) as assurance:
        cpactor.trusted_actor(block(assurance="delegated"), exc=DomainError)
    assert str(assurance.value).startswith(f"{UNSUPPORTED_ASSURANCE}: ")


def test_the_accepted_set_holds_exactly_the_one_minted_value():
    """A widening is a deliberate edit here, never a side effect of a plane relaxing its own check."""
    assert frozenset({cpactor.ASSURANCE_INTERACTIVE}) == cpactor.ACCEPTED_ASSURANCE
    assert cpactor.ASSURANCE_INTERACTIVE == "interactive"


def test_the_reader_cannot_verify_and_makes_no_call_out():
    """A reader that could verify is a reader that will grow a second verifier.

    Parsed rather than grepped, so the module may EXPLAIN in its docstring why it does not verify
    without tripping the check on its own prose — a sweep a docstring can fail gets loosened the
    first time it does, and a loosened sweep is one nobody trusts.
    """
    source = pathlib.Path(cpactor.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)

    forbidden = {"jwt", "boto3", "botocore", "os", "urllib", "requests"}
    assert not forbidden & {name.split(".")[0] for name in imported}, imported
    assert not any("auth" in name for name in imported), imported
    assert not any("clients" in name for name in imported), imported
