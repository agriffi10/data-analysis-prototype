"""The one reader of the trusted actor a queue message carries.

Every control plane used to verify a Cognito ID token that arrived inside the message body. That
was correct while the browser was the sender: the queue was writable by every signed-in user's
credentials, so only a signature could say who was asking. The API is now the only principal that
may write to these queues, and it verifies the bearer at the edge and stamps what it verified into
a nested ``identity`` block. Reading that block is therefore reading a value this deployment's own
service established, not a value a caller asserted.

**The trust rests on who may write the queue, not on cryptography, so this module must never grow
the ability to verify.** It makes no network call, reads no environment variable, imports neither
``jwt`` nor ``cpcommon.auth``, and an import sweep asserts each of those — a reader that could
verify is a reader that will grow a second verifier, and the whole point of the collapse was that
five of them had drifted.

**The flat top-level ``actor`` field beside the block is never consulted.** On table-share,
file-send, archive and file-ops that field holds the raw ID token in any message enqueued before
the cutover, and a raw JWT and a username are both non-empty strings — so a reader shaped "take the
block, fall back to the field" passes every well-formed fixture and builds an S3 prefix, a Glue
database name and a notification recipient out of a 900-character token on the first message from
before the flip. The block is read into a local and nothing else is read at all.

Dropping the verification is not dropping an authorization. The token answered "is this really
alice?", which the API answers now. Whether alice may do the thing is still decided by each plane's
own authorizer, and none of those moved.

Attributes:
  ASSURANCE_INTERACTIVE: How the API establishes an actor today — an OIDC ID token presented by an
    interactive browser session, with the username taken from the verified claim. It names the
    assurance KIND rather than the mechanism, so a provider swap needs no rename.
  ACCEPTED_ASSURANCE: The assurance values a control plane will act on. The single definition in
    the fleet; no plane declares its own, and a sweep enforces that. A later arc's machine-facing
    door widens this set here, in one module.
  UNSUPPORTED_ASSURANCE: The refusal for a principal kind this plane does not accept. Distinct from
    ``unauthorized`` on purpose: an unknown assurance is a request the plane understood and
    declined to act on, not one it could not attribute.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import config
from .errors import TerminalError
from .messages import UNSUPPORTED_ASSURANCE

ASSURANCE_INTERACTIVE = "interactive"
ACCEPTED_ASSURANCE = frozenset({ASSURANCE_INTERACTIVE})

_IDENTITY = "identity"
_ACTOR = "actor"
_DELEGATED_BY = "delegated_by"
_ASSURANCE = "assurance"


@dataclass(frozen=True)
class Actor:
    """Who a message is on behalf of, as the API verified them.

    Attributes:
      username: The caller's verified username, catalog-safe by construction — it is checked
        against the same rule the S3 prefix, the principal tag and the Glue database name use,
        because it is all four. Matched with ``fullmatch``, not ``match``: the shared pattern
        ends in ``$``, which in Python also matches before a trailing newline, so ``"alice\n"``
        would otherwise pass the rule that every downstream key is built from.
      delegated_by: Who asked that the actor's behalf be acted on. ``None`` for every message this
        arc produces; a non-``None`` value is refused today rather than ignored.
      assurance: How the actor was established. Always a member of ``ACCEPTED_ASSURANCE``.
    """

    username: str
    delegated_by: str | None
    assurance: str


def _refuse(
    exc: Callable[[str], Exception] | None, reason: str, detail: str
) -> Exception:
    """Builds the refusal, in the caller's own exception type where it supplied one.

    A plane whose Catch keys on its own exception type passes ``exc``, and that type carries a
    string rather than a reason code — so for anything but ``unauthorized`` the code is prefixed
    into the detail, which is the only place it can survive on those two planes.

    **It does NOT come back out through ``errors.failure_reason``**, and saying so matters because
    the shape invites the assumption: that decoder gates on ``errorType == "TerminalError"``, and
    these callers raise ``AuthorizationError``. The prefix is for a human reading a log line or a
    Step Functions Cause, not for a machine. What those planes lose is a distinguishable reason
    CODE, which is why the live check for an unaccepted assurance is aimed at a plane that takes
    the default exception instead.

    Args:
      exc: The caller's one-argument exception factory, or None for the default.
      reason: The registered reason code to raise under.
      detail: Operator context.

    Returns:
      The exception to raise.

    Raises:
      None.
    """
    if exc is None:
        return TerminalError(reason, detail)
    if reason == UNSUPPORTED_ASSURANCE:
        return exc(f"{reason}: {detail}")
    return exc(detail)


def trusted_actor(
    req: Any, *, exc: Callable[[str], Exception] | None = None
) -> Actor:
    """Reads the trusted actor out of a parsed queue message.

    The refusal order is load-bearing rather than stylistic: the block's shape, then the actor's,
    then the two fields that describe the principal KIND. Checking assurance first would report a
    message with no identity block at all as an assurance problem, and the honest refusal for a
    pre-cutover envelope is that the block is missing.

    A refusal is total. There is no default actor, no coercion, and no second field consulted —
    including the flat top-level ``actor``, which on four planes holds a raw token in any message
    enqueued before the cutover and would resolve to a plausible-looking non-empty string.

    Args:
      req: The parsed message body, as ``events.parse_sqs_request`` returns it. Typed ``Any``
        because that parse is unguarded: a body that is valid JSON of another type is returned
        as-is, and this function refuses it rather than assuming a mapping.
      exc: A one-argument exception factory for a plane whose Catch behaviour is expressed in its
        own exception type. Defaults to ``TerminalError``.

    Returns:
      The trusted actor.

    Raises:
      TerminalError: ``unauthorized`` when the identity block or its actor is absent or malformed,
        ``unsupported_assurance`` when the principal kind is one this plane does not accept — or
        whatever ``exc`` builds, in the same cases.
    """
    block = req.get(_IDENTITY) if isinstance(req, Mapping) else None
    if not isinstance(block, Mapping):
        raise _refuse(
            exc, "unauthorized", "the request carries no identity block"
        )

    username = block.get(_ACTOR)
    if not isinstance(username, str) or not config.CATALOG_IDENTIFIER_RE.fullmatch(
        username
    ):
        raise _refuse(
            exc, "unauthorized", "the identity block carries no usable actor"
        )

    if _DELEGATED_BY not in block:
        raise _refuse(
            exc, UNSUPPORTED_ASSURANCE, "the identity block omits delegated_by"
        )
    delegated_by = block[_DELEGATED_BY]
    if delegated_by is not None:
        raise _refuse(
            exc, UNSUPPORTED_ASSURANCE, "a delegated actor is not accepted here"
        )

    assurance = block.get(_ASSURANCE)
    if not isinstance(assurance, str) or assurance not in ACCEPTED_ASSURANCE:
        raise _refuse(
            exc, UNSUPPORTED_ASSURANCE, f"assurance {assurance!r} is not accepted"
        )

    return Actor(
        username=username,
        delegated_by=None,
        assurance=assurance,
    )
