"""The CSP's one environment-shaped directive, and the parser that reads it out of Terraform.

``connect-src`` is the only directive Terraform still computes: ``csp_connect_src`` at root, carried
to the container as ``PORTAL_CSP_CONNECT_SRC``. Every other directive is a property of the bundle
and lives in the Next.js server's policy builder, where a TypeScript test holds them against a
recorded literal; this file used to hold that literal too, while Terraform assembled the whole
policy for a CloudFront distribution that no longer exists.

Attributes:
  INFRA: The IaC tree.
  ROOT_MAIN: Where ``csp_connect_src`` lives.
"""

import pathlib

from tf_blocks import join_list_items

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
ROOT_MAIN = INFRA / "main.tf"


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
