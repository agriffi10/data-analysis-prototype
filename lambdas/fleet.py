"""Derives the Lambda fleet's membership from the Terraform that declares it.

**This is the replacement for `.github/lambda-functions.json`, and its independence is the
point.** The image's own sweep decides "is this a Lambda" by looking for a module defining a
top-level ``handler``; `lambdas/docker/assemble.py` uses the same rule to lay the task root out.
Computing the fleet's expected size the same way would put one derivation on both sides of every
comparison — measured, and it happened: renaming a function's ``handler`` once removed it from
both sides at once, the two numbers agreed at 85, and a planted mutation that broke a function's
entry point passed the whole matrix. So the expectation comes from Terraform, which is maintained
separately and still says 86.

**It reads the SOURCES, not `tofu output`, and both readers exist for different reasons.**
`deploy-lambdas.yml` needs the fleet as the commit declares it, because a `tofu output` is
last-applied state and the two deploy workflows fire on the same push with no ordering between
them — a commit that adds a function would deploy over state that predates it, never point the new
function, and reconcile cleanly over the gap. `.github/workflows/lambda-image.yml` needs it with no
AWS credentials at all, which it deliberately has none of.

**An unrecognised expression RAISES.** The three shapes below are what the fleet is written in
today; a fourth one silently skipped would shrink the fleet, and a shrunk fleet passes every
comparison that derives both sides from here.

Attributes:
  MODULE_SOURCE: The module path every fleet function is a call to.
  NAME_PREFIX: The interpolation every deployed name starts with. CI builds a function's real
    name as ``${PROJECT_NAME}-${ENVIRONMENT}-${NAME}``, so the short name this module returns is
    whatever follows it. A template that does not carry it is refused rather than returned
    unchanged, which is what `trimprefix` would silently do.
"""

import argparse
import json
import pathlib
import re

from tf_blocks import argument, map_entries, module_calls, span

MODULE_SOURCE = "docker-lambda"
NAME_PREFIX = "${var.project_name}-${var.environment}-"


class FleetError(Exception):
    """A function declaration this module cannot resolve.

    Raised rather than skipped: every consumer compares a count or a set against this answer, so a
    declaration quietly dropped here shrinks both sides of the comparison at once.
    """


def _bare_keys(body: str) -> list[str]:
    """The map keys written as bare identifiers rather than as quoted strings.

    HCL accepts both, and the quoted-key reader these verbs are resolved through sees only quoted
    ones — so a bare key is a verb that is absent from the fleet while every count derived from
    the fleet agrees with the shortfall.

    **This DETECTS rather than counts, and the difference was measured.** The first version
    compared the quoted-key count against a count of assignments, and was wrong in both
    directions: it updated its depth AFTER testing the line, so a key sharing the opening brace's
    line — ``verbs = {{ bare = 3`` — was invisible to both counts at once and the guard agreed
    with the shortfall it exists to catch; and it counted a legal one-line map as a disagreement
    and refused it. Both forms pass ``tofu fmt`` unchanged, so nothing else would have caught
    either.

    The walk mirrors the quoted-key reader's: depth tracked over braces, strings skipped whole,
    comments skipped to end of line. A key is an identifier appearing where an entry may START —
    after the opening brace, a comma or a newline — and followed by a single ``=``.

    Args:
      body: A map's braced body, outer braces included.

    Returns:
      The bare keys, in the order they appear.

    Raises:
      None.
    """
    found: list[str] = []
    depth, index, at_entry_start = 0, 0, False
    while index < len(body):
        char = body[index]
        if char == "#" or body[index : index + 2] == "//":
            end_of_line = body.find("\n", index)
            index = len(body) if end_of_line == -1 else end_of_line
            continue
        if char == '"':
            index += 1
            while index < len(body) and body[index] != '"':
                index += 2 if body[index] == "\\" else 1
            index += 1
            at_entry_start = False
            continue
        if char in "{}":
            depth += 1 if char == "{" else -1
            at_entry_start = char == "{"
            index += 1
            continue
        if char in ",\n":
            at_entry_start = True
            index += 1
            continue
        if char in " \t":
            index += 1
            continue
        if depth == 1 and at_entry_start and (char.isalpha() or char == "_"):
            match = re.match(r"([A-Za-z_][A-Za-z0-9_-]*)[ \t]*=(?!=)", body[index:])
            if match:
                found.append(match.group(1))
                index += match.end()
                at_entry_start = False
                continue
        at_entry_start = False
        index += 1
    return found


def _is_fleet_module(source: str) -> bool:
    """Reports whether a module call's ``source`` is the fleet's function module.

    An exact path-segment match rather than a suffix test. ``endswith`` accepted
    ``"../not-docker-lambda"`` and rejected ``"../docker-lambda/"`` — a legal trailing slash that
    silently dropped an entire plane's verbs, and the shortfall then surfaced as an assembler
    disagreement blaming the wrong side.

    Args:
      source: The ``source`` argument as written, quotes included.

    Returns:
      True when the path's final segment is the fleet module.

    Raises:
      None.
    """
    return source.strip('"').rstrip("/").rsplit("/", 1)[-1] == MODULE_SOURCE


