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


def test_connect_src_names_neither_cognito_host_nor_the_api() -> None:
    """The hosts the browser stopped fetching when it stopped holding tokens, refused by name.

    Stated on its own, and deliberately not as part of a whole-list comparison —
    ``test_api_module.py`` owns that list. These were once asserted present by name, because Amplify
    in the browser fetched both Cognito hosts and the API. The portal server signs in and calls the
    API now, so the browser reaches Cognito only by navigation, which ``connect-src`` does not govern.
    A reader restoring them on the old reasoning would widen the browser's network surface for nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a Cognito host or the API's origin is back in the source list.
    """
    separator, terms = join_list_items(ROOT_MAIN.read_text(), "csp_connect_src")
    assert terms, "connect-src's list parsed empty — the parse went trivial."
    assert separator == " ", (
        f"connect-src's terms are joined on {separator!r}. A source list is space-separated; "
        "anything else is one unparseable source expression and a policy that blocks every fetch."
    )
    assert any("user_space_bucket_name" in term for term in terms), "the parse no longer reads the bucket terms"
    returned = [
        term for term in terms if "cognito-idp." in term or "cognito_hosted_ui_domain" in term or "api_origin" in term
    ]
    assert returned == [], f"connect-src names {returned}; the browser no longer fetches Cognito or the API"


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
