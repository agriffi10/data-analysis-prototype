"""Every deployed function's Terraform environment must satisfy what its own code can demand.

``cpcommon.config`` resolves its required variables on FIRST ACCESS, not at import. A name
absent from a function's ``environment`` block therefore raises ``RuntimeError`` in production,
on whichever branch happens to read it, and nothing else in this repository can see it: ``tofu
apply`` is green against a thin environment, ``update-function-code`` is green against it, and
the whole pytest suite is green because ``lambdas/conftest.py`` stamps every variable before
collection. Two functions were already checked one at a time — the API's front door against a
hand-kept copy of the set, and the directory builder against the declaration itself — and the
other eighty-four were not. This reads the deployed Terraform and joins it against the code.

**The demand is COMPUTED per function, never assumed to be the whole set.** A blanket "every
plane sets all four" would be false in both directions. It is too weak for the API, whose own
config module requires the same names through a different map; and it is too strong for the
planes that legitimately set three — archive, file-ops and file-send reach no Athena workgroup
on any branch, and their Terraform omitting it is correct rather than drift. So each function's
demand is the set of required names its import closure can actually reach through a fail-fast
reader, walked from its own modules through exactly the layers the deployment manifest attaches
to it. What a function cannot reach, it cannot be broken by.

**That computation is also what replaces an exemption list.** Four functions — the ones
``test_layer_import_safety`` calls the singletons — attach the shared layer for its logging and a
short allowlist beside it, and set almost none of the required set on purpose. A hand-written
exception naming them would be a hidden coupling: it would go on passing after one of them grew a
read that made the exemption false. Here they are exempt only because the scan finds they demand
nothing, and a test below pins that the two agree — so the exemption cannot outlive its reason.

The guard is a SUPERSET, not set equality. Several planes deliberately set the layer's whole
union so a verb that grows a read does not need a Terraform change to go with it. That leaves one blind spot, which a second assertion below covers: a name added
to ``_REQUIRED_VARS`` that nothing reads YET is demanded by no function, so the reachability
comparison stays green while the fleet contract has silently widened. The declaration is
therefore pinned separately. ``user-directory-build`` keeps a stricter per-plane mirror beside
its verb tests, which catches the same widening from the other side; both were kept after
checking that adding a variable reddens each of them.

Attributes:
  ROOT: The repository root.
  LAMBDAS: The Lambda source tree, and the import root for the layers.
  MODULES: The Terraform module tree holding one lambda.tf per plane.
  FUNCTION_MANIFEST: The deploy manifest naming every function and the layers it attaches.
  LAYER_MANIFEST: The layer manifest, which says where each layer's importable code lives.
  NAME_PREFIX: The project/environment prefix every deployed function name carries. Stripping it
    yields the ``lambdas/`` directory, which is the contract the deploy matrix already rests on.
  FAIL_FAST_READERS: The canonical spellings of the shared fail-fast reader. A module's own
    aliases for it are resolved per module, because a domain layer imports it under a third name.
  DEPLOYED: Every function name in the deploy manifest, sorted, and the parametrisation of the
    guard below — so a function added to the fleet is covered by having been deployed.
"""

import ast
import functools
import json
import pathlib
import re

import pytest
from cpcommon import config
from tf_blocks import blocks, map_entries, span, strip_noise

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
MODULES = ROOT / "infra" / "modules"
FUNCTION_MANIFEST = ROOT / ".github" / "lambda-functions.json"
LAYER_MANIFEST = ROOT / ".github" / "lambda-layers.json"

NAME_PREFIX = "${var.project_name}-${var.environment}-"
FAIL_FAST_READERS = ("require", "_require")


def _required_names() -> frozenset[str]:
    """The fleet-wide required set, read live from the module that declares it.

    Read rather than transcribed: a copy could not see the declaration gaining a name, which is
    the drift this file exists to catch.

    Args:
      None.

    Returns:
      The environment variable names ``cpcommon.config`` requires.

    Raises:
      None.
    """
    return frozenset(config._REQUIRED_VARS.values())


