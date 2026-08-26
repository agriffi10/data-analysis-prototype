"""Reads Terraform source as text, for the infrastructure suites that assert over it.

Every assertion built on this is a TEXT assertion: it can prove what the configuration says
and never what AWS applied. The live checks own the second half.

Extracted when the second consumer arrived rather than copied into it — a brace counter that
skips strings and comments is exactly the kind of helper whose two copies drift apart in the
one case that matters.

Attributes:
  None.
"""

import re


def blocks(text: str, kind: str) -> dict[str, str]:
    """Splits Terraform source into top-level resource blocks of one type.

    A brace-counting split rather than a regex over the whole block, because a resource body
    contains nested braces and a non-greedy match stops at the first inner one — which would
    quietly hide whatever came after it.

    **Strings and comments are skipped, and that is not fastidiousness.** A naive count ends the
    block at the ``}`` inside ``tags = { Name = "closes early }" }``, so everything after it —
    including a default route to a NAT gateway — falls outside the body and every assertion below
    reports clean. The reverse, an unbalanced brace inside a ``#`` comment, swallows the next
    resource whole and produces a failure naming the wrong one.

    Args:
      text: The Terraform source to read.
      kind: The resource type to collect, e.g. ``aws_route_table``.

    Returns:
      Each matching resource's local name mapped to its body.

    Raises:
      None.
    """
    found = {}
    for match in re.finditer(rf'resource\s+"{re.escape(kind)}"\s+"([^"]+)"\s*\{{', text):
        depth, index = 1, match.end()
        while depth and index < len(text):
            char = text[index]
            if char == "#" or text[index : index + 2] == "//":
                index = text.find("\n", index)
                if index == -1:
                    break
            elif char == '"':
                index += 1
                while index < len(text) and text[index] != '"':
                    index += 2 if text[index] == "\\" else 1
            else:
                depth += {"{": 1, "}": -1}.get(char, 0)
            index += 1
        found[match.group(1)] = text[match.end() : index - 1]
    return found
