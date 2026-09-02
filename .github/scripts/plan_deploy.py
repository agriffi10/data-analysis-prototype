"""Decides which Lambda functions and which layers a push actually needs to deploy.

Deploy Lambdas rebuilt and redeployed all 73 functions on every push. The median push
touches 4 function directories, so ~69 of them were re-uploading byte-identical code.

The reason that was not simply wasteful is worth stating, because it is what makes this
script's job harder than "diff the directories": every run republished all ten layers,
and `publish-layer-version` MINTS A NEW VERSION every time it is called. A new version
means a new ARN, and a function pins its layers by ARN — so every function needed
`update-function-configuration` on every run regardless of whether anything it depended
on had changed. Skipping functions is only correct once unchanged layers resolve to the
version already published rather than to a fresh one, which is why this script decides
layers and functions together and the workflow resolves the rest from AWS.

The failure this must never produce is a function left pointing at a layer whose contents
have moved on, or code deployed against a stale layer. Both surface as
`ModuleNotFoundError` at COLD START, where no test and no deploy can see them — SPEC-137
broke real Cognito signups exactly that way. So every rule here is biased toward
deploying too much: anything it cannot reason about confidently falls back to the whole
fleet.

Reads a list of changed paths and returns the plan as JSON. Pure and offline, so
``lambdas/test_plan_deploy.py`` can drive it over the real tables.

**THE NARROWING IS NO LONGER REACHED.** Once every function ran one container image, "which
functions changed" stopped having an answer: there is a single artefact, and a function left
un-pointed runs an older image and reports a stale build stamp while working perfectly.
``deploy-lambdas.yml`` therefore calls this module with ``--all`` and nothing else, so only the
sharding below is live. The narrowing is kept for one spec rather than half-removed — SPEC-214
replaces CI's function list with a Terraform output and deletes this module whole — and its tests
are kept with it, because a rule and its test go together or neither is trustworthy.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

#: Changing any of these makes no narrower answer trustworthy, so the plan degrades to the
#: whole fleet. These EXECUTE the deploy — a change to any of them can alter what happens to
#: a function whose own directory is untouched — including this planner, whose bug must not
#: be able to suppress the deploy that fixes it.
HARD_GLOBAL_PATHS = (
    ".github/workflows/deploy-lambdas.yml",
    ".github/scripts/deploy-lambda.sh",
    ".github/scripts/point-lambda.sh",
    ".github/scripts/build-layer.sh",
    ".github/scripts/plan_deploy.py",
    # Bundled into any function that attaches none of the dependency-bearing layers.
    "lambdas/requirements.txt",
)

#: The two tables. A change here is NARROWED by diffing the table against its previous
#: content rather than treated as global, because "add a function" is one of the commonest
#: pushes in this repository and it is the change least in need of a full-fleet deploy.
#: Narrowing requires the previous content; without it these behave exactly like the hard
#: paths above.
TABLE_PATHS = (
    ".github/lambda-functions.json",
    ".github/lambda-layers.json",
)

#: Kept for callers and tests that want the full set of paths that can force a full deploy.
GLOBAL_PATHS = HARD_GLOBAL_PATHS + TABLE_PATHS

#: Functions per shard the sharding aims for, and the ceiling on shard count. Both exist
#: only to keep each job comfortably over a billed minute — see the workflow.
PER_SHARD = 12
MAX_SHARDS = 6


def layer_sources(layer: dict) -> list[str]:
    """The paths whose contents end up inside one layer.

    Deliberately precise rather than directory-wide. ``lambdas/control-plane-common/``
    holds the cpcommon package AND its test suite, so watching the directory would
    republish the layer — and therefore redeploy all 73 functions that attach it — every
    time one of its tests changed. Watching ``.../cpcommon`` does not.

    Args:
      layer: One entry from the layer table.

    Returns:
      Path prefixes, each matched against a changed path by prefix.
    """
    sources = []
    if layer.get("requirements"):
        sources.append(layer["requirements"])
    if layer.get("package"):
        sources.append(layer["package"])
    source_dir = layer.get("sourceDir")
    if source_dir:
        # Only the modules the layer actually copies. The rest of that directory is tests,
        # and a module added there without being added to the list is caught by
        # test_the_layer_copy_list_matches_the_layer_directory, not here.
        sources.extend(f"{source_dir}/{module}.py" for module in layer.get("modules", []))
    return sources


def _touched(changed: set[str], prefix: str) -> bool:
    """Whether any changed path is, or is inside, ``prefix``.

    Args:
      changed: The changed paths.
      prefix: A file path or a directory path, without a trailing slash.

    Returns:
      True if the prefix itself changed or anything beneath it did.
    """
    return any(path == prefix or path.startswith(prefix + "/") for path in changed)


def _by_name(rows: list[dict], key: str) -> dict:
    """Indexes a table by its identity field."""
    return {row[key]: row for row in rows}


def _table_deltas(
    changed: set[str],
    functions: list[dict],
    layers: list[dict],
    old_functions: list[dict] | None,
    old_layers: list[dict] | None,
) -> tuple[set[str], set[str]] | None:
    """What a change to the two tables implies, or ``None`` if it cannot be narrowed.

    Returns ``None`` — meaning "fall back to the whole fleet" — whenever a table changed
    and its previous content is unavailable. That is the honest answer for a force-push, a
    first run, or a shallow clone, and it is the only branch here that can be wrong in the
    safe direction.

    Args:
      changed: Paths changed by the push.
      functions: The current function table.
      layers: The current layer table.
      old_functions: The function table before this push, if it could be read.
      old_layers: The layer table before this push, if it could be read.

    Returns:
      ``(function names, layer flags)`` implied by the table changes, or None.
    """
    selected: set[str] = set()
    publish: set[str] = set()

    if _touched(changed, ".github/lambda-functions.json"):
        if old_functions is None:
            return None
        before = _by_name(old_functions, "name")
        for row in functions:
            # A new row, or one that changed in ANY field — matching how the layer table is
            # compared below. Testing only `layers` is correct for today's two-field row and
            # would silently ignore a third field the moment one is added.
            if before.get(row["name"]) != row:
                selected.add(row["name"])

    if _touched(changed, ".github/lambda-layers.json"):
        if old_layers is None:
            return None
        before = _by_name(old_layers, "flag")
        for entry in layers:
            # ANY difference republishes, not just the build inputs: `description` is passed
            # to publish-layer-version, so it is part of what a version IS.
            if before.get(entry["flag"]) != entry:
                publish.add(entry["flag"])

    return selected, publish


def plan(
    changed: set[str],
    functions: list[dict],
    layers: list[dict],
    force_all: bool,
    old_functions: list[dict] | None = None,
    old_layers: list[dict] | None = None,
) -> dict:
    """Works out what to publish and what to deploy.

    Args:
      changed: Paths changed by the push, repository-relative.
      functions: The function table.
      layers: The layer table.
      force_all: Deploy everything regardless — a manual dispatch, or a diff that could
        not be computed. "I do not know what changed" must never mean "nothing did".
      old_functions: The function table before this push, where it could be read.
      old_layers: The layer table before this push, where it could be read.

    Returns:
      A dict with ``functions`` (names to deploy), ``publish`` (layer flags needing a new
      version), ``shards``, ``shard_count`` and ``reason``.
    """
    everything: str | None = None
    deltas: tuple[set[str], set[str]] | None = None

    if force_all:
        # The only live caller passes this on every run, so the sentence has to be true of that
        # rather than of the recovery case it was written for: it reaches a step summary.
        everything = "one image serves the whole fleet, so every function is pointed"
    elif any(_touched(changed, path) for path in HARD_GLOBAL_PATHS):
        hit = sorted(p for p in HARD_GLOBAL_PATHS if _touched(changed, p))
        everything = f"{', '.join(hit)} changed"
    else:
        deltas = _table_deltas(changed, functions, layers, old_functions, old_layers)
        if deltas is None:
            everything = "a table changed and its previous content was unavailable"

    if everything is not None or deltas is None:
        reason = f"deploying every function: {everything}"
        selected = [f["name"] for f in functions]
        publish = [layer["flag"] for layer in layers]
    else:
        from_tables_fns, from_tables_layers = deltas
        republished = {
            layer["flag"]
            for layer in layers
            if any(_touched(changed, source) for source in layer_sources(layer))
        } | from_tables_layers
        publish = sorted(republished)
        selected = [
            f["name"]
            for f in functions
            # Its own code changed, its row changed, or a layer it attaches is getting a new
            # version and therefore a new ARN it must be re-pointed at.
            if _touched(changed, f"lambdas/{f['name']}")
            or f["name"] in from_tables_fns
            or republished & set(f["layers"])
        ]
        reason = (
            f"{len(selected)} of {len(functions)} functions"
            + (f"; republishing {', '.join(publish)}" if publish else "; no layer changed")
        )

    count = min(MAX_SHARDS, max(1, math.ceil(len(selected) / PER_SHARD))) if selected else 0
    return {
        "functions": selected,
        "publish": sorted(publish),
        "shards": list(range(count)),
        "shard_count": count,
        "reason": reason,
    }


def main() -> int:
    """Reads the changed paths and prints the plan as JSON.

    Returns:
      0 always; an unusable input is expressed as ``--all`` by the caller, never as an
      error here, because a planner that fails closed would block every deploy.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--functions", default=".github/lambda-functions.json")
    parser.add_argument("--layers", default=".github/lambda-layers.json")
    parser.add_argument("--old-functions", default=None)
    parser.add_argument("--old-layers", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--changed-from",
        default="-",
        help="File of newline-separated changed paths, or - for stdin.",
    )
    args = parser.parse_args()

    if args.all:
        changed: set[str] = set()
    else:
        raw = (
            sys.stdin.read()
            if args.changed_from == "-"
            else pathlib.Path(args.changed_from).read_text()
        )
        changed = {line.strip() for line in raw.splitlines() if line.strip()}

    def maybe(path):
        """The table as it was before the push, or None if it could not be read."""
        if not path:
            return None
        try:
            return json.loads(pathlib.Path(path).read_text())
        except (OSError, ValueError):
            return None

    result = plan(
        changed,
        json.loads(pathlib.Path(args.functions).read_text()),
        json.loads(pathlib.Path(args.layers).read_text()),
        args.all,
        maybe(args.old_functions),
        maybe(args.old_layers),
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