def _locals_bodies(module: pathlib.Path) -> list[str]:
    """The INNER body of every ``locals`` block in one Terraform module.

    Read from all the module's files rather than from ``locals.tf`` alone, because a module may
    declare a local beside the resource that uses it — `api` and `auth` both do. Restricted to
    ``locals`` blocks because a plain search of the module's text finds
    ``function_name = aws_lambda_function.drain.function_name`` in a resource and resolves the
    local to a self-reference.

    The bodies are kept SEPARATE and their outer braces stripped, which is what lets the caller
    read an entry with the shared argument scanner: that scanner works at depth zero, and a
    concatenation of braced blocks puts every entry one level down where it matches nothing.

    Args:
      module: The module directory.

    Returns:
      One brace-stripped body per locals block, in file order.

    Raises:
      None.
    """
    found = []
    for path in sorted(module.glob("*.tf")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^locals\s*\{", text, re.MULTILINE):
            body = span(text, match.start())
            found.append(body[body.index("{") + 1 : body.rindex("}")])
    return found


def _local_value(bodies: list[str], name: str, where: str) -> str:
    """The expression one ``locals`` entry is assigned.

    Args:
      bodies: The module's locals bodies, from ``_locals_bodies``.
      name: The local's name.
      where: The module being read, so a failure names it.

    Returns:
      The value expression as written.

    Raises:
      FleetError: When the local is not declared — a renamed local otherwise resolves to nothing
        and drops its functions from the fleet.
    """
    for body in bodies:
        try:
            return argument(body, name)
        except ValueError:
            continue
    raise FleetError(f"{where}: no local named `{name}`")


def _short_name(template: str, where: str) -> str:
    """The suffix of a deployed-name template, which is the function's short name.

    The quoting is not re-checked here. The comprehension branch passes a group its pattern
    captured with the quotes on, and the inline branch is reached only for an expression starting
    with one — an expression starting with anything else is refused earlier, by name, as a shape
    this module does not resolve. A guard for it was written and then removed: no corpus case
    could reach it, and a refusal that nothing can fire reads as coverage while providing none.
    The narrower claim is the honest one — the leading quote is guaranteed, the trailing one is
    inferred from HCL being parseable at all.

    Args:
      template: A quoted Terraform string, interpolations included.
      where: The module being read, so a failure names it.

    Returns:
      The name with the project/environment prefix removed.

    Raises:
      FleetError: When the template does not carry the deployed-name prefix. A refusal rather than
        a best-effort answer: CI reconstructs the deployed name by prepending that exact prefix,
        so a name derived without it would point at a function that does not exist. A residual
        interpolation is caught on the FINISHED name instead, because a per-verb template
        legitimately carries its loop variable at this point.
    """
    literal = template.strip()[1:-1]
    if not literal.startswith(NAME_PREFIX):
        raise FleetError(
            f"{where}: {literal!r} does not start with {NAME_PREFIX!r}. CI builds every function's "
            "real name by prepending exactly that, so a name derived without it would point at a "
            "function that does not exist."
        )
    return literal[len(NAME_PREFIX) :]


def _resolve(expression: str, bodies: list[str], where: str, for_each: str | None) -> list[str]:
    """The short names one ``function_name`` argument resolves to.

    Three shapes, which is what the fleet is written in:

    * a quoted template written inline (`api`);
    * ``local.<name>``, a scalar template (the six singletons and `shared-spaces`' reader);
    * ``local.<map>[each.key]``, a ``for`` comprehension over a sibling map local, which is how
      every plane declares its verbs.

    Args:
      expression: The argument's value expression.
      bodies: The module's locals bodies.
      where: The module being read, so a failure names it.

    Returns:
      Every short name the expression declares, sorted.

    Raises:
      FleetError: On any other shape. A fourth spelling silently skipped would shrink the fleet.
    """
    expression = expression.strip()

    if expression.startswith('"'):
        return [_short_name(expression, where)]

    indexed = re.fullmatch(r"local\.([A-Za-z0-9_]+)\[each\.key\]", expression)
    if indexed:
        return sorted(_resolve_map(indexed.group(1), bodies, where, for_each))

    scalar = re.fullmatch(r"local\.([A-Za-z0-9_]+)", expression)
    if scalar:
        return _resolve(_local_value(bodies, scalar.group(1), where), bodies, where, for_each)

    raise FleetError(
        f"{where}: cannot resolve `function_name = {expression}`. This module understands an inline "
        "template, `local.<name>` and `local.<map>[each.key]`; a new spelling must be added here "
        "rather than skipped, because a skipped declaration shrinks the fleet on both sides of "
        "every comparison built on it."
    )


def _resolve_map(name: str, bodies: list[str], where: str, for_each: str | None) -> set[str]:
    """The short names a per-verb name map declares.

    The map is a comprehension — ``{ for suffix, _ in local.<verbs> : suffix => "<template>" }`` —
    so the keys come from the map it iterates and the template supplies the rest. The loop
    variable is read from the comprehension rather than assumed to be ``suffix``.

    Args:
      name: The name-map local.
      bodies: The module's locals bodies.
      where: The module being read, so a failure names it.

    Returns:
      Every short name in the map.

    Raises:
      FleetError: When the comprehension is not the expected shape, or its source map is empty —
        an empty source map yields an empty fleet for that plane, which every count comparison
        would then agree with.
    """
    body = _local_value(bodies, name, where)
    comprehension = re.search(
        r"\{\s*for\s+([A-Za-z0-9_]+)\s*,\s*[A-Za-z0-9_]+\s+in\s+local\.([A-Za-z0-9_]+)\s*:"
        r"\s*[A-Za-z0-9_]+\s*=>\s*(\"[^\"]*\")",
        body,
    )
    if not comprehension:
        raise FleetError(f"{where}: `{name}` is not a `for … in local.<map> : k => \"…\"` map")
    variable, source, template = comprehension.groups()

    if for_each is not None and for_each.strip() != f"local.{source}":
        raise FleetError(
            f"{where}: `function_name` indexes `{name}`, built from `local.{source}`, but "
            f"`for_each = {for_each.strip()}`. Only the instances `for_each` creates exist, so a "
            "gated or filtered expression here means this module names functions Terraform never "
            "deployed — an OVER-count, which the assembler agrees with (the source directory is "
            "still there) and which CI discovers by waiting five minutes per name."
        )

    body_of_source = _local_value(bodies, source, where)
    keys = map_entries(span(body_of_source, 0))
    if not keys:
        raise FleetError(
            f"{where}: `{source}` names no verbs, so `{name}` would contribute no functions and "
            "every count derived from it would agree with the shortfall."
        )
    bare = _bare_keys(span(body_of_source, 0))
    if bare:
        raise FleetError(
            f"{where}: `{source}` writes {', '.join(bare)} as bare identifier key(s). HCL accepts "
            "that and the reader here sees only quoted keys, so each one is a verb Terraform "
            "deploys and this derivation never names — absent from the fleet, never pointed, "
            "running an older image and working perfectly. Quote them."
        )

    stem = _short_name(template, where)
    placeholder = "${" + variable + "}"
    if placeholder not in stem:
        raise FleetError(f"{where}: `{name}`'s template does not interpolate `{variable}`")
    return {stem.replace(placeholder, key) for key in keys}


def function_names(repo: pathlib.Path) -> list[str]:
    """Every Lambda in the fleet, as the short name CI and the source tree both use.

    Args:
      repo: The repository root.

    Returns:
      The short names, sorted and unique.

    Raises:
      FleetError: When a declaration cannot be resolved, when two declarations collide, or when
        the sweep finds implausibly few — a sweep that has stopped working reports an empty fleet,
        and an empty fleet passes every set comparison against another empty one.
    """
    found: dict[str, str] = {}
    for module in sorted((repo / "infra" / "modules").iterdir()):
        if not module.is_dir():
            continue
        bodies = _locals_bodies(module)
        for path in sorted(module.glob("*.tf")):
            for call, inner in module_calls(path.read_text(encoding="utf-8")).items():
                try:
                    source = argument(inner, "source")
                except ValueError:
                    continue
                if not _is_fleet_module(source):
                    continue
                where = f"{module.name}/{path.name} module.{call}"
                try:
                    for_each: str | None = argument(inner, "for_each")
                except ValueError:
                    for_each = None
                for name in _resolve(argument(inner, "function_name"), bodies, where, for_each):
                    if "${" in name:
                        raise FleetError(
                            f"{where}: resolves to {name!r}, which still carries an unresolved "
                            "interpolation. Only the project and environment are resolved here, so "
                            "a name built from any other reference comes back with the reference "
                            "still in it and is pointed at a function that cannot exist."
                        )
                    if name in found:
                        raise FleetError(f"{where} and {found[name]} both declare `{name}`")
                    found[name] = where
    if len(found) < 30:
        raise FleetError(
            f"only {len(found)} functions found in infra/modules — the Terraform sweep has stopped "
            "working, and every comparison against this answer would pass vacuously."
        )
    return sorted(found)


def main() -> int:
    """Prints the fleet as JSON, for the shell callers that cannot import it.

    Args:
      None.

    Returns:
      0.

    Raises:
      FleetError: Propagated, so a broken derivation fails its caller rather than printing an
        empty list that reads as a clean sweep.
    """
    parser = argparse.ArgumentParser(description="Print the Lambda fleet's short names as JSON.")
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path(__file__).parent.parent)
    parser.add_argument(
        "--rows",
        action="store_true",
        help='Print [{"name": …}] rows, the shape the plan guard reads.',
    )
    arguments = parser.parse_args()
    names = function_names(arguments.repo)
    print(json.dumps([{"name": n} for n in names] if arguments.rows else names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
