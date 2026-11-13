"""The web tier's switch, which now has one side.

``network`` and ``spa`` are the tier, and the repository variable that switches them is the only
thing deciding whether the portal is served. With the static portal retired there is no other
side, so the one property left to hold is that both modules move together: a network built without
the service bills for nothing, and a service without its network cannot be created at all.

Attributes:
  ROOT_MAIN: The root composition.
  TIER_COUNT: The count both modules carry.
"""

import pathlib

from tf_blocks import module_calls

ROOT_MAIN = pathlib.Path(__file__).resolve().parent.parent / "infra" / "main.tf"

TIER_COUNT = "count  = local.web_tier_enabled ? 1 : 0"


def test_network_and_spa_are_both_counted_on_the_switch() -> None:
    """Both modules exist exactly when the switch is on.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either module's count is anything but the switch, or when the root
        composition still calls a module serving the portal from anywhere else.
    """
    calls = module_calls(ROOT_MAIN.read_text())
    assert "network" in calls and "spa" in calls, f"the parse found {sorted(calls)}"

    assert TIER_COUNT in calls["network"], "the network is no longer counted on the switch"
    assert TIER_COUNT in calls["spa"], "the service is no longer counted on the switch"
    assert "static_portal" not in calls, "a second front door is back beside the web tier"
