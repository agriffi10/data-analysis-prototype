"""The data-quality reserved prefixes, member for member, now that two of them are shared."""

from dqcommon import config


def test_the_reserved_prefixes_are_exactly_these_six():
    """Spelled out: a set built from imported names cannot widen or shrink unnoticed."""
    assert frozenset(
        {"athenaresults", "user_settings", "shared_tables", "_data-quality-reports", "_fc-work", "_directory"}
    ) == config.RESERVED_PREFIXES
