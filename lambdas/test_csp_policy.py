"""The Content-Security-Policy, and the move that gave it one home.

The policy used to be assembled inside ``infra/modules/app``, where a root-level check could not
read it and where the module's own retirement would have taken the computation with it. It is at
root now, and this file is what makes that a move rather than a rewrite.

**Why a byte-identity test at all.** A CSP is observed by nothing offline — no unit test, no plan,
no scanner reads a response header — and the one recorded outage from this file's subject came from
a single missing ``connect-src`` term that a signed-in tester could not have seen. So the move is
proved against a literal copy of the pre-move string rather than against a retyped copy of the new
one, which would assert only that the file equals itself.

**ACCEPTED_PRE_MOVE_DIRECTIVES pins the MOVE, not the policy.** A deliberate CSP change updates both
halves and that is correct; what must never happen is one half being edited to make the other pass.
Revisit the decision, do not delete the test.

Attributes:
  INFRA: The IaC tree.
  ROOT_MAIN: Where both CSP locals live after the move.
  ROOT_OUTPUTS: Carries the Hosted-UI drift precondition the served policy depends on.
  ACCEPTED_PRE_MOVE_DIRECTIVES: The policy's directive list as it stood immediately before the
    move — the true pre-move text, ``${var.csp_connect_src}`` and all. The reference changing to
    a root local is the ONE permitted difference, normalised at the comparison rather than baked
    into this constant, so the exemption is visible instead of hidden. The hole's own contents
    are asserted term by term in ``test_api_module.py``, which owns that list — a copy here would
    be a second place to edit for one change.
  ACCEPTED_SEPARATOR: What the directives are joined on. Part of the emitted bytes: joined on a
    space instead, the policy is one malformed directive and every other directive is dropped by
    the browser — an element-only comparison cannot see it.
"""

import pathlib

from tf_blocks import join_list_items

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
ROOT_MAIN = INFRA / "main.tf"
ROOT_OUTPUTS = INFRA / "outputs.tf"

ACCEPTED_SEPARATOR = "; "

ACCEPTED_PRE_MOVE_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data:",
    "font-src 'self' data: https://fonts.gstatic.com",
    "worker-src 'self' blob:",
    "connect-src ${var.csp_connect_src}",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
)


def test_the_policy_string_is_byte_identical_to_its_pre_move_value() -> None:
    """The separator and the directive list, term for term and in order, against a recorded copy.

    Compared against a literal rather than against the file it is testing: a test that re-derived
    the expectation from the new source would assert that the file equals itself, and would have
    accepted a directive silently dropped during the move.

    The separator is asserted too, and it is not a formality — joined on a space the whole policy
    collapses to one malformed directive and the browser drops every other one, which is the app's
    entire network surface gone with every element still in place.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the separator changed, or when any directive was added, dropped,
        reordered or edited by the move.
    """
    separator, now = join_list_items(ROOT_MAIN.read_text(), "content_security_policy")

    assert separator == ACCEPTED_SEPARATOR, (
        f"The directives are joined on {separator!r}, not {ACCEPTED_SEPARATOR!r}. Every element "
        "can be correct and the emitted policy still be one malformed directive."
    )

    # THE ONE PERMITTED DIFFERENCE, applied here rather than recorded in the constant: the move
    # repointed connect-src from a module input at a root local. Normalising at the comparison
    # keeps the exemption readable; baking it into the expectation would make this a copy of the
    # new source, which is what the test exists not to be.
    normalised = tuple(
        directive.replace("${local.csp_connect_src}", "${var.csp_connect_src}") for directive in now
    )

    assert len(normalised) == len(ACCEPTED_PRE_MOVE_DIRECTIVES), (
        f"The policy has {len(normalised)} directives; it had "
        f"{len(ACCEPTED_PRE_MOVE_DIRECTIVES)} before the move. If this is a deliberate CSP change, "
        "update both halves of this test and say so in the commit — do not edit one to make the "
        "other pass."
    )
    assert normalised == ACCEPTED_PRE_MOVE_DIRECTIVES, (
        f"The policy changed during a move that was supposed to change nothing.\n"
        f"  before: {ACCEPTED_PRE_MOVE_DIRECTIVES}\n  after:  {normalised}"
    )


def test_connect_src_still_names_both_cognito_hosts() -> None:
    """The two entries whose loss a signed-in tester cannot see, asserted by name.

    Stated on its own, and deliberately not as part of a whole-list comparison —
    ``test_api_module.py`` owns that list. A reader deletes these two on purpose, reasoning that the
    Identity Pool is retired — it is — or that the provider changes later, and would then update a
    list assertion to match the mistake. Neither reaches these hosts. Amplify still runs in the
    browser: the authorization-code exchange POSTs to the Hosted UI host and token refresh calls
    cognito-idp, so a policy without them produces a portal that works for everyone already signed
    in and for nobody else.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either Cognito host is absent from the source list.
    """
    separator, terms = join_list_items(ROOT_MAIN.read_text(), "csp_connect_src")
    assert terms, "connect-src's list parsed empty — the parse went trivial."
    assert separator == " ", (
        f"connect-src's terms are joined on {separator!r}. A source list is space-separated; "
        "anything else is one unparseable source expression and a policy that blocks every fetch."
    )

    assert any("cognito-idp." in term for term in terms), (
        "connect-src lost the cognito-idp host. Amplify refreshes tokens and revokes them there; "
        "this arc does not retire it."
    )
    assert any("cognito_hosted_ui_domain" in term for term in terms), (
        "connect-src lost the Hosted UI domain. The authorization-code exchange is the only fetch "
        "to that host, a warm session never makes it, and its absence broke fresh sign-in for a "
        "day once already."
    )


def test_the_parser_sees_an_unquoted_element() -> None:
    """The parser everything above trusts, driven against the shape that once slipped past one.

    A regex over quoted strings alone is complete only while every element is a literal. Both of
    these lists carry interpolated locals, and a directive or a host that arrived as one would be
    invisible — added to the emitted policy with every assertion over it still green. That was
    rediscovered once in this repository already, which is why the parser is shared and why this
    drives it rather than trusting its name.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When an unquoted element is dropped, when the separator is not returned, or
        when a malformed list is accepted instead of refused.
    """
    source = """locals {
  probe = join("; ", [
    "quoted-one",
    # a comment, which is not an element
    local.unquoted_one,
    "quoted-two",
  ])
}"""
    separator, items = join_list_items(source, "probe")

    assert separator == "; ", separator
    assert items == ("quoted-one", "local.unquoted_one", "quoted-two"), (
        f"the parser returned {items} — an unquoted element or a comment was mishandled"
    )

    # Refusing beats returning nothing: an empty result is what every caller compares against and
    # passes on, which is the failure mode this whole file is written against.
    for broken, why in (
        ('locals {\n  other = join("; ", ["x"])\n}', "a local that is not there"),
        ('locals {\n  probe = join(sep, ["x"])\n}', "a separator that is not a literal"),
    ):
        try:
            join_list_items(broken, "probe")
        except ValueError:
            continue
        raise AssertionError(f"the parser accepted {why} instead of refusing")
