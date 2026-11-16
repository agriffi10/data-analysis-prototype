"""The container runtime, where almost every mistake applies green.

Text assertions over this module's Terraform. The three classes of failure they catch — the ones
that produce a container that never starts, the ones that work and are wrong, and the ones
invisible until something else needs them — are set out in ``infra/modules/spa/README.md``, along
with what only a live check can settle.

Attributes:
  INFRA: The IaC tree.
  SPA: The container-platform module.
  ROOT_MAIN: The composition that builds the runtime-configuration map and wires the module.
  ROOT_VARIABLES: Where ``spa_desired_count``'s default lives.
  NETWORK_ENDPOINTS: The endpoints file owning the reciprocal ingress rule this module must not
    re-declare.
  WRITABLE_PATHS: The one path the image writes, a copy on purpose — a shared constant would
    prove nothing.
  ALLOWED_TLS_POLICIES: TLS 1.3-capable ALB policies at or stricter than the spec's.
"""

import pathlib
import re

from tf_blocks import blocks, strip_comments

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
SPA = INFRA / "modules" / "spa"
ROOT_MAIN = INFRA / "main.tf"
ROOT_VARIABLES = INFRA / "variables.tf"
NETWORK_ENDPOINTS = INFRA / "modules" / "network" / "endpoints.tf"
WRITABLE_PATHS = ("/tmp",)  # noqa: S108 — a container path, not a host temp file

ALLOWED_TLS_POLICIES = frozenset(
    {
        "ELBSecurityPolicy-TLS13-1-2-2021-06",
        "ELBSecurityPolicy-TLS13-1-2-Res-2021-06",
        "ELBSecurityPolicy-TLS13-1-3-2021-06",
    }
)


def _source() -> str:
    """Concatenates every Terraform file in the container-platform module.

    Args:
      None.

    Returns:
      The module's whole source, comments included.

    Raises:
      None.
    """
    return "\n".join(path.read_text() for path in sorted(SPA.glob("*.tf")))


def _declares_a_task_volume(source: str) -> bool:
    """Whether the module's source declares a task-level volume, read with its comments blanked.

    Naming the thing you forbid is not the same as doing it, and this module explains at length
    why it uses a tmpfs rather than a task volume, so a raw scan reads those sentences as a
    violation. Comments go through the shared reader, so a ``//`` or ``/* */`` comment is skipped
    exactly as a ``#`` one is, while string contents stay searched.

    Args:
      source: The module's Terraform.

    Returns:
      True when ``volume {`` appears outside a comment.

    Raises:
      None.
    """
    return "volume {" in strip_comments(source)


def _container_definition() -> str:
    """Returns the single container definition's body from the task definition.

    Args:
      None.

    Returns:
      The text between ``container_definitions = jsonencode([`` and its closing bracket.

    Raises:
      AssertionError: When the block cannot be found, so no assertion below runs vacuously.
    """
    text = _source()
    start = text.find("container_definitions = jsonencode([")
    assert start > -1, "No container_definitions block — the parse went trivial."
    end = text.find("\n  ])", start)
    assert end > start, "The container_definitions block did not close where expected."
    return text[start:end]


def test_the_container_runs_read_only_as_a_non_root_user() -> None:
    """Both halves, because either alone leaves the other undone.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the root filesystem is writable or the container runs as root.
    """
    definition = _container_definition()
    assert re.search(r"readonlyRootFilesystem\s*=\s*true", definition), definition[:400]

    # The uid is a local rather than a literal, because the tmpfs mounts must be created owned by
    # the SAME value — see the writable-paths test for what splitting them costs.
    assert re.search(r"user\s*=\s*local\.container_uid", definition), (
        "The container definition names no user, so it runs as root."
    )
    uid = re.search(r'container_uid\s*=\s*"(\d+)"', _source())
    assert uid, "No container_uid local."
    assert uid.group(1) != "0", "The container runs as uid 0."


