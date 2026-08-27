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
    move, with ``connect-src`` held as a hole because its value is assembled separately. The
    hole's own contents are asserted term by term in ``test_api_module.py``, which owns that
    list — a copy here would be a second place to edit for one change.
"""

import pathlib
import re

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
ROOT_MAIN = INFRA / "main.tf"
ROOT_OUTPUTS = INFRA / "outputs.tf"
APP_CLOUDFRONT = INFRA / "modules" / "app" / "cloudfront.tf"
APP_VARIABLES = INFRA / "modules" / "app" / "variables.tf"

ACCEPTED_PRE_MOVE_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data:",
    "font-src 'self' data: https://fonts.gstatic.com",
    "worker-src 'self' blob:",
    "connect-src ${local.csp_connect_src}",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
)


def _list_items(text: str, local_name: str) -> tuple[str, ...]:
    """Returns the quoted elements of a ``<name> = join("; ", [...])`` local, in order.

    Order is part of the claim: a CSP is a sequence of directives and a set comparison would
    accept a reordering that changes which directive a browser applies first.

    Args:
      text: The Terraform source to read.
      local_name: The local's name, e.g. ``content_security_policy``.

    Returns:
      Each element's literal source text, unquoted, in declaration order.

    Raises:
      AssertionError: When the local or its list cannot be found, so that no comparison below
        runs against an empty tuple and passes.
    """
    start = text.find(f"{local_name} = join(")
    assert start > -1, f"No `{local_name} = join(...)` local — the parse went trivial."
    end = text.find("])", start)
    assert end > start, f"`{local_name}`'s list does not close where expected."
    body = text[start:end]
    return tuple(re.findall(r'^\s*"([^"]*)",\s*$', body, re.MULTILINE))


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
    assert "content_security_policy = join(" in root
    assert "csp_connect_src = join(" in root
    assert "content_security_policy = var.content_security_policy" in module, (
        "The response-headers policy no longer reads the module input."
    )

    # The orphan. Once the assembled string arrives whole, the module has no use for the source
    # list, and a surviving unused input is a second place a later reader would wire.
    assert "csp_connect_src" not in APP_VARIABLES.read_text().replace(
        "# constructed strings, and before that from `csp_connect_src` alone; both are", ""
    ), "modules/app still declares csp_connect_src, which nothing in it reads."


def test_the_policy_string_is_byte_identical_to_its_pre_move_value() -> None:
    """The directive list, term for term and in order, against the recorded pre-move copy.

    Compared against a literal rather than against the file it is testing: a test that re-derived
    the expectation from the new source would assert that the file equals itself, and would have
    accepted a directive silently dropped during the move.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any directive was added, dropped, reordered or edited by the move.
    """
    now = _list_items(ROOT_MAIN.read_text(), "content_security_policy")
    assert len(now) == len(ACCEPTED_PRE_MOVE_DIRECTIVES), (
        f"The policy has {len(now)} directives; it had {len(ACCEPTED_PRE_MOVE_DIRECTIVES)} before "
        "the move. If this is a deliberate CSP change, update both halves of this test and say so "
        "in the commit — do not edit one to make the other pass."
    )
    assert now == ACCEPTED_PRE_MOVE_DIRECTIVES, (
        f"The policy changed during a move that was supposed to change nothing.\n"
        f"  before: {ACCEPTED_PRE_MOVE_DIRECTIVES}\n  after:  {now}"
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
    terms = _list_items(ROOT_MAIN.read_text(), "csp_connect_src")
    assert terms, "connect-src's list parsed empty — the parse went trivial."

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

    root = ROOT_MAIN.read_text()
    assert "cognitoDomain           = local.cognito_hosted_ui_domain" in root, (
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
    root = ROOT_MAIN.read_text()
    assert "content_security_policy = local.content_security_policy" in root, (
        "module.app no longer receives the assembled policy."
    )
    assert "csp_connect_src = local.csp_connect_src" in root, (
        "module.spa's connect-src is no longer the root local unmodified. A filter or a rebuild "
        "interposed here is how the two delivery paths start emitting different policies."
    )
