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
  APP_CLOUDFRONT: The module that used to hold them and now takes the assembled string.
  APP_VARIABLES: The module's inputs, where the orphaned ``csp_connect_src`` must not survive.
  ROOT_OUTPUTS: Carries the Hosted-UI drift precondition both delivery paths depend on.
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
import re

from tf_blocks import join_list_items

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
ROOT_MAIN = INFRA / "main.tf"
ROOT_OUTPUTS = INFRA / "outputs.tf"
APP_CLOUDFRONT = INFRA / "modules" / "app" / "cloudfront.tf"
APP_VARIABLES = INFRA / "modules" / "app" / "variables.tf"

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


def _module_block(name: str) -> str:
    """Returns one ``module "<name>" {…}`` block from the root composition.

    Scoped rather than searched whole: root composes twenty-odd modules, and a substring found
    anywhere in the file cannot tell which one it belongs to — so an argument wired to the wrong
    module would satisfy an unscoped assertion exactly.

    Args:
      name: The module's label.

    Returns:
      The block's body.

    Raises:
      AssertionError: When the block is absent, so no assertion on it runs vacuously.
    """
    text = ROOT_MAIN.read_text()
    marker = f'module "{name}" {{'
    assert marker in text, f"root does not compose module {name}."
    start = text.index(marker)
    end = text.index("\n}\n", start)
    assert end > start, f'module "{name}" does not close where expected.'
    return text[start:end]


def test_the_sources_were_found() -> None:
    """Guards every assertion below: an empty read agrees with everything.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a file this suite does not own has moved or been renamed.
    """
    assert "locals {" in ROOT_MAIN.read_text()
    assert "aws_cloudfront_response_headers_policy" in APP_CLOUDFRONT.read_text()
    assert "variable " in APP_VARIABLES.read_text()


def test_the_move_is_a_move_and_the_module_declares_neither_local() -> None:
    """Both locals live at root; the module reads the assembled string as an input.

    A module that still assembles its own policy would keep every criterion below green while
    the two delivery paths diverged — which is the whole failure this move prevents.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either local survives in the module, or root declares neither.
    """
    module = APP_CLOUDFRONT.read_text()
    root = ROOT_MAIN.read_text()

    assert "content_security_policy = join(" not in module, (
        "modules/app still assembles the policy. It moved to root so one computation feeds both "
        "delivery paths and so a root-level check has a referent it can read."
    )
    assert "csp_connect_src = join(" not in module, "modules/app still assembles connect-src."
    assert re.search(r"content_security_policy\s*=\s*join\(", root), (
        "root does not assemble the policy, so nothing does."
    )
    assert re.search(r"csp_connect_src\s*=\s*join\(", root), (
        "root does not assemble connect-src, so nothing does."
    )
    assert "content_security_policy = var.content_security_policy" in module, (
        "The response-headers policy no longer reads the module input."
    )

    # The orphan. Once the assembled string arrives whole, the module has no use for the source
    # list, and a surviving unused input is a second place a later reader would wire.
    #
    # Read as DECLARED NAMES rather than as raw text: a substring scan trips on any comment that
    # mentions the old name, which is a legal edit, and then fails naming the wrong cause.
    declared = re.findall(r'^variable "([^"]+)"', APP_VARIABLES.read_text(), re.MULTILINE)
    assert declared, "no variables parsed from modules/app — the parse went trivial."
    assert "csp_connect_src" not in declared, (
        "modules/app still declares csp_connect_src, which nothing in it reads."
    )
    assert "content_security_policy" in declared, (
        "modules/app does not declare the input the assembled policy arrives through."
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
    ``test_api_module.py`` owns that list. A reader holding the arc's END state in mind deletes
    these two on purpose, because the Identity Pool is retired later and the provider changes later
    still, and would then update a list assertion to match the mistake. Amplify runs in the browser
    for the whole of this arc: the authorization-code exchange POSTs to the Hosted UI host and token
    refresh calls cognito-idp, so a policy without them produces a portal that works for everyone
    already signed in and for nobody else.

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


def test_the_hosted_ui_term_is_covered_by_the_drift_precondition() -> None:
    """One local feeds the policy and the document, so the existing precondition covers both.

    The container's Cognito domain and the policy's Hosted-UI term are the same root local, so the
    drift check written for the distribution reaches the container too. Asserted rather than
    assumed, because a later edit that gave either path its own value would leave one delivery path
    correct and the other unable to complete a sign-in.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the precondition is gone, or when either consumer stops reading the
        shared local.
    """
    outputs = ROOT_OUTPUTS.read_text()
    assert "module.auth.user_pool_domain == local.cognito_hosted_ui_domain" in outputs, (
        "The Hosted-UI drift precondition is gone. Sign-in breaks with no failing test anywhere; "
        "that outage happened once already."
    )

    # Whitespace-tolerant: `tofu fmt` aligns these on the longest key in the map, and that map is
    # designed to grow. A literal-spacing assertion fails on a formatter run and blames the wrong
    # thing.
    root = ROOT_MAIN.read_text()
    assert re.search(r"cognitoDomain\s*=\s*local\.cognito_hosted_ui_domain\b", root), (
        "The runtime-configuration document no longer reads the local the precondition guards."
    )
    assert 'https://${local.cognito_hosted_ui_domain}"' in root, (
        "connect-src no longer reads the local the precondition guards."
    )


def test_both_delivery_paths_read_one_computation() -> None:
    """The distribution takes the assembled policy; the container takes only connect-src.

    That seam is the spec's: every directive other than ``connect-src`` describes the bundle and
    travels in the image, while the one environment-shaped directive arrives from the task
    definition. Baking the whole policy into the image would re-create the build-time-configuration
    problem the runtime-configuration document exists to end.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either module stops reading its half, or the container's input is not
        the root local unmodified.
    """
    assert re.search(
        r"content_security_policy\s*=\s*local\.content_security_policy\b", _module_block("app")
    ), "module.app no longer receives the assembled policy."

    assert re.search(r"csp_connect_src\s*=\s*local\.csp_connect_src\b", _module_block("spa")), (
        "module.spa's connect-src is no longer the root local unmodified. A filter or a rebuild "
        "interposed here is how the two delivery paths start emitting different policies."
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
