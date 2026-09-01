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


def strip_noise(text: str) -> str:
    """Blanks comments and string CONTENTS, preserving length and every other character.

    For scanning a block's assignments. A bare regex over the raw text reads a variable name out
    of a comment explaining it or a string quoting it, and reports it as though the block set it
    — which on a check that refuses certain names is a failure sentence describing something the
    file does not do. Length is preserved so an offset taken here still points into the original.

    Quotes are kept and their contents blanked, so a string remains recognisably a string while
    nothing inside it can match.

    Args:
      text: The Terraform fragment to blank.

    Returns:
      The fragment, same length, with comment and string bodies replaced by spaces.

    Raises:
      None.
    """
    out = list(text)
    index = 0
    while index < len(text):
        char = text[index]
        if char == "#" or text[index : index + 2] == "//":
            end = text.find("\n", index)
            end = len(text) if end == -1 else end
            out[index:end] = " " * (end - index)
            index = end
        elif char == '"':
            index += 1
            while index < len(text) and text[index] != '"':
                step = 2 if text[index] == "\\" else 1
                out[index : index + step] = " " * step
                index += step
            index += 1
        else:
            index += 1
    return "".join(out)


def map_entries(body: str) -> dict[str, str]:
    """The quoted keys assigned at the TOP level of a braced map body, with their entry text.

    Depth is tracked rather than lines counted, and that is the whole point. Anchoring to the
    start of a line misses a map written on one line; not anchoring at all reads a key out of a
    nested map — a ``tags`` block inside one entry becomes an entry of its own, and downstream
    that is a Lambda directory nobody can find. Neither is a judgement call once depth is known.

    Args:
      body: A map's braced body, outer braces included.

    Returns:
      Each top-level key mapped to its entry text: the braced body when the value is a block,
      the rest of the line otherwise.

    Raises:
      None.
    """
    entries: dict[str, str] = {}
    depth, index = 0, 0
    while index < len(body):
        char = body[index]
        if char == "#" or body[index : index + 2] == "//":
            end = body.find("\n", index)
            index = len(body) if end == -1 else end
            continue
        if char == '"':
            start = index
            index += 1
            while index < len(body) and body[index] != '"':
                index += 2 if body[index] == "\\" else 1
            index += 1
            key = body[start + 1 : index - 1]
            rest = index
            while rest < len(body) and body[rest] in " \t":
                rest += 1
            if depth == 1 and body[rest : rest + 1] == "=" and body[rest + 1 : rest + 2] != "=":
                value = rest + 1
                while value < len(body) and body[value] in " \t":
                    value += 1
                if body[value : value + 1] == "{":
                    entries[key] = span(body, value)
                else:
                    end = body.find("\n", value)
                    entries[key] = body[value : len(body) if end == -1 else end]
            continue
        depth += {"{": 1, "}": -1}.get(char, 0)
        index += 1
    return entries