def _locals_source(module: pathlib.Path) -> str:
    """Every ``locals`` block in one Terraform module, concatenated.

    Read from all of the module's files rather than from locals.tf alone, because a module may
    declare a local beside the resource that uses it. Restricted to locals blocks for the reason
    the first draft of this was wrong: a plain search of the module's text found
    ``function_name = aws_lambda_function.drain.function_name`` in lambda.tf and resolved the
    local to a self-reference.

    Args:
      module: The module directory.

    Returns:
      The concatenated locals blocks.

    Raises:
      None.
    """
    found = []
    for path in sorted(module.glob("*.tf")):
        text = path.read_text(encoding="utf-8")
        found.extend(
            span(text, match.start())
            for match in re.finditer(r"^locals\s*\{", text, re.MULTILINE)
        )
    return "\n".join(found)


def _assigned(body: str) -> set[str]:
    """The upper-case names assigned anywhere in one Terraform fragment.

    Comments and string contents are blanked first. Without that a comment mentioning a variable
    reads as the block setting it, which on the shadow check below produces a failure sentence
    accusing an override of replacing a name it never mentions — and this tree comments heavily
    inside exactly these blocks.

    Not depth-restricted, deliberately: the merge form nests the variables one level inside
    ``merge({…})``, and the only assignments in either form are the variables themselves.

    Args:
      body: The fragment to scan.

    Returns:
      The names assigned in it.

    Raises:
      None.
    """
    return set(re.findall(r"([A-Z][A-Z0-9_]*)\s*=(?!=)", strip_noise(body)))


