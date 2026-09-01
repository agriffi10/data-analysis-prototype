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
        found[match.group(1)] = text[match.end() : _close(text, match.end()) - 1]
    return found


def _close(text: str, index: int) -> int:
    """Scans from just inside an open brace to just past the one that closes it.

    Strings and comments are skipped here rather than by each caller, which is the whole reason
    this is one function: a naive count ends a block at the ``}`` inside ``tags = { Name =
    "closes early }" }``, and an unbalanced brace inside a ``#`` comment swallows whatever
    follows.

    Args:
      text: The Terraform source being read.
      index: The offset immediately after the opening brace.

    Returns:
      The offset immediately after the matching closing brace, or the end of an unterminated
      comment, matching what the block scan has always done with malformed input.

    Raises:
      None.
    """
    depth = 1
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
    return index


def span(text: str, start: int) -> str:
    """Returns the braced block beginning at or after ``start``, braces included.

    The counterpart to ``blocks`` for everything that is not a top-level resource — a ``locals``
    block, a map local, one entry inside it. It exists so those reads go through the SAME
    string-and-comment-aware counter: a second one written beside a suite is the copy that
    drifts, and the drift shows up as a cascade of failures naming resources that are fine.

    Args:
      text: The Terraform source to read.
      start: An offset at or before the block's opening brace.

    Returns:
      The block, including its outer braces.

    Raises:
      ValueError: If no opening brace follows ``start``, rather than returning an empty string
        that every caller would then parse to nothing and pass over.
    """
    opening = text.index("{", start)
    return text[opening : _close(text, opening + 1)]


def join_list_items(text: str, local_name: str) -> tuple[str, str]:
    """Splits a ``<name> = join("<sep>", [ … ])`` local into its separator and its elements.

    **Quoted AND unquoted elements**, which is the whole reason this lives here rather than in
    one suite. A regex over quoted strings alone is complete only while every element is a
    literal; these lists also carry interpolated locals, and a term that arrives as one is
    invisible to that pattern — a directive silently added to a policy, or a host silently added
    to a network surface, with every assertion over it still green. That has been rediscovered
    once already.

    **The separator is returned, not discarded.** It is part of the emitted bytes: a policy
    joined on `" "` instead of `"; "` is one malformed directive, every other directive dropped
    by the browser, and an element-only comparison cannot see it.

    Order is preserved, because a CSP is a sequence and a set comparison would accept a
    reordering.

    Args:
      text: The Terraform source to read.
      local_name: The local's name, e.g. ``content_security_policy``.

    Returns:
      The separator literal and the elements, each unquoted if it was quoted.

    Raises:
      ValueError: When the local, its list or its separator cannot be found — never a silent
        empty result, which every caller would compare against and pass.
    """
    start = text.find(f"{local_name} = join(")
    if start == -1:
        raise ValueError(f"no `{local_name} = join(...)` local — the parse went trivial")
    end = text.find("])", start)
    if end <= start:
        raise ValueError(f"`{local_name}`'s list does not close where expected")

    block = text[start:end]
    opening = block.index("[")
    separator = block[block.index("(") + 1 : opening].strip().rstrip(",").strip()
    if not separator.startswith('"'):
        raise ValueError(f"`{local_name}`'s separator is not a literal: {separator!r}")

    items = []
    for raw in block[opening:].splitlines()[1:]:
        line = raw.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        items.append(line[1:-1] if line.startswith('"') and line.endswith('"') else line)
    return separator[1:-1], tuple(items)
