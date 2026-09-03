#!/usr/bin/env python3
"""Deletes every published version of the Lambda layers the zip pipeline left behind.

Every function now runs the fleet's container image and none attaches a layer, so the published
versions are orphans that no longer buy a rollback: rolling back means pointing the fleet at a
previous sha's image, which is a workflow input and no code change. This script is the one-shot
that removes them.

**Why the layer names are carried here rather than derived.** Terraform declares only eight of the
ten: ``control-plane-common`` and ``table-builder-common`` have no local and no output anywhere
under ``infra/``, because the layer table was what named them. Deriving this list from Terraform
would leave those two behind — a quarter of the published versions — and a half-finished destroy
looks exactly like a finished one. The list below is the ``layerName`` set of the deleted
``.github/lambda-layers.json``, whose last content is recoverable from git history at the commit
that removed it; the accompanying suite asserts the two Terraform never named, so an eighth-of-ten
derivation cannot creep back in later.

The account cannot be enumerated instead: the deploy role holds ``ListLayerVersions`` scoped to
per-plane layer ARNs and no account-wide ``lambda:ListLayers``, so a listing of what exists is not
an API this identity can make.

**The verification is the re-list, not the delete.** ``DeleteLayerVersion`` is idempotent and
answers 204 for a version that was never there, so its success proves nothing. Each layer is
re-listed after its deletions and a surviving version raises.

Progress is written to stderr per layer, before the verdict on stdout. The deletion is
irreversible and the verdict is only printed once every layer is swept, so a run that dies
part-way would otherwise leave no record of which layers are already gone.

**A sweep of nothing must not look like a completed one.** An absent layer and a
just-emptied one are the same API answer, so a wrong ``--project`` or ``--environment``
would report ten empty layers, exit 0, and claim success — after which the grants come off
and 923 versions are stranded with no identity left that can reach them.

``apply`` therefore requires ``--expect-versions``, the count the report found, re-checked
against the live total before anything is deleted. Supplying it is impossible without having
run the report, which makes report-before-apply a gate rather than an instruction in a
comment. It is also the containment the IAM grants do not give — they wildcard the environment
segment (``dat-*-archive-*``), so a wrong environment is authorised to delete.

**The count must be at least 1, and that is the half a first version got wrong.** A wrong name
set reports zero, and an operator copying that zero into ``apply`` would meet a gate comparing
0 to 0 — passing on precisely the input it exists to refuse. The comparison alone is not the
guard; the comparison plus a positive floor is.

Usage:
    destroy_lambda_layers.py --mode report --project dat --environment prod --region us-east-1
    destroy_lambda_layers.py --mode apply  --project dat --environment prod --region us-east-1 \\
                             --expect-versions 923

Attributes:
    LAYER_SUFFIXES: The ten layer names the zip pipeline published, without the
        ``{project}-{environment}-`` prefix every one of them carries.
    TERRAFORM_ORPHANS: The two of those ten that Terraform names nowhere. Asserted by the suite
        rather than left as a comment, because it is the fact a future derivation would lose.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

LAYER_SUFFIXES = (
    "archive-common",
    "control-plane-common",
    "data-quality-common",
    "data-quality-polars",
    "file-ops-common",
    "file-send-common",
    "shared-space-common",
    "table-builder-common",
    "table-builder-polars",
    "table-share-common",
)

TERRAFORM_ORPHANS = frozenset({"control-plane-common", "table-builder-common"})


def layer_names(project: str, environment: str) -> tuple[str, ...]:
    """The fully-qualified layer names for one deployment.

    Args:
      project: The resource-name prefix, e.g. ``dat``.
      environment: The environment segment, e.g. ``prod``.

    Returns:
      One name per entry in ``LAYER_SUFFIXES``, in that order.

    Raises:
      ValueError: If either part is empty. An empty repository variable renders as an empty
        string rather than going unset, and the names it would build
        (``--prod-archive-common``) match no layer and no grant, so the run would report a
        clean sweep of nothing.
    """
    if not project or not environment:
        raise ValueError(
            f"project and environment must both be non-empty, got {project!r} and {environment!r}"
        )
    return tuple(f"{project}-{environment}-{suffix}" for suffix in LAYER_SUFFIXES)


def versions_of(client: Any, name: str) -> list[int] | None:
    """Every published version number of one layer, oldest first.

    Paginated explicitly. ``ListLayerVersions`` answers at most 50 per page and seven of the ten
    layers carry more than that, so a single call would read a third of the fleet's versions and
    report the rest as absent.

    Args:
      client: A Lambda client, or any object exposing ``list_layer_versions`` and an
        ``exceptions.ResourceNotFoundException``.
      name: The fully-qualified layer name.

    Returns:
      The version numbers, ascending, or ``None`` when the layer holds none. In Lambda a layer
      with no versions does not exist, so those are one fact rather than two, and ``None`` is
      how this function says it.

      **Absence is zero versions, NOT an exception.** Measured against the live API: a name
      that has never been published answers ``{"LayerVersions": []}`` and raises nothing. The
      ``ResourceNotFoundException`` catch is kept because the API models that error on this
      call and a future answer may use it, but a guard that keyed on the exception alone would
      never fire, which is the shape of a check that reads as coverage and provides none.

    Raises:
      None.
    """
    versions: list[int] = []
    marker: str | None = None
    while True:
        kwargs: dict[str, Any] = {"LayerName": name, "MaxItems": 50}
        if marker:
            kwargs["Marker"] = marker
        try:
            page = client.list_layer_versions(**kwargs)
        except client.exceptions.ResourceNotFoundException:
            break
        versions.extend(int(v["Version"]) for v in page.get("LayerVersions", []))
        marker = page.get("NextMarker")
        if not marker:
            break
    return sorted(versions) if versions else None


def report(client: Any, names: tuple[str, ...]) -> dict[str, list[int] | None]:
    """What a destroy would delete, without deleting anything.

    Args:
      client: A Lambda client.
      names: The fully-qualified layer names to inspect.

    Returns:
      Layer name to its published version numbers, or to ``None`` where the layer does not
      exist.

    Raises:
      None.
    """
    return {name: versions_of(client, name) for name in names}


def total_versions(found: dict[str, list[int] | None]) -> int:
    """How many versions a report found, counting an absent layer as none.

    Args:
      found: A report.

    Returns:
      The sum across every layer.

    Raises:
      None.
    """
    return sum(len(v) for v in found.values() if v is not None)


def destroy(client: Any, names: tuple[str, ...], expected: int) -> dict[str, list[int]]:
    """Deletes every published version of each layer, then proves each one positively absent.

    Args:
      client: A Lambda client.
      names: The fully-qualified layer names to destroy.
      expected: How many versions the caller's report found. The sweep refuses to start unless
        the live total still agrees.

    Returns:
      Layer name to the version numbers it deleted.

    Raises:
      RuntimeError: If the live total disagrees with ``expected``, or if a layer is still
        listable after its deletions.
    """
    found = report(client, names)
    live = total_versions(found)
    if live != expected:
        raise RuntimeError(
            f"expected {expected} versions across {len(names)} layers and found {live} — "
            "refusing to sweep. Re-run in report mode: either the names are wrong (a wrong "
            "project or environment resolves to layers that do not exist, and deleting nothing "
            "would look exactly like deleting everything), or something changed since the "
            "report this number came from"
        )

    deleted: dict[str, list[int]] = {}
    for name in names:
        versions = found[name] or []
        for version in versions:
            client.delete_layer_version(LayerName=name, VersionNumber=version)
        deleted[name] = versions
        survivors = versions_of(client, name)
        print(
            f"swept {name}: {len(versions)} deleted, "
            f"{'GONE' if survivors is None else f'{len(survivors)} REMAINING'}",
            file=sys.stderr,
            flush=True,
        )
        if survivors is not None:
            raise RuntimeError(
                f"{name} still lists versions {survivors} after deleting {versions} — "
                "the layer was NOT destroyed and the sweep is incomplete"
            )
    return deleted


def optional_count(value: str) -> int | None:
    """Parses ``--expect-versions``, treating an empty string as not supplied.

    The workflow passes this flag unconditionally so it never has to expand an empty bash
    array. ``"${arr[@]}"`` on an empty array is an unbound-variable error under ``set -u`` on
    bash 3.2 and fine on 4.4+, so the array form works on today's runner image and silently
    depends on it; the default `report` path is the one that would carry the empty array.

    Args:
      value: The raw argument.

    Returns:
      The count, or ``None`` when the argument is empty or whitespace.

    Raises:
      argparse.ArgumentTypeError: If a non-empty value is not a non-negative integer.
    """
    if not value.strip():
        return None
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from None
    if count < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {count}")
    return count


def _client(region: str) -> Any:
    """A Lambda client with the retry mode this workload needs.

    Args:
      region: The AWS region the layers live in.

    Returns:
      A boto3 Lambda client.

    Raises:
      None.
    """
    import boto3
    from botocore.config import Config

    return boto3.client(
        "lambda",
        region_name=region,
        config=Config(retries={"mode": "standard", "max_attempts": 10}),
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
      argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
      0 on success.

    Raises:
      SystemExit: On a bad argument, including ``--mode apply`` without ``--expect-versions``.
      RuntimeError: Propagated from ``destroy``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("report", "apply"), required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument(
        "--expect-versions",
        type=optional_count,
        default=None,
        help="How many versions the report found. Required by apply, which refuses to sweep "
        "unless the live total still agrees. This is what makes report-before-apply a gate "
        "rather than an instruction.",
    )
    args = parser.parse_args(argv)

    if args.mode == "apply" and args.expect_versions is None:
        parser.error("--mode apply requires --expect-versions; run --mode report first")
    if args.mode == "apply" and args.expect_versions < 1:
        parser.error(
            "--expect-versions must be at least 1. Zero is what a WRONG project or environment "
            "reports, and a zero expectation would match the zero it finds: the sweep would "
            "delete nothing and exit claiming ten layers were destroyed. There is nothing to "
            "sweep anyway when the report found none"
        )

    names = layer_names(args.project, args.environment)
    client = _client(args.region)

    verdict: dict[str, Any]
    if args.mode == "report":
        found = report(client, names)
        verdict = {
            "mode": "report",
            "layers": {n: v for n, v in found.items() if v is not None},
            "absent": sorted(n for n, v in found.items() if v is None),
            "versions": total_versions(found),
        }
    else:
        gone = destroy(client, names, args.expect_versions)
        verdict = {
            "mode": "apply",
            "layers": gone,
            "versions": sum(len(v) for v in gone.values()),
            "provedAbsent": sorted(gone),
        }

    json.dump(verdict, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
