"""Unit tests for dqcommon.config — the DQ_* caps and their import-time validation.

Mirrors control-plane-common/test_config_cpcommon.py and shared-space-common/
test_config_shared_space.py, which both exercise their module's fail-fast rather than
trusting that it is wired. Runnable under pytest or directly.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from dqcommon import config


def test_caps_are_positive_ints():
    for name in (
        "DQ_MAX_OBJECTS",
        "DQ_MAX_GZIP_OBJECT_BYTES",
        "DQ_MAX_PARTITION_VALUES",
        "DQ_MAX_COLUMNS",
        "DQ_SCAN_TOTAL_BYTES",
    ):
        value = getattr(config, name)
        assert isinstance(value, int) and not isinstance(value, bool) and value > 0


@pytest.mark.parametrize("bad", [0, -1, 1.5, "1000", True, None])
def test_validate_caps_rejects_a_meaningless_cap(monkeypatch, bad):
    """FR-004: caps are validated at import, so a bad edit fails at COLD START.

    Without this the module imports happily and the cap surfaces as an inexplicable
    terminal on every request instead of one clear error. `True` is in the list because
    bool subclasses int — `isinstance(True, int)` is True, so a naive check would let
    `DQ_MAX_OBJECTS = True` (i.e. 1) through and silently reject every folder with more
    than one file.
    """
    monkeypatch.setattr(config, "DQ_MAX_OBJECTS", bad)
    with pytest.raises(RuntimeError, match="DQ_MAX_OBJECTS"):
        config._validate_caps()


def test_the_module_imports_clean_at_the_shipped_values():
    importlib.reload(config)  # runs _validate_caps() at the bottom of the module


def test_reserved_prefixes_cover_this_arcs_own_report_folder():
    assert "_data-quality-reports" in config.RESERVED_PREFIXES


def test_extension_map_is_the_documented_set():
    assert config.EXT_FORMAT == {
        ".csv": "csv",
        ".txt": "csv",
        ".json": "json",
        ".ndjson": "json",
        ".jsonl": "json",
        ".parquet": "parquet",
    }


def test_txt_is_csv_here_unlike_table_builder():
    """A deliberate divergence from table-builder's map, not an accident — pinned so it
    isn't "corrected" back into line."""
    assert config.EXT_FORMAT[".txt"] == "csv"


def test_parquet_is_supported_so_convert_then_verify_composes():
    assert config.EXT_FORMAT[".parquet"] == "parquet"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
