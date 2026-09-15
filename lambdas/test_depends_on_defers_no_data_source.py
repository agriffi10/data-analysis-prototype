"""A data source a ``depends_on`` reaches is read at apply, so none may sit where one does.

Besides an argument unknown at plan, OpenTofu defers a data source to apply when it carries a
``depends_on`` of its own, or sits in a module called with one at any depth, and anything the edge
names has a create or an update pending. Then everything built from it is ``(known after apply)``
in the plan. A
policy document built that way is one no plan-time scan reads, and a value feeding a ``for_each``
is a hard error. Nearly every module the root calls waits on ``module.base``, which a pull request
changing a deploy grant touches, so the deferral is routine rather than rare.

The answer is never to drop the edge, which orders a deploy grant before its first use. It is to
read nothing there: render a document with ``templatefile()``, and pass what a data source would
have read from the root, where no edge defers it. The reasoning is in
``infra/modules/observability/README.md`` and in ``infra/info/deploy-role-iam.md``.

Attributes:
  INFRA: The IaC tree the sweep reads.
  HCL_FILES: The native-syntax files OpenTofu loads from a module directory, all of them read.
  JSON_FILES: The JSON-syntax files it also loads, which this sweep cannot parse and so names
    rather than passes over.
  DEFERRING_CALLS_FLOOR: The fewest module calls carrying a ``depends_on`` the real tree must
    yield, so a collector that stopped seeing the edge cannot pass on an empty population. Most
    modules the root calls carry one, so fifteen leaves room for several to be retired before the
    floor reports the tree rather than the collector.
"""

import pathlib

from tf_blocks import argument, data_sources, module_calls

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"

DEFERRING_CALLS_FLOOR = 15

HCL_FILES = ("*.tf", "*.tofu")

JSON_FILES = ("*.tf.json", "*.tofu.json")


def _files(directory: pathlib.Path, patterns: tuple[str, ...], *, recursive: bool) -> list[pathlib.Path]:
    """The files under ``directory`` matching any of ``patterns``, outside provider caches.

    Args:
      directory: Where to look.
      patterns: Glob patterns, one per file shape.
      recursive: Whether to descend into subdirectories.

    Returns:
      The matching files, sorted.

    Raises:
      None.
    """
    found = (
        path
        for pattern in patterns
        for path in (directory.rglob(pattern) if recursive else directory.glob(pattern))
    )
    return sorted(path for path in found if ".terraform" not in path.parts)


def _has_depends_on(body: str) -> bool:
    """Whether a block assigns ``depends_on`` at its top level, comments excluded.

    Args:
      body: A block's body, outer braces excluded.

    Returns:
      True when the block carries the argument.

    Raises:
      None.
    """
    try:
        argument(body, "depends_on")
    except ValueError:
        return False
    return True


def _local_source(caller: pathlib.Path, body: str) -> pathlib.Path | None:
    """The directory a module call's ``source`` names, when it is a path in this tree.

    Args:
      caller: The file the call is written in, which a relative source is resolved against.
      body: The module call's body.

    Returns:
      The resolved directory, or None for a source that is not a local path.

    Raises:
      ValueError: If the call has no ``source``.
    """
    source = argument(body, "source").strip('"')
    if not source.startswith(("./", "../")):
        return None
    return (caller.parent / source).resolve()


def _reached(directory: pathlib.Path) -> tuple[list[pathlib.Path], list[str]]:
    """Every module directory an edge on ``directory`` reaches: itself and all it calls, at any depth.

    Args:
      directory: The module a deferring call names.

    Returns:
      The directories reached, and the non-local sources among the nested calls, which this
      sweep cannot open.

    Raises:
      None.
    """
    found: list[pathlib.Path] = []
    unreadable: list[str] = []
    pending = [directory]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.append(current)
        for path in _files(current, HCL_FILES, recursive=False):
            for body in module_calls(path.read_text(encoding="utf-8")).values():
                nested = _local_source(path, body)
                if nested is None:
                    unreadable.append(argument(body, "source"))
                else:
                    pending.append(nested)
    return sorted(found), unreadable


