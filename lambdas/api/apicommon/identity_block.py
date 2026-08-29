"""The identity a message carries, written by this service from the verified bearer.

One top-level key holding three fields, and it is nested rather than flat because it has to be:
on table-share, file-send, archive and file-ops the top-level field named ``actor`` **is the raw
ID token today**, so a flat verified ``actor`` would overwrite the very field those planes verify.
That is the ordering failure this whole change exists to avoid.

It stays nested after the cutover. The token field is removed rather than the block being moved
into its place, so there is no second migration and no window in which one plane's ``actor`` is a
username while another's is still a JWT.

Nothing in the block is secret, and that is load-bearing rather than incidental: the dead-letter
drain's redaction replaces TOP-LEVEL keys only, so anything nested here reaches CloudWatch verbatim
when a message dead-letters.

Attributes:
  ASSURANCE_INTERACTIVE: The only assurance value this service can mint. It names the assurance
    KIND rather than the mechanism that produced it — ``verified-id-token`` would need renaming
    the day the provider changes or a machine-facing caller mints a delegated one.
"""

from typing import Literal, TypedDict

from cpcommon.auth import Principal

Assurance = Literal["interactive"]

ASSURANCE_INTERACTIVE: Assurance = "interactive"


class IdentityBlock(TypedDict):
    """Who this message is on behalf of, as the planes will come to read it.

    Attributes:
      actor: The caller's verified username. Never a value out of a request body.
      delegated_by: Who asked the actor's behalf be acted on. Always ``None`` here, and PRESENT
        rather than omitted — an absent key and a null key are different to a strict parser, and
        the planes are written to refuse the absent one.
      assurance: How the actor was established.
    """

    actor: str
    delegated_by: str | None
    assurance: Assurance


def build(principal: Principal) -> IdentityBlock:
    """Builds the block for one verified caller.

    Args:
      principal: The verified caller, whose username is the only claim that reaches the block.

    Returns:
      The identity block, with every field present.

    Raises:
      None.
    """
    return IdentityBlock(
        actor=principal.username,
        delegated_by=None,
        assurance=ASSURANCE_INTERACTIVE,
    )
