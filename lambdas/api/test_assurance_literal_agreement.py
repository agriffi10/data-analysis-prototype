"""One assurance vocabulary, shared by the service that mints it and the planes that accept it.

The API stamps ``assurance`` into every message; the planes refuse anything outside the set they
accept. Those are two modules in two layers with two test suites, and nothing in either suite sees
the other's constant — so two hand-written copies of one string would let the contract disagree
while both suites stayed green, and the failure would present as every request being refused for a
principal kind nobody changed.

The agreement is therefore asserted by IMPORT rather than by restatement. ``conftest.py`` puts
every layer package root on ``sys.path``, so one test can hold both. It lives here, in the API's own suite, because this is the one place both constants import
without a path hack: ``cpcommon`` is a layer and reaches every suite, and ``apicommon`` is NOT —
it ships inside this function's package and only ``api/conftest.py`` puts it on the path.

The sweep proving no SECOND module declares an accepted set is a fleet-wide concern and lives at
the fleet root, in ``test_one_assurance_set.py``.
"""

from apicommon import identity_block
from cpcommon import actor as cpactor


def test_the_minted_literal_is_the_accepted_literal() -> None:
    """The value the API stamps is the value the planes accept, by import, not by restatement.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the producer's literal and the consumers' drifted apart.
    """
    assert cpactor.ASSURANCE_INTERACTIVE == identity_block.ASSURANCE_INTERACTIVE
    assert identity_block.ASSURANCE_INTERACTIVE in cpactor.ACCEPTED_ASSURANCE


def test_the_api_mints_nothing_the_planes_would_refuse() -> None:
    """Everything ``identity_block`` can produce is accepted, so no plane refuses a real request.

    Read off the ``Assurance`` Literal rather than off the one constant, because the type is what
    widens first when a machine-facing door is added — and a value added there but not to
    ``ACCEPTED_ASSURANCE`` is a producer minting what every consumer refuses.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the producer could mint a value no plane accepts.
    """
    mintable = set(identity_block.Assurance.__args__)

    assert mintable <= cpactor.ACCEPTED_ASSURANCE, (
        f"the API can mint {sorted(mintable - cpactor.ACCEPTED_ASSURANCE)}, which every "
        "plane refuses — widen ACCEPTED_ASSURANCE deliberately or stop minting it"
    )