def deferred_data_sources(root: pathlib.Path) -> tuple[list[str], int]:
    """Every data source a ``depends_on`` defers, named with the edge that defers it.

    Args:
      root: The Terraform tree to sweep.

    Returns:
      One sorted line per deferred data source, and how many module calls carrying a
      ``depends_on`` were found.

    Raises:
      None.
    """
    root = root.resolve()
    findings = [
        f"{path.relative_to(root).as_posix()} is JSON syntax, which this sweep cannot read"
        for path in _files(root, JSON_FILES, recursive=True)
    ]
    calls = 0
    for path in _files(root, HCL_FILES, recursive=True):
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(root).as_posix()
        for key, body in data_sources(text).items():
            if _has_depends_on(body):
                findings.append(f"data.{key} in {where} carries its own depends_on")
        for name, body in module_calls(text).items():
            if not _has_depends_on(body):
                continue
            calls += 1
            target = _local_source(path, body)
            if target is None:
                findings.append(f'module "{name}" in {where} has a depends_on and a source this sweep cannot open')
                continue
            directories, unreadable = _reached(target)
            findings.extend(
                f'module "{name}" in {where} reaches {source}, which this sweep cannot open' for source in unreadable
            )
            for directory in directories:
                for module_file in _files(directory, HCL_FILES, recursive=False):
                    for key in data_sources(module_file.read_text(encoding="utf-8")):
                        findings.append(
                            f'data.{key} in {module_file.relative_to(root).as_posix()}, '
                            f'deferred by module "{name}" in {where}'
                        )
    return sorted(findings), calls


def test_no_data_source_sits_where_a_depends_on_defers_it() -> None:
    """The tree as it stands: every edge is kept, and none of them reaches a data source.

    The positive controls come first. The collector must find the root's own caller-identity read,
    which no edge defers, or it is reading nothing; and it must find the edges, or an empty result
    agrees with every tree.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the collector reads nothing, or a data source sits behind a depends_on.
    """
    assert "aws_caller_identity.current" in data_sources((INFRA / "main.tf").read_text(encoding="utf-8"))

    findings, calls = deferred_data_sources(INFRA)

    assert calls >= DEFERRING_CALLS_FLOOR, (
        f"only {calls} module calls carry a depends_on, so the sweep below is about the collector "
        "rather than the tree"
    )
    assert findings == [], (
        "these data sources are read at apply whenever the edge's target has a change pending, so "
        "everything built from them is unknown in the plan. Render a document with templatefile(), "
        f"or pass the value from the root: {findings}"
    )


def test_each_deferring_shape_is_named_and_nothing_else_is(tmp_path: pathlib.Path) -> None:
    """A planted tree: both edges that defer are reported by name, and the reads they miss are not.

    Deferred: a data source in a module the root waits on, one in a ``.tofu`` file beside it, one
    in a module THAT module calls, one behind an edge written inside a module, and one carrying its
    own ``depends_on``. A JSON-syntax file is named as unreadable. Not deferred, and so asserted
    silent by the exact comparison: a read in a module called with no edge, one whose edge is only
    a comment, and a plain read at the root.

    Args:
      tmp_path: pytest's scratch directory, which holds the planted tree.

    Returns:
      None.

    Raises:
      AssertionError: If a deferred read goes unreported, or a read nothing defers is reported.
    """
    files = {
        "main.tf": (
            'module "waits" {\n  source     = "./modules/waits"\n  depends_on = [module.other]\n}\n'
            'module "free" {\n  source = "./modules/free"\n}\n'
            'module "commented" {\n  source = "./modules/commented"\n  # depends_on = [module.other]\n}\n'
            'data "aws_region" "own_edge" {\n  depends_on = [module.other]\n}\n'
            'data "aws_caller_identity" "root" {}\n'
        ),
        "modules/waits/main.tf": (
            'data "aws_iam_policy_document" "doc" {}\nmodule "inner" {\n  source = "../inner"\n}\n'
        ),
        "modules/waits/extra.tofu": 'data "aws_partition" "tofu" {}\n',
        "modules/waits/generated.tf.json": '{"data": {"aws_region": {"json": {}}}}\n',
        "modules/inner/main.tf": 'data "aws_region" "current" {}\n',
        "modules/free/main.tf": (
            'data "aws_caller_identity" "current" {}\n'
            'module "late" {\n  source     = "../late"\n  depends_on = [aws_sqs_queue.q]\n}\n'
        ),
        "modules/late/main.tf": 'data "aws_partition" "current" {}\n',
        "modules/commented/main.tf": 'data "aws_region" "current" {}\n',
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")

    findings, calls = deferred_data_sources(tmp_path)

    assert calls == 2
    assert findings == [
        'data.aws_iam_policy_document.doc in modules/waits/main.tf, deferred by module "waits" in main.tf',
        'data.aws_partition.current in modules/late/main.tf, deferred by module "late" in modules/free/main.tf',
        'data.aws_partition.tofu in modules/waits/extra.tofu, deferred by module "waits" in main.tf',
        'data.aws_region.current in modules/inner/main.tf, deferred by module "waits" in main.tf',
        "data.aws_region.own_edge in main.tf carries its own depends_on",
        "modules/waits/generated.tf.json is JSON syntax, which this sweep cannot read",
    ]
