"""The name rules the browser mirrors, held against the ones the control planes enforce.

``cpcommon.config`` defines the catalog identifier rule and the partition-key name rule;
``apps/portal/src/lib/catalogIdentifier.ts`` re-spells both as regex literals so a dialog can say
what is wrong before a request is sent. Nothing at runtime notices when the two drift, and each
suite tests only its own copy, so a browser rule stricter than the plane's refuses a name the plane
accepts, and a looser one sends a request that comes back as a refusal notification.

The Python side is imported and the TypeScript is parsed out of its module, rather than both being
held against a third literal here, which would agree with itself while the two that matter drift.

Attributes:
  BROWSER_RULES: The browser module holding the mirrored literals.
  MIRRORED: The rule names that must be spelled identically in both languages.
"""

import pathlib
import re

import pytest
from cpcommon import config

BROWSER_RULES = (
    pathlib.Path(__file__).resolve().parent.parent
    / "apps"
    / "portal"
    / "src"
    / "lib"
    / "catalogIdentifier.ts"
)
MIRRORED = ("CATALOG_IDENTIFIER_RE", "PARTITION_KEY_NAME_RE")


def _browser_literal(name: str) -> tuple[str, str]:
    """Reads one exported regex literal out of the browser's rule module.

    Args:
      name: The exported constant's name.

    Returns:
      The literal's source between its slashes, and its flags.

    Raises:
      AssertionError: If the module does not export it as a regex literal, which would leave the
        comparison pinned to nothing.
    """
    found = re.search(
        rf"^export const {name} = /(.+)/([a-z]*);$",
        BROWSER_RULES.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert found, f"{BROWSER_RULES.name} exports no regex literal named {name}"
    return found.group(1), found.group(2)


@pytest.mark.parametrize("name", MIRRORED)
def test_the_browser_spells_each_rule_exactly_as_the_plane_does(name: str) -> None:
    """Equal source and no flags on either side.

    The flags are compared as well as the text because a case-insensitive flag keeps the source
    identical while admitting uppercase, and in Python it also lets ``[a-z]`` match the Kelvin sign.
    A Python ``str`` pattern always carries ``re.UNICODE``, so that is its no-flags value.

    Args:
      name: The rule's name in both modules.

    Returns:
      None.

    Raises:
      None.
    """
    rule = getattr(config, name)
    source, flags = _browser_literal(name)

    assert source == rule.pattern, (
        f"the browser's {name} is /{source}/ and the plane's is {rule.pattern!r}; a dialog and the "
        "plane now disagree about which names are valid"
    )
    assert flags == "", f"the browser's {name} carries flags {flags!r}"
    assert rule.flags == re.UNICODE, f"the plane's {name} carries flags {rule.flags!r}"


@pytest.mark.parametrize(
    ("name", "accepted"),
    [
        pytest.param("d", True, id="one-character"),
        pytest.param("dt", True, id="two-characters"),
        pytest.param("d" * 63, True, id="sixty-three-characters"),
        pytest.param("hour_2", True, id="digits-and-underscore-after-the-letter"),
        pytest.param("", False, id="empty"),
        pytest.param("d" * 64, False, id="sixty-four-characters"),
        pytest.param("_dt", False, id="leading-underscore"),
        pytest.param("1d", False, id="leading-digit"),
        pytest.param("Dt", False, id="uppercase"),
        pytest.param("order-id", False, id="hyphen"),
        pytest.param("dt\n", False, id="trailing-newline"),
    ],
)
def test_a_partition_key_name_is_one_to_sixty_three_catalog_safe_characters(
    name: str, accepted: bool
) -> None:
    """The partition-key rule's boundaries, applied the way the plane applies it.

    Args:
      name: A candidate key name.
      accepted: Whether the rule must accept it.

    Returns:
      None.

    Raises:
      None.
    """
    assert (config.PARTITION_KEY_NAME_RE.fullmatch(name) is not None) is accepted


def test_a_two_character_name_is_still_refused_as_a_table_or_username() -> None:
    """The key rule is a separate rule, not the shared one loosened.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    assert config.CATALOG_IDENTIFIER_RE.fullmatch("dt") is None
    assert config.CATALOG_IDENTIFIER_RE.fullmatch("dtx") is not None