def test_the_mounted_paths_are_the_images_writable_set() -> None:
    """The task mounts exactly the one path the Node image writes.

    The image's real writable set is the behaviour matrix's to prove: it runs the container with a
    read-only root filesystem and this one tmpfs. This holds the module to that set, and it is the
    check that would have kept nginx's cache mount alive after nginx was gone.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the parse finds no list, the mounted set differs, the mounts are not
        derived from it, a task volume returns, or the mounts' owner is not the container's user.
    """
    paths = re.search(r"writable_paths\s*=\s*\[([^\]]+)\]", _source())
    assert paths, "No writable_paths local — the mounts are no longer derived from one list."
    from_local = tuple(sorted(re.findall(r'"([^"]+)"', paths.group(1))))

    assert from_local == WRITABLE_PATHS, (
        f"The module mounts {from_local}; the image writes {WRITABLE_PATHS}. A path missing here is "
        "a container that never starts, reported as a generic essential-container exit."
    )
    assert "for path in local.writable_paths" in _container_definition(), (
        "The mounts are hand-listed rather than derived from the writable_paths local."
    )

    # TMPFS, NOT A TASK VOLUME — measured, not preferred. A Fargate task volume arrives as an
    # empty root-owned directory and does not initialise from the image, so a container running
    # as a non-root user cannot write to it. A tmpfs is created owned by the uid its mount
    # options name, and that uid must be the one the container runs as.
    assert '"aws_ecs_task_definition"' in _source() and not _declares_a_task_volume(_source()), (
        "A task-level volume is back. It cannot give a non-root container a writable path: the "
        "mount arrives owned by root, and the server dies on a permission error that reads as a "
        "container bug."
    )
    tmpfs = re.search(r"tmpfs\s*=\s*\[(.*?)\]\s*\n\s*\}", _container_definition(), re.DOTALL)
    assert tmpfs, "No tmpfs block — the writable paths have no mechanism at all."
    assert "uid=${local.container_uid}" in tmpfs.group(1), tmpfs.group(1)
    assert "gid=${local.container_uid}" in tmpfs.group(1), tmpfs.group(1)

    # The mount's owner and the container's user are ONE value. Split, a mount is silently
    # unwritable by the process that needs it.
    assert re.search(r"user\s*=\s*local\.container_uid", _container_definition()), (
        "The container's user is not the local the tmpfs mounts are owned by."
    )

def test_the_service_ignores_the_image_and_still_obeys_the_desired_count() -> None:
    """CI owns the task definition; the count stays Terraform's because a step raises it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the image is not ignored, or when the count is.
    """
    service = blocks(_source(), "aws_ecs_service")["spa"]
    ignored = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", service)
    assert ignored, "Nothing is ignored, so every infra apply reverts the deployed image."

    entries = {entry.strip() for entry in ignored.group(1).split(",") if entry.strip()}
    assert "task_definition" in entries, entries
    assert "desired_count" not in entries, (
        "desired_count is ignored, which makes raising spa_desired_count a silent no-op — and "
        "the verification step that raises it from 0 to 1 reads as a broken service."
    )
    assert re.search(r"desired_count\s*=\s*var\.desired_count", service), service


def test_a_commented_out_task_volume_is_not_a_task_volume() -> None:
    """A block comment keeping the retired volume for reference does not trip the guard.

    The guard once dropped only ``#`` lines, so a ``/* */`` comment holding the old ``volume {``
    block failed it for a module that mounts a tmpfs. A live block is still found.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a comment reads as a volume, or a live volume is missed.
    """
    commented = 'resource "aws_ecs_task_definition" "spa" {\n  /*\n  volume {\n    name = "tmp"\n  }\n  */\n}\n'
    live = commented.replace("  /*\n", "").replace("  */\n", "")

    assert not _declares_a_task_volume(commented), "a block comment was read as a task volume"
    assert _declares_a_task_volume(live), "the fixture's live volume was not found, so the check reads nothing"
