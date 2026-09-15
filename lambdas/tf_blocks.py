"""Reads Terraform source as text, for the infrastructure suites that assert over it.

Every assertion built on this is a TEXT assertion: it can prove what the configuration says
and never what AWS applied. The live checks own the second half.

Extracted when the second consumer arrived rather than copied into it — a brace counter that
skips strings and comments is exactly the kind of helper whose two copies drift apart in the
one case that matters.

Attributes:
  LAMBDA_INPUT_SPELLINGS: What one function setting is called under each packaging, module
    spelling first. The pairs live here rather than at the call sites because more than one suite
    reads the same pair, and a rule written twice is wrong in one copy.
"""

import re


def _declarations(text: str, blanked: str, original: str) -> dict[str, str]:
    """Every top-level block whose header matches, keyed by the labels ``original`` captures.

    **Located over ``strip_noise`` and sliced from the original**, and that is not fastidiousness:
    a commented-out ``module "x" { … }`` is an ordinary Terraform idiom, and a bare scan reads it
    as a declaration whose body then swallows the rest of the file. Measured on the one-line form:
    a commented `module "api" { … }` placed after the real declaration shadowed it and returned a
    number Terraform does not deploy.

    Two patterns rather than one, because ``strip_noise`` blanks string BODIES: on its output a
    header is only recognisable by its shape, so ``blanked`` finds the offsets and ``original``
    re-reads the header there to filter by type and capture the name.

    Args:
      text: The Terraform source to read.
      blanked: A shape regex that matches a header in noise-blanked source, ending just after the
        opening brace.
      original: The same header with its literals spelled out, its groups the labels that name the
        block: the local name alone, or a data source's type and name.

    Returns:
      Each block's labels, joined by a dot, mapped to its body, braces excluded.

    Raises:
      None.
    """
    found = {}
    for match in re.finditer(blanked, strip_noise(text)):
        header = re.match(original, text[match.start() : match.end()])
        if header is None:
            continue
        found[".".join(header.groups())] = text[match.end() : _close(text, match.end()) - 1]
    return found


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
    return _declarations(
        text,
        r'(?<![\w-])resource\s+"[^"]*"\s+"[^"]*"\s*\{',
        rf'(?<![\w-])resource\s+"{re.escape(kind)}"\s+"([^"]+)"\s*\{{',
    )


def output_blocks(text: str) -> dict[str, str]:
    """Splits Terraform source into top-level ``output`` blocks, keyed by output name.

    The third kind of named declaration these suites read, and it goes through the same scanner
    as the other two rather than being regexed at its call site. The reason is worth stating,
    because the call-site version was written first and was wrong: ``strip_noise`` blanks string
    BODIES, so a pattern capturing ``"([^"]+)"`` over its output captures spaces and every block
    comes back keyed by whitespace. The offsets come from the blanked text and the NAME is re-read
    from the original, which is the split ``_declarations`` exists to hold.

    Args:
      text: The Terraform source to read.

    Returns:
      Each output's name mapped to its body.

    Raises:
      None.
    """
    return _declarations(
        text,
        r'(?<![\w-])output\s+"[^"]*"\s*\{',
        r'(?<![\w-])output\s+"([^"]+)"\s*\{',
    )


def module_calls(text: str) -> dict[str, str]:
    """Splits Terraform source into top-level ``module`` blocks, keyed by call name.

    The counterpart to ``blocks`` for the other kind of declaration a fleet function can have. It
    goes through the same header scan and the same brace counter for the same reason: a module
    call's body nests, and a second scanner written beside a suite is the copy that drifts.

    Args:
      text: The Terraform source to read.

    Returns:
      Each module call's local name mapped to its body.

    Raises:
      None.
    """
    return _declarations(
        text,
        r'(?<![\w-])module\s+"[^"]*"\s*\{',
        r'(?<![\w-])module\s+"([^"]+)"\s*\{',
    )


def data_sources(text: str) -> dict[str, str]:
    """Splits Terraform source into top-level ``data`` blocks, keyed ``<type>.<name>``.

    Keyed by both labels because a data source's local name is unique only within its type, so a
    key of the name alone would let ``aws_region.current`` overwrite ``aws_caller_identity.current``
    and report one where there are two.

    Args:
      text: The Terraform source to read.

    Returns:
      Each data source's ``type.name`` mapped to its body.

    Raises:
      None.
    """
    return _declarations(
        text,
        r'(?<![\w-])data\s+"[^"]*"\s+"[^"]*"\s*\{',
        r'(?<![\w-])data\s+"([^"]+)"\s+"([^"]+)"\s*\{',
    )


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


def join_list_items(text: str, local_name: str) -> tuple[str, tuple[str, ...]]:
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


