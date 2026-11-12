"""The control planes' deploy grants, read from their map and rendered the way Terraform renders them.

Eight planes share one deploy-role template and differ by the entries of one map in
``infra/modules/base/iam.tf``, so no file on disk IS any plane's policy: a suite that wants a
plane's document has to compose it. This module is the one place that does, because every
suite composing it for itself is the copy that drifts.

The renderer mirrors ``templatefile()`` for exactly the subset the template uses — ``${name}``
interpolation and ``%{ if <bool> ~}`` / ``%{ endif ~}`` — and refuses everything else rather than
approximating it: an escape, a nested or unknown directive, a non-bool condition, a variable the
caller did not supply, or one Terraform would not pass. A renderer that guessed would agree with
Terraform until the one template edit where it did not, and every suite reading through it would
then be measuring a document IAM never sees.

Attributes:
  IAM: The Terraform file holding the map and the resources that render it.
  POLICY_DIR: Where the core and extras templates live.
  CORE: The template every plane renders.
  MAP_LOCAL: The local naming the map of planes.
  VARS_LOCAL: The local naming the variables every template receives.
  BOOL_FIELDS: The map fields the core template branches on.
  VERSION: The policy language version the resource composes every document with.
"""

import json
import pathlib
import re
from dataclasses import dataclass

import tf_blocks

ROOT = pathlib.Path(__file__).resolve().parent.parent
IAM = ROOT / "infra" / "modules" / "base" / "iam.tf"
POLICY_DIR = ROOT / "infra" / "modules" / "base" / "policies"
CORE = POLICY_DIR / "github-actions-deploy-control-plane.json.tftpl"
MAP_LOCAL = "control_plane_grants"
VARS_LOCAL = "control_plane_grant_vars"
BOOL_FIELDS = ("probe", "ceiling")
VERSION = "2012-10-17"
_JSONENCODE_ESCAPES = (
    ("<", "\\u003c"),
    (">", "\\u003e"),
    ("&", "\\u0026"),
    ("\u2028", "\\u2028"),
    ("\u2029", "\\u2029"),
)

_DIRECTIVE = re.compile(r"%\{(~?)\s*(if\s+([A-Za-z_]\w*)|endif)\s*(~?)\}")
_INTERPOLATION = re.compile(r"\$\{([^}]*)\}")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_STRIPPED = re.compile(r"\A[ \t]*(?:\r?\n)?")


@dataclass(frozen=True)
class Grant:
    """One plane's entry in the map, with every field resolved to a literal.

    Attributes:
      slug: The map key: the plane's ``name`` in its root call, and the infix its ARNs scope by.
      name: The policy name after the project prefix.
      description: The policy description.
      sid: The prefix every statement id starts with.
      probe: Whether the plane carries the validate-authorize invoke statement.
      ceiling: Whether the plane carries the TIMED_OUT rule statement.
      extras: The extras template's file name, or None when the plane has none.
    """

    slug: str
    name: str
    description: str
    sid: str
    probe: bool
    ceiling: bool
    extras: str | None


def _local_body(text: str, name: str) -> str:
    """The braced value of one map local in ``iam.tf``.

    Args:
      text: The Terraform source.
      name: The local's name.

    Returns:
      The map's braced body, braces included.

    Raises:
      ValueError: When the local is declared other than exactly once.
    """
    blanked = tf_blocks.strip_noise(text)
    found = list(re.finditer(rf"(?m)^\s*{re.escape(name)}\s*=\s*\{{", blanked))
    if len(found) != 1:
        raise ValueError(f"iam.tf declares `{name} = {{` {len(found)} times, not once")
    return tf_blocks.span(text, found[0].end() - 1)


def _literal(expression: str, where: str) -> str | bool | None:
    """Resolves a map field written as a literal, and refuses anything Terraform would compute.

    Args:
      expression: The field's value expression as written.
      where: The plane and field, for the failure message.

    Returns:
      The string, bool or None the literal denotes.

    Raises:
      ValueError: When the expression is not a plain string, bool or null literal.
    """
    if expression in ("true", "false"):
        return expression == "true"
    if expression == "null":
        return None
    if expression.startswith('"') and expression.endswith('"') and "${" not in expression:
        value = json.loads(expression)
        if isinstance(value, str):
            return value
    raise ValueError(
        f"{where} is `{expression}`, which is not a literal string, bool or null. The suites "
        "read this map as text, so a computed field would be one they cannot resolve."
    )


