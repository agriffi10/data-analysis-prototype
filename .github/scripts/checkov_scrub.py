#!/usr/bin/env python3
"""Writes a copy of a Checkov plan result with every resource's planned values removed.

Checkov copies each scanned resource's planned values into its JSON result, under
`check_result.entity` and, without `--compact`, in each check's `code_block` too, and a plan carries
a sensitive value in plain text: a SecureString parameter's `value` reaches the result whole. The result is uploaded as a workflow artifact, so
the copy that is published must not hold them. What the gates read (check ids, resources, counts)
survives the scrub.

The scrubbed copy is a separate file on purpose. The upload names only that file, so a scrub
that fails leaves nothing to upload rather than the unscrubbed original.

Usage:
    checkov_scrub.py <checkov-plan.json> <publishable.json>

Attributes:
    SCRUBBED_KEYS: The keys removed wherever they appear: the resource's values and its source lines.
"""

import json
import os
import pathlib
import sys
from typing import Any

SCRUBBED_KEYS = frozenset({"entity", "code_block"})


def scrub(node: Any) -> Any:
    """Returns a copy of a parsed Checkov result with every scrubbed key removed at any depth.

    Args:
      node: Any parsed JSON value.

    Returns:
      The same value, rebuilt without the scrubbed keys.

    Raises:
      None.
    """
    if isinstance(node, dict):
        return {key: scrub(value) for key, value in node.items() if key not in SCRUBBED_KEYS}
    if isinstance(node, list):
        return [scrub(item) for item in node]
    return node


def main(argv: list[str]) -> int:
    """Reads a Checkov result, scrubs it, and writes the publishable copy atomically.

    Args:
      argv: The input path and the output path.

    Returns:
      0 on success, 2 when the arguments are wrong or the input is not JSON.

    Raises:
      None.
    """
    if len(argv) != 2:
        print("usage: checkov_scrub.py <checkov-plan.json> <publishable.json>", file=sys.stderr)
        return 2
    source, target = pathlib.Path(argv[0]), pathlib.Path(argv[1])
    try:
        parsed = json.loads(source.read_text())
    except (OSError, ValueError):
        print(f"checkov_scrub: {source} is not a readable JSON result; nothing written.", file=sys.stderr)
        return 2
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps(scrub(parsed)))
    os.replace(partial, target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