def strip_comments(text: str) -> str:
    """Blanks comments ONLY, preserving length and every other character — strings included.

    The counterpart to ``strip_noise`` for a scan whose subject IS a string literal. A
    constructed ARN, a resource name, a log-group path: every one of those lives inside quotes,
    and ``strip_noise`` blanks exactly that, so a sweep for one over its output finds nothing and
    reports the tree clean. Measured: a sweep for ``arn:aws:lambda:`` over stripped source found
    zero occurrences in a module that had one.

    Comments still have to go, for ``strip_noise``'s own reason: a comment explaining why a
    pattern is forbidden reads, to a bare regex, exactly like the file doing it.

    Args:
      text: The Terraform fragment to blank.

    Returns:
      The fragment, same length, with comment bodies replaced by spaces.

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
                index += 2 if text[index] == "\\" else 1
            index += 1
        else:
            index += 1
    return "".join(out)


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


_OPENERS = {"{": 1, "[": 1, "(": 1}
_CLOSERS = {"}": 1, "]": 1, ")": 1}


def _depths(text: str) -> list[int]:
    """The delimiter depth immediately BEFORE each character.

    Args:
      text: Noise-blanked Terraform source.

    Returns:
      One depth per character.

    Raises:
      None.
    """
    depths, depth = [], 0
    for char in text:
        depths.append(depth)
        depth += _OPENERS.get(char, 0)
        depth -= _CLOSERS.get(char, 0)
    return depths


def argument(body: str, name: str) -> str:
    """The value expression assigned to ``name`` at the TOP LEVEL of a block body.

    The counterpart to ``span`` for a value that is not a braced block. ``span`` returns the first
    braced run it finds, which truncates ``merge({…}, lookup(…))`` at the first map and drops the
    override the caller was looking for — a slice that looks exhaustive while measuring less.

    **Scanned over ``strip_noise``, and that is the whole reason this is not a bare delimiter
    count.** Measured: a ``#`` comment carrying one unmatched ``}`` makes a raw count end the value
    early and swallow the argument after it, and a string containing ``}`` truncates it. Both blank
    to spaces here, and because ``strip_noise`` preserves length the offsets still point into the
    original, which is what is sliced.

    Args:
      body: A block's body, outer braces excluded — so its own arguments sit at depth zero.
      name: The argument's name.

    Returns:
      The value expression, whitespace-trimmed, exactly as written in ``body``.

    Raises:
      ValueError: If ``name`` is not assigned at the top level, rather than an empty string that
        every caller would compare against and pass.
    """
    scan = strip_noise(body)
    depths = _depths(scan)
    pattern = re.compile(rf"(?m)^[ \t]*{re.escape(name)}[ \t]*=(?!=)")

    for match in pattern.finditer(scan):
        if depths[match.start()] != 0:
            continue
        index = match.end()
        while index < len(scan) and scan[index] in " \t":
            index += 1
        start, depth = index, 0
        while index < len(scan):
            char = scan[index]
            if char == "\n" and depth == 0:
                break
            depth += _OPENERS.get(char, 0)
            depth -= _CLOSERS.get(char, 0)
            index += 1
        # Trimmed against the BLANKED text, which is what keeps a trailing `# …` out of the
        # value: the comment is spaces there, so rstrip finds the value's real last character,
        # and the same offset in the original ends the slice before the comment begins.
        return body[start : start + len(scan[start:index].rstrip())].strip()

    raise ValueError(f"no top-level `{name} = …` in this block")


def lambda_declaration(text: str, name: str) -> str:
    """The body of one fleet function's declaration, whichever way it is declared.

    Today every deployed function is an ``aws_lambda_function`` resource; the container packaging
    declares one as a ``module`` call instead. Both arms exist so a suite that pins a Python
    constant to a deployed number does not have to be rewritten twice — once to move to the new
    shape and once when the old one goes. The resource arm is deleted when nothing in ``infra/``
    declares such a resource outside the container module itself.

    The module arm is tried FIRST, so during the window where a plane has moved and its
    neighbours have not, the shape the plane actually deploys wins.

    Args:
      text: One module's Terraform source.
      name: The declaration's local name.

    Returns:
      The declaration's body.

    Raises:
      ValueError: If nothing of that name is declared, so a suite cannot silently assert over an
        empty string.
    """
    calls = module_calls(text)
    if name in calls:
        return calls[name]
    resources = blocks(text, "aws_lambda_function")
    if name in resources:
        return resources[name]
    raise ValueError(f"no module call or aws_lambda_function named {name!r}")


def lambda_environment(body: str) -> str:
    """One function declaration's environment, whichever shape it has.

    A resource nests a block (``environment { variables = {…} }``); a module call assigns a map
    (``environment = merge({…}, lookup(…))``). Both come back as text, because every caller wants
    the same thing out of them: the names assigned inside.

    Args:
      body: A declaration body from ``lambda_declaration``.

    Returns:
      The environment's text.

    Raises:
      ValueError: If the declaration carries no environment at all.
    """
    try:
        return argument(body, "environment")
    except ValueError:
        opening = re.search(r"(?m)^\s*environment\s*\{", body)
        if not opening:
            raise ValueError("the declaration sets no environment") from None
        return span(body, opening.start())


LAMBDA_INPUT_SPELLINGS = {
    "timeout": ("timeout_seconds", "timeout"),
    "memory": ("memory_mb", "memory_size"),
    "role": ("role_arn", "role"),
}


def lambda_input(body: str, setting: str) -> str:
    """One function's declared timeout, memory or role, under whichever name it carries.

    The two packagings spell these differently — ``timeout``/``memory_size``/``role`` on the
    resource, ``timeout_seconds``/``memory_mb``/``role_arn`` on the module's inputs — and a suite
    pinning a Python constant to the deployed value cares about the value, not the spelling.

    Args:
      body: A declaration body from ``lambda_declaration``.
      setting: A key of ``LAMBDA_INPUT_SPELLINGS``.

    Returns:
      The value expression, often a literal a caller will ``int()``.

    Raises:
      ValueError: On an unknown setting, or when the declaration uses neither spelling.
    """
    if setting not in LAMBDA_INPUT_SPELLINGS:
        raise ValueError(f"unknown setting {setting!r}")
    for spelling in LAMBDA_INPUT_SPELLINGS[setting]:
        try:
            return argument(body, spelling)
        except ValueError:
            continue
    raise ValueError(f"the declaration sets no {setting}")
