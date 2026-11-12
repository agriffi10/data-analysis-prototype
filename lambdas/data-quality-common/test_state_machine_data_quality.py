"""What only the data-quality machine has: the execution ARN reaches the verb that claims the run.

The fleet-wide invariants — reachability, the failure seeds, the trace shapes — live in
``control-plane-common`` and pass with this state removed or moved, which is why it is pinned here.
Without it, inspect-source finds no ARN and refuses every check as malformed; placed after
inspect-source, the claim would be refused the same way on every run.

Reads the deployed template rather than a copy, so drift fails rather than passes.

Attributes:
  _TFTPL: The data-quality state machine template.
"""

import json
import os
import re

_TFTPL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "infra", "planes", "data-quality", "state-machine.asl.json.tftpl",
)


def _states() -> dict:
    """Parses the template with every interpolation replaced by a placeholder.

    Args:
      None.

    Returns:
      The machine's states, by name.

    Raises:
      None.
    """
    with open(_TFTPL) as handle:
        return json.loads(re.sub(r"\$\{[^}]+\}", "ARN", handle.read()))["States"]


def test_the_execution_arn_is_stamped_between_the_validator_and_the_claim() -> None:
    """A Pass puts the ARN on the state after validation and before inspect-source reads it.

    A Pass rather than inspect-source's own Parameters: reading ``$$`` there builds an object that
    wraps the payload, and every verb reads the request at the top level of its event.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the stamp is missing, reshaped or out of order.
    """
    states = _states()
    stamp = states["StampExecution"]

    assert states["ValidateAuthorize"]["Next"] == "StampExecution"
    assert stamp["Type"] == "Pass"
    assert stamp["Parameters"] == {"arn.$": "$$.Execution.Id"}
    assert stamp["ResultPath"] == "$.execution"
    assert stamp["Next"] == "InspectSource"
    assert states["InspectSource"]["Parameters"] == {"FunctionName": "ARN", "Payload.$": "$"}