def grants() -> dict[str, Grant]:
    """Every plane's entry in the map, keyed by slug.

    Args:
      None.

    Returns:
      Each plane's resolved entry.

    Raises:
      ValueError: When the map is missing or empty, or carries a field that is absent or computed.
      TypeError: When a field is a literal of the wrong kind.
    """
    entries = tf_blocks.map_entries(_local_body(IAM.read_text(encoding="utf-8"), MAP_LOCAL))
    if not entries:
        raise ValueError(f"local.{MAP_LOCAL} parsed to no planes")
    result = {}
    for slug, entry in entries.items():
        fields = {
            field: _literal(tf_blocks.argument(entry[1:-1], field), f"{slug}.{field}")
            for field in ("name", "description", "sid", "probe", "ceiling", "extras")
        }
        for field in ("name", "description", "sid"):
            if not isinstance(fields[field], str):
                raise TypeError(f"{slug}.{field} must be a string, not {fields[field]!r}")
        for field in BOOL_FIELDS:
            if not isinstance(fields[field], bool):
                raise TypeError(f"{slug}.{field} must be a bool, not {fields[field]!r}")
        if fields["extras"] is not None and not isinstance(fields["extras"], str):
            raise TypeError(f"{slug}.extras must be a file name or null")
        result[slug] = Grant(slug=slug, **fields)  # type: ignore[arg-type]
    return result


def template_variables() -> tuple[str, ...]:
    """The names every template receives from ``local.control_plane_grant_vars``.

    Args:
      None.

    Returns:
      The variable names, in declaration order.

    Raises:
      ValueError: When the local is missing or empty.
    """
    body = _local_body(IAM.read_text(encoding="utf-8"), VARS_LOCAL)
    names = tuple(re.findall(r"(?m)^\s*([A-Za-z_]\w*)\s*=", tf_blocks.strip_noise(body[1:-1])))
    if not names:
        raise ValueError(f"local.{VARS_LOCAL} parsed to no variables")
    return names


def _substitute(chunk: str, values: dict[str, str | bool]) -> str:
    """Resolves every ``${…}`` in one literal run of a template, as ``templatefile()`` would.

    One run at a time, never the joined output: a ``$`` ending one run and a ``{x}`` starting the
    next are two literals to Terraform, and joining first would invent an interpolation.

    Args:
      chunk: The text between two directives.
      values: Every variable the template receives.

    Returns:
      The run with each interpolation replaced by its value.

    Raises:
      ValueError: When an interpolation is not a plain variable, or is not supplied.
      TypeError: When the variable's value is not a string.
    """

    def resolve(match: re.Match[str]) -> str:
        """Resolves one interpolation.

        Args:
          match: The interpolation.

        Returns:
          The variable's string value.

        Raises:
          ValueError: When the interpolation is not a plain variable, or is not supplied.
          TypeError: When the variable's value is not a string.
        """
        name = match.group(1).strip()
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError(f"`${{{match.group(1)}}}` is not a plain variable")
        if name not in values:
            raise ValueError(f"`${{{name}}}` is not a variable this template receives")
        value = values[name]
        if not isinstance(value, str):
            raise TypeError(f"`${{{name}}}` interpolates {value!r}, not a string")
        return value

    return _INTERPOLATION.sub(resolve, chunk)


def render(text: str, values: dict[str, str | bool]) -> str:
    """Renders a template the way ``templatefile()`` does, for the subset these templates use.

    A trailing ``~}`` strips the spaces and tabs after the directive and at most ONE newline —
    measured against ``templatefile()``, which keeps a second blank line, the next line's
    indentation, and any other control character. A leading ``%{~`` is refused rather than
    modelled, because no template here uses one. Every run is checked for its variables whether
    or not its branch is taken, as ``templatefile()`` checks them before it evaluates anything.

    Args:
      text: The template source.
      values: Every variable the template may read, exactly as Terraform would pass them.

    Returns:
      The rendered text.

    Raises:
      ValueError: When the template carries an escape, a leading strip marker, an unknown or
        nested directive, a condition that is not a bool, or an interpolation that is not a
        plain variable this call supplies.
      TypeError: When an interpolated variable is not a string.
    """
    if "$${" in text or "%%{" in text:
        raise ValueError("the template carries a `$${` or `%%{` escape this renderer does not mirror")
    stray = [token for token in re.findall(r"%\{[^}]*\}", text) if not _DIRECTIVE.fullmatch(token)]
    if stray:
        raise ValueError(f"the template carries directives this renderer does not mirror: {stray}")
    if any(match.group(1) for match in _DIRECTIVE.finditer(text)):
        raise ValueError("the template carries a leading `%{~` strip marker this renderer does not mirror")

    output: list[str] = []
    position = 0
    active: bool | None = None
    strip_next = False
    for match in _DIRECTIVE.finditer(text):
        chunk = _substitute(text[position : match.start()], values)
        if strip_next:
            chunk = _STRIPPED.sub("", chunk, count=1)
        if active is not False:
            output.append(chunk)
        if match.group(3):
            if active is not None:
                raise ValueError("the template nests an `if`, which this renderer does not mirror")
            condition = values.get(match.group(3))
            if not isinstance(condition, bool):
                raise ValueError(f"`%{{ if {match.group(3)} }}` reads {condition!r}, not a bool")
            active = condition
        else:
            if active is None:
                raise ValueError("the template closes an `if` it never opened")
            active = None
        strip_next = bool(match.group(4))
        position = match.end()
    if active is not None:
        raise ValueError("the template leaves an `if` open")
    tail = _substitute(text[position:], values)
    output.append(_STRIPPED.sub("", tail, count=1) if strip_next else tail)
    return "".join(output)