def _map_entries(source: str, name: str) -> dict[str, str]:
    """The quoted keys of a Terraform map local, mapped to their entry bodies.

    Read to the map's own closing brace by counting braces, never to the first brace after a
    named entry. That earlier shape is what let a plane's last-declared verbs sit outside a
    guard that looked exhaustive.

    Locating the local is all this does; the entries themselves are read by the shared scanner,
    which tracks depth. Two regexes were tried here first and both were wrong in opposite
    directions — one anchored to the line start and could not see a single-line map, the other
    read a nested map's keys as though they were entries of this one.

    Args:
      source: The concatenated locals source.
      name: The local's name.

    Returns:
      Each key mapped to the text of its entry, empty if the local is not found.

    Raises:
      None.
    """
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*\{{", source, re.MULTILINE)
    if not match:
        return {}
    return map_entries(span(source, match.start()))


def _directories(function_name: str, source: str, where: str) -> list[tuple[str, str]]:
    """The ``lambdas/`` directories one Terraform resource deploys.

    The deployed name is ``<project>-<environment>-<suffix>`` and the suffix IS the source
    directory — the same contract the deploy matrix rests on — so the mapping is derived here
    rather than hand-kept. A hand-kept one would silently stop covering a function the day a
    plane gained a verb.

    Args:
      function_name: The resource's ``function_name`` expression.
      source: The module's concatenated locals source.
      where: The module being read, so a failure names it. Without it a renamed local surfaces
        as eighty-odd identical errors citing a local and no file.

    Returns:
      One ``(directory, key)`` pair per function the resource deploys. The key is the ``each.key``
      the name was built from, empty for a singleton — carried out rather than recovered later,
      because recovering it by splitting the directory is wrong for every hyphenated plane.

    Raises:
      ValueError: If the expression names a local this cannot resolve, rather than resolving to
        an empty list that every assertion would then pass over.
    """
    if function_name.startswith('"'):
        return [(function_name.strip('"').replace(NAME_PREFIX, ""), "")]

    keyed = re.match(r"local\.([a-z_]+)\[each\.key\]", function_name)
    if keyed:
        names = re.search(rf"^\s*{keyed.group(1)}\s*=\s*\{{", source, re.MULTILINE)
        if not names:
            raise ValueError(f"{where}: cannot resolve local.{keyed.group(1)}")
        body = span(source, names.start())
        over = re.search(r"for\s+\w+,\s*\w+\s+in\s+local\.([a-z_]+)", body)
        template = re.search(r'=>\s*"([^"]+)"', body)
        if not over or not template:
            raise ValueError(f"{where}: local.{keyed.group(1)} is not a name comprehension")
        stem = template.group(1).replace(NAME_PREFIX, "")
        return sorted(
            (re.sub(r"\$\{\w+\}", key, stem), key) for key in _map_entries(source, over.group(1))
        )

    plain = re.match(r"local\.([a-z_]+)$", function_name)
    if not plain:
        raise ValueError(f"{where}: unrecognised function_name expression: {function_name!r}")
    literal = re.search(rf'^\s*{plain.group(1)}\s*=\s*"([^"]+)"', source, re.MULTILINE)
    if not literal:
        raise ValueError(f"{where}: cannot resolve local.{plain.group(1)}")
    return [(literal.group(1).replace(NAME_PREFIX, ""), "")]


@functools.lru_cache(maxsize=1)
def _resources() -> tuple[tuple[str, str, tuple[tuple[str, str], ...], frozenset[str], str], ...]:
    """Every ``aws_lambda_function`` in the module tree, with what its environment supplies.

    Args:
      None.

    Returns:
      One row per resource: its module, its resource name, the ``(directory, key)`` pairs it
      deploys, the variable names its base environment block sets, and the name of its per-verb
      override local, empty when it has none.

    Raises:
      ValueError: Through ``_directories``, if a resource's name cannot be resolved.
    """
    rows = []
    for path in sorted(MODULES.glob("*/lambda.tf")):
        source = _locals_source(path.parent)
        for name, body in blocks(path.read_text(encoding="utf-8"), "aws_lambda_function").items():
            expression = re.search(r"^\s{2}function_name\s*=\s*(.+)$", body, re.MULTILINE)
            assert expression, f"{path}: {name} declares no function_name"
            opening = re.search(r"^\s{2}environment\s*\{", body, re.MULTILINE)
            assert opening, f"{path}: {name} declares no environment block"
            environment = span(body, opening.start())
            override = re.search(r"lookup\(local\.([a-z_]+),", environment)
            rows.append(
                (
                    path.parent.name,
                    name,
                    tuple(_directories(expression.group(1).strip(), source, str(path))),
                    frozenset(_assigned(environment)),
                    override.group(1) if override else "",
                )
            )
    return tuple(rows)


@functools.lru_cache(maxsize=1)
def _supply() -> dict[str, tuple[str, frozenset[str]]]:
    """Each function directory mapped to the resource that deploys it and what it is given.

    A per-verb override entry is unioned in, because an override that ADDS a variable supplies
    it as genuinely as the base block does. For a REQUIRED name that union is currently
    unreachable, and deliberately so: the shadow check below refuses any required name in an
    override map at all, on the grounds that an override is where one silently becomes an empty
    string. The union is kept anyway so that what this function reports is what Terraform
    actually merges, rather than what a second test happens to forbid — the two would otherwise
    have to be read together to know whether either was right.

    The override is looked up by the key the DIRECTORY WAS BUILT FROM, never by splitting the
    directory name back apart. A plane whose name contains a hyphen — five of the six that have
    an override map — makes ``file-ops-copy-objects`` split to ``ops-copy-objects``, which
    matches no entry, so every override on those planes was silently read as absent.

    Args:
      None.

    Returns:
      Directory to a ``(module/resource, variable names)`` pair.

    Raises:
      None.
    """
    supply = {}
    for module, resource, directories, names, override in _resources():
        entries = _map_entries(_locals_source(MODULES / module), override) if override else {}
        for directory, key in directories:
            supply[directory] = (
                f"{module}/{resource}",
                names | frozenset(_assigned(entries.get(key, ""))),
            )
    return supply


@functools.lru_cache(maxsize=1)
def _manifest() -> tuple[dict[str, list[str]], dict[str, dict]]:
    """The two deploy manifests: functions with their layers, and the layers themselves.

    Args:
      None.

    Returns:
      Function name to layer flags, and layer flag to its manifest entry.

    Raises:
      None.
    """
    functions = json.loads(FUNCTION_MANIFEST.read_text(encoding="utf-8"))
    layers = json.loads(LAYER_MANIFEST.read_text(encoding="utf-8"))
    return (
        {entry["name"]: entry.get("layers", []) for entry in functions},
        {entry["flag"]: entry for entry in layers},
    )


def _import_roots(function: str) -> list[pathlib.Path]:
    """The directories a function's imports resolve against, as the deployment resolves them.

    Its own directory plus one root per attached layer, and no others. Scoping to the attached
    layers is what keeps the walk honest: a global search would resolve a name through a layer
    the function does not carry, and report a demand it cannot actually reach.

    Args:
      function: The function's manifest name.

    Returns:
      The existing roots, in resolution order.

    Raises:
      None.
    """
    attached, layers = _manifest()
    roots = [LAMBDAS / function]
    for flag in attached.get(function, []):
        entry = layers[flag]
        if "package" in entry:
            roots.append((ROOT / entry["package"]).parent)
        elif "sourceDir" in entry:
            roots.append(ROOT / entry["sourceDir"])
    return [root for root in roots if root.is_dir()]


def _modules_under(roots: tuple[pathlib.Path, ...]) -> dict[str, pathlib.Path]:
    """Importable module names mapped to files, over these roots only.

    Args:
      roots: The roots to index.

    Returns:
      Dotted module name to file path, first root winning a collision.

    Raises:
      None.
    """
    found: dict[str, pathlib.Path] = {}
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if path.name.startswith(("test_", "conftest")):
                continue
            parts = list(path.relative_to(root).parts)
            if parts[-1] == "__init__.py":
                name = ".".join(parts[:-1])
            else:
                name = ".".join([*parts[:-1], parts[-1][:-3]])
            if name:
                found.setdefault(name, path)
    return found


def _literal_maps(tree: ast.Module) -> dict[str, object]:
    """Every module-level name bound to a literal collection.

    Needed because the API's config does not pass a literal to its reader — it indexes its own
    map, so a scan for string arguments alone would find none of its requirements and report
    that the API demands nothing.

    Args:
      tree: The parsed module.

    Returns:
      Name to its evaluated literal, skipping anything not literal-evaluable.

    Raises:
      None.
    """
    maps: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                try:
                    maps[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    continue
    return maps


def _reader_names(tree: ast.Module) -> set[str]:
    """The local names bound to the fleet's fail-fast reader in one module.

    Resolved per module rather than matched against two fixed spellings, because the reader is
    routinely imported under a third. The archive domain layer binds it as ``_require_env``, and
    a scan keyed on the exported name alone cannot see that call at all — which is how the one
    variable this whole rule was written for came to be invisible to the guard enforcing it.

    Args:
      tree: The parsed module.

    Returns:
      Every name a call to the reader may appear under here, including the bare spellings for
      the attribute form.

    Raises:
      None.
    """
    names = set(FAIL_FAST_READERS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in FAIL_FAST_READERS
            )
    return names


def _demanded_by(tree: ast.Module) -> set[str]:
    """The environment names one module can demand through a fail-fast read.

Four shapes. Two of them occur in the tree today: an attribute read of the lazily resolved
    config, which raises through its ``__getattr__``, and an explicit reader call, which raises
    directly whether passed a literal or an entry from the caller's own map. The reader call was
    being missed whenever the reader had been imported under an alias, which is how one domain
    layer writes it.

    The other two are counted prospectively, and are cheap to count. ``getattr`` with a literal
    reaches the same ``__getattr__`` while looking like nothing to a checker; a subscript of
    ``os.environ`` raises ``KeyError`` on its own. Importing a required name FROM the config
    module is counted for the same reason and is the worst of the four — it resolves at import,
    so it fails at COLD START rather than on a branch, and the config module's own docstring
    warns against writing it with nothing enforcing that.

    Args:
      tree: The parsed module.

    Returns:
      The variable names it can require.

    Raises:
      None.
    """
    required = _required_names()
    names = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in required
    }
    maps = _literal_maps(tree)
    readers = _reader_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("config"):
            names.update(alias.name for alias in node.names if alias.name in required)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            target = node.value
            environ = (isinstance(target, ast.Attribute) and target.attr == "environ") or (
                isinstance(target, ast.Name) and target.id == "environ"
            )
            if environ and isinstance(node.slice.value, str):
                names.add(node.slice.value)
        elif isinstance(node, ast.Call) and node.args:
            called = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", None)
            )
            argument = node.args[0]
            if called == "getattr" and len(node.args) > 1:
                argument = node.args[1]
            elif called not in readers:
                continue
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                names.add(argument.value)
            elif (
                isinstance(argument, ast.Subscript)
                and isinstance(argument.value, ast.Name)
                and isinstance(argument.slice, ast.Constant)
            ):
                entry = maps.get(argument.value.id)
                value = entry.get(argument.slice.value) if isinstance(entry, dict) else None
                if isinstance(value, str):
                    names.add(value)
    return names


def _imports_of(tree: ast.Module, module: str, package: bool) -> set[str]:
    """Every module name one module imports, absolute and relative forms both.

    By AST over the whole file, so an import deferred into a function body counts. That shape is
    exactly the one that survives cold start and fails on the branch that runs it.

    The relative form honours the DOT COUNT rather than stripping one component. The transfer
    subpackage reaches its siblings with ``from .. import clients``, and resolving that as though
    it were a single dot pointed at modules which do not exist — so the walk stopped there and
    four verbs computed a demand that omitted everything reachable through it.

    Args:
      tree: The parsed module.
      module: Its own dotted name, for resolving a relative import.
      package: Whether that name refers to a package's ``__init__``, whose relative imports
        resolve from itself rather than from its parent.

    Returns:
      The imported module names, each also paired with its imported members so a submodule
      imported by name resolves.

    Raises:
      None.
    """
    parts = module.split(".") if module else []
    if not package:
        parts = parts[:-1]
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            if target:
                found.add(target)
                found.update(f"{target}.{alias.name}" for alias in node.names)
    return found


@functools.cache
def demand(function: str) -> frozenset[str]:
    """The required variables one function's import closure can actually reach.

    Args:
      function: The function's manifest name, which is also its source directory.

    Returns:
      The subset of the fleet's required set it can demand.

    Raises:
      None.
    """
    roots = tuple(_import_roots(function))
    modules = _modules_under(roots)
    own = (LAMBDAS / function).resolve()
    pending = [name for name, path in modules.items() if path.parent == own]
    seen, needed = set(), set()
    while pending:
        name = pending.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        tree = ast.parse(modules[name].read_text(encoding="utf-8"))
        needed |= _demanded_by(tree)
        package = modules[name].name == "__init__.py"
        pending.extend(
            target for target in _imports_of(tree, name, package) if target in modules
        )
    return frozenset(needed) & _required_names()


DEPLOYED = sorted(_manifest()[0])


@pytest.mark.parametrize("function", DEPLOYED)
def test_a_functions_environment_supplies_every_variable_its_code_can_reach(function):
    """The guard itself, one case per deployed function.

    A shortfall here is a ``RuntimeError`` in production on the branch that reads the name, with
    a green apply, a green deploy and a green suite either side of it.
    """
    where, supplied = _supply()[function]
    missing = demand(function) - supplied

    assert not missing, (
        f"{function} can reach {sorted(missing)} on some branch, and {where}'s environment does "
        f"not set it. That is a RuntimeError at first access in production — invisible to apply, "
        f"to update-function-code, and to this suite everywhere except here"
    )


def test_every_deployed_function_is_claimed_by_exactly_one_terraform_resource():
    """The completeness control, and the reason the guard above cannot quietly stop covering one.

    Both directions are failures worth naming. A manifest function no resource claims is a
    function this file never checks; a claimed name that is in no manifest means the derivation
    of a directory from a deployed name has drifted, and every demand computed through it is
    being read from the wrong source tree.

    The third assertion is the one that keeps the other two from being satisfiable by a name
    that resolves to nothing. Every step of the walk is forgiving of a missing directory — the
    roots are filtered by existence and the seed is a directory listing — so a manifest name
    whose source tree has been renamed computes an empty demand and satisfies every comparison
    in this file, including both positive controls. Asserting the directory exists is what turns
    that from silence into a failure.
    """
    claimed = [
        directory for _, _, directories, _, _ in _resources() for directory, _ in directories
    ]
    deployed = set(DEPLOYED)

    assert len(claimed) == len(set(claimed)), (
        f"two Terraform resources claim the same function: "
        f"{sorted({name for name in claimed if claimed.count(name) > 1})}"
    )
    assert set(claimed) == deployed, (
        f"deployed but unclaimed by any lambda.tf: {sorted(deployed - set(claimed))}; "
        f"claimed but in no deploy manifest: {sorted(set(claimed) - deployed)}"
    )
    missing = [name for name in deployed if not (LAMBDAS / name).is_dir()]
    assert not missing, (
        f"{missing} is deployed but has no lambdas/ directory, so its demand computes as empty "
        f"and every assertion in this file passes over it while the function still runs"
    )


def test_no_per_verb_override_can_shadow_a_required_variable():
    """A per-verb map is merged OVER the base block, so an entry can replace a required name.

    An empty string is what makes this worth pinning rather than trusting: the reader refuses
    one exactly as it refuses an unset variable, so a verb overridden to ``""`` fails at first
    access while the base block still names the variable and every eye passes over it. The maps
    are empty today; this holds the reason they must stay that way for these names.
    """
    offenders = {}
    for module, _, _, _, override in _resources():
        if not override:
            continue
        source = _locals_source(MODULES / module)
        for key, body in _map_entries(source, override).items():
            shadowed = _assigned(body) & _required_names()
            if shadowed:
                offenders[f"{module}:{key}"] = sorted(shadowed)

    assert not offenders, f"per-verb overrides shadow required variables: {offenders}"


def test_every_function_exempt_from_the_required_set_demands_nothing():
    """The exemption is DERIVED, and this is what stops it outliving its reason.

    One direction only, deliberately. Thirty-one of the eighty-six functions demand nothing —
    every verb that neither authorises nor reads a registry — so "demands nothing" does not pick
    out the exempt four, and the converse would be false. What is asserted is the half that can
    go wrong: an exempt function must not have grown a demand.

    The functions that attach the layer for its logging alone set almost none of the required
    set. Naming them in a list here would be a coupling that keeps passing after one of them
    grows a read — the exemption would then be hiding a real requirement rather than recording
    an absent one. So the list is imported from the suite that already owns that property, and
    what is asserted is that the two agree: each of those functions demands nothing, and its
    Terraform is correspondingly free to omit the set.
    """
    from test_layer_import_safety import SINGLETONS

    still_demanding = {name: sorted(demand(name)) for name in SINGLETONS if demand(name)}

    assert not still_demanding, (
        f"{still_demanding} attach the layer for logging alone and set almost none of the "
        f"required set, yet now reach one. Either the read is a mistake or the function's "
        f"Terraform must start setting the variable — the exemption cannot simply absorb it"
    )
    thin = {name for name in SINGLETONS if not _supply()[name][1] & _required_names()}
    assert thin, (
        "no exempt function omits the required set any more — this test is now measuring "
        "nothing, and the demand scan above has lost its only negative case"
    )


def test_the_demand_scan_reaches_through_a_layer_and_through_a_lookup_table():
    """The positive control, and the one this file cannot do without.

    Every assertion above is a subset comparison, and an empty demand satisfies one trivially.
    So if the import walk silently stopped resolving — a renamed layer flag, a moved package, a
    root that no longer exists — all eighty-odd cases would pass while measuring nothing at all.
    Both reaches asserted here are ones a shallower scan gets wrong: the first is only reachable
    two layers deep, and the second only by evaluating a map the reader indexes.
    """
    through_a_layer = demand("file-ops-validate-authorize")
    assert "SHARED_SPACE_BUCKET" in through_a_layer, (
        "the walk no longer reaches cpcommon.config through the file-ops domain layer — every "
        "superset assertion in this file is now passing on an empty demand"
    )
    assert "ATHENA_WORKGROUP" in demand("api"), (
        "the API's own config indexes its required map rather than passing a literal; losing "
        "that shape makes the API demand nothing and its whole environment unchecked"
    )
    assert "ATHENA_WORKGROUP" in demand("table-builder-execute-ddl"), (
        "the workgroup read in the DDL verb is no longer seen — the one plane whose demand "
        "differs from its neighbours is now indistinguishable from them"
    )
    assert demand("archive-validate-authorize") >= {"ADMIN_BUCKET", "USER_SPACE_BUCKET"}, (
        "the archive layer's reads are no longer seen. This is the reach that was missed once "
        "already, when the layer imported the shared reader under an alias"
    )


def test_the_terraform_side_is_actually_being_parsed():
    """The same control for the other half of every comparison.

    A supply set that came back empty would turn each assertion into ``demand <= {}``, which
    fails loudly — but a supply set built from the WRONG block, or a resource list that quietly
    lost its merge-form planes, fails silently in the direction that matters.
    """
    rows = _resources()
    assert len(rows) >= 16, f"only {len(rows)} lambda resources parsed out of the module tree"
    assert any(override for _, _, _, _, override in rows), (
        "no resource parsed as the merge form — the per-verb override check is measuring nothing"
    )
    assert _supply()["table-builder-execute-ddl"][1] >= {"ATHENA_WORKGROUP", "ADMIN_BUCKET"}


def test_the_required_set_is_still_the_four_this_file_was_measured_against():
    """The tripwire for a change to the fleet contract itself, rather than to one plane.

    The reachability guard above is deliberately quiet about a name nothing reads yet: no
    function can demand it, so no environment is short of it, and every case stays green. That
    is correct and it is also a blind spot, because the name is now a fleet-wide requirement
    that no plane supplies. This is the half that speaks up. It is not a duplicate of the
    per-plane mirror beside ``user-directory-build``'s verb tests — that one catches the same
    change through a plane, this one through the declaration — and the pair was kept after
    checking that a variable added here reddens both.
    """
    assert _required_names() == {
        "ADMIN_BUCKET",
        "USER_SPACE_BUCKET",
        "SHARED_SPACE_BUCKET",
        "ATHENA_WORKGROUP",
    }, (
        f"the fleet's required set is now {sorted(_required_names())}. Every plane whose code "
        f"can reach the new name must set it, and the reachability guard above cannot tell you "
        f"that until something reads it — check the environment blocks before widening this"
    )


def test_no_module_lets_terraform_set_the_build_stamp() -> None:
    """`BUILD_VERSION` travels in the artefact, and Terraform must not set it ANYWHERE.

    `test_api_module.py` asserts this for the API's own `lambda.tf`, and
    `cpcommon.observability` states it as a property of the whole fleet. One module's guard cannot
    carry a fleet-wide claim, so this sweeps every module that declares a function.

    The reason is unchanged by the move to containers and is worth restating where the sweep lives:
    `update-function-configuration --environment` replaces the map whole, so an env-borne version
    would either race an apply or be reverted by the next one — and Deploy Infrastructure is
    path-filtered to `infra/**`, so a Tofu-set value would name the last INFRA commit rather than
    the code that is running. Both pipelines write the file instead: `Deploy Lambdas` into each
    zip beside the handler, `lambdas/Dockerfile` into the image's task root.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any module's Terraform sets the stamp.
    """
    offenders = sorted(
        path.relative_to(MODULES.parent).as_posix()
        for path in MODULES.glob("*/*.tf")
        if "BUILD_VERSION" in path.read_text(encoding="utf-8")
    )

    assert offenders == [], (
        f"Terraform sets BUILD_VERSION in {offenders}. The stamp travels in the artefact — the "
        "zip's package or the image's task root — because an env-borne one names the last infra "
        "commit rather than the running code, and an apply would revert whatever CI set."
    )