def document(grant: Grant, values: dict[str, str]) -> dict:
    """One plane's policy document, composed the way ``aws_iam_policy.control_plane`` composes it.

    Args:
      grant: The plane's map entry.
      values: A value for every name in ``local.control_plane_grant_vars``; extra keys are
        dropped, because Terraform passes those names and no others.

    Returns:
      The parsed document: the core statements, then the extras'.

    Raises:
      ValueError: When ``values`` lacks a variable the templates receive, or a template does
        not render.
    """
    names = template_variables()
    missing = sorted(set(names) - set(values))
    if missing:
        raise ValueError(f"no value supplied for the template variables {missing}")
    shared: dict[str, str | bool] = {name: values[name] for name in names}
    core = {**shared, "plane": grant.slug, "sid": grant.sid, "probe": grant.probe, "ceiling": grant.ceiling}
    statements = json.loads(render(CORE.read_text(encoding="utf-8"), core))["Statement"]
    if grant.extras is not None:
        extras = POLICY_DIR / grant.extras
        statements = statements + json.loads(render(extras.read_text(encoding="utf-8"), shared))["Statement"]
    return {"Version": VERSION, "Statement": statements}


def documents(values: dict[str, str]) -> dict[str, dict]:
    """Every plane's policy document, keyed by slug.

    Args:
      values: As for ``document``.

    Returns:
      Each plane's parsed document.

    Raises:
      ValueError: As for ``grants`` and ``document``.
    """
    return {slug: document(grant, values) for slug, grant in grants().items()}


def encoded(policy: dict) -> str:
    """A document as ``jsonencode`` writes it, which is the text IAM receives.

    Args:
      policy: A parsed policy document.

    Returns:
      Compact JSON with sorted keys, and the characters Terraform escapes escaped.

    Raises:
      TypeError: When the document carries a float, which ``jsonencode`` writes differently.
    """
    _refuse_floats(policy)
    text = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    for character, escape in _JSONENCODE_ESCAPES:
        text = text.replace(character, escape)
    return text


def _refuse_floats(node: object) -> None:
    """Refuses a number ``json.dumps`` would write differently from ``jsonencode``.

    ``jsonencode`` writes an integral number without a fraction (``1``, not ``1.0``); no policy
    here carries a number at all, so one arriving is refused rather than rendered.

    Args:
      node: A parsed document, or any part of one.

    Returns:
      None.

    Raises:
      TypeError: When the document carries a float.
    """
    if isinstance(node, float):
        raise TypeError(f"the document carries the number {node!r}, which jsonencode writes differently")
    if isinstance(node, dict):
        for value in node.values():
            _refuse_floats(value)
    if isinstance(node, list):
        for value in node:
            _refuse_floats(value)


def template_paths() -> frozenset[pathlib.Path]:
    """The template files the plane documents are rendered from: the core and every extras.

    Suites that sweep the policy directory measure these THROUGH the documents, never as files
    of their own — the core does not parse until rendered, and an extras file is a fragment of a
    plane's policy rather than a policy.

    Args:
      None.

    Returns:
      The core template and each extras template the map names.

    Raises:
      ValueError: As for ``grants``.
    """
    return frozenset({CORE} | {POLICY_DIR / g.extras for g in grants().values() if g.extras})
