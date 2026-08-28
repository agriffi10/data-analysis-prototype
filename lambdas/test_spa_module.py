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
  SPEC_193: This module's own spec, whose mounted-pair criterion the mount assertion reads.
  SPEC_194: The image spec, whose writable-path criterion this module's mounts must equal.
  WRITABLE_PATHS: The two paths, a third copy on purpose — a shared constant would prove nothing.
  ALLOWED_TLS_POLICIES: TLS 1.3-capable ALB policies at or stricter than the spec's.
"""

import pathlib
import re

from tf_blocks import blocks

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
SPA = INFRA / "modules" / "spa"
ROOT_MAIN = INFRA / "main.tf"
ROOT_VARIABLES = INFRA / "variables.tf"
NETWORK_ENDPOINTS = INFRA / "modules" / "network" / "endpoints.tf"
SPEC_193 = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "specs"
    / "SPEC-193-network-compute-and-the-front-door.md"
)
SPEC_194 = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "specs"
    / "SPEC-194-the-spa-container.md"
)

WRITABLE_PATHS = ("/tmp", "/var/cache/nginx")  # noqa: S108 — container paths, not host temp files

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


def _source_without_comments() -> str:
    """The module's source with comment lines dropped.

    Naming the thing you forbid is not the same as doing it, and this module explains at length
    why it does NOT use linuxParameters.tmpfs, the awslogs driver's create-group option or the
    legacy load-balancer service account — a raw scan reads those sentences as violations.

    Args:
      None.

    Returns:
      The source with every full-line comment removed.

    Raises:
      None.
    """
    return "\n".join(line for line in _source().splitlines() if not line.lstrip().startswith("#"))


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


def test_the_mounted_paths_equal_the_writable_set_the_image_spec_declares() -> None:
    """An agreement between two specs and one configuration, read from the spec itself.

    The limit is worth stating: this proves the two DOCUMENTS agree. That the image's real
    writable set matches is the image spec's own build matrix, and is recorded there.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the spec's criterion cannot be found (the parse going trivial), or
        when the mounted set differs from it.
    """
    own_spec = SPEC_193.read_text()
    own_anchor = "The mounted pair is exactly"
    assert own_anchor in own_spec, (
        f"{SPEC_193.name} no longer states its mounted-pair criterion at '{own_anchor}'. This test "
        "compares two specs and one configuration; re-point it rather than deleting it."
    )
    own_criterion = own_spec[own_spec.index(own_anchor) : own_spec.index(own_anchor) + 200]
    own_declared = tuple(sorted(set(re.findall(r"`(/[a-z/]+)`", own_criterion))))
    assert len(own_declared) == 2, f"Parsed {own_declared} from this spec — the parse went trivial."

    spec = SPEC_194.read_text()
    anchor = "The writable paths the image needs are exactly"
    assert anchor in spec, (
        f"{SPEC_194.name} no longer states its writable-path criterion at '{anchor}'. This test "
        "compares two specs; if the wording moved, re-point it — do not delete it."
    )
    criterion = spec[spec.index(anchor) : spec.index(anchor) + 400]
    declared = tuple(sorted(set(re.findall(r"`(/[a-z/]+)`", criterion))))
    assert len(declared) == 2, f"Parsed {declared} from the criterion — the parse went trivial."
    assert declared == tuple(sorted(WRITABLE_PATHS)), (
        f"{SPEC_194.name} declares {declared}; this file expects {tuple(sorted(WRITABLE_PATHS))}."
    )
    assert own_declared == declared, (
        f"The two specs disagree: {SPEC_193.name} declares {own_declared}, {SPEC_194.name} "
        f"declares {declared}. One of them was edited alone."
    )

    text = _source()
    paths = re.search(r"writable_paths\s*=\s*\[([^\]]+)\]", text)
    assert paths, "No writable_paths local — the mounts are no longer derived from one list."
    from_local = tuple(sorted(re.findall(r'"([^"]+)"', paths.group(1))))

    assert from_local == tuple(sorted(declared)), (
        f"The module mounts {from_local}; the image spec declares {declared}. A mount set missing "
        "one of them produces a container that never starts, reported as a generic "
        "essential-container exit."
    )
    assert "for path in local.writable_paths" in _container_definition(), (
        "The mounts are hand-listed rather than derived from the writable_paths local."
    )

    # TMPFS, NOT A TASK VOLUME — measured, not preferred. A Fargate task volume arrives as an
    # empty root-owned directory and does not initialise from the image, so a container running
    # as a non-root user cannot write to it. A tmpfs is created owned by the uid its mount
    # options name, and that uid must be the one the container runs as.
    assert '"aws_ecs_task_definition"' in text and "volume {" not in _source_without_comments(), (
        "A task-level volume is back. It cannot give a non-root container a writable path: the "
        "mount arrives owned by root, and nginx dies on a permission error that reads as a "
        "container bug."
    )
    tmpfs = re.search(r"tmpfs\s*=\s*\[(.*?)\]\s*\n\s*\}", _container_definition(), re.DOTALL)
    assert tmpfs, "No tmpfs block — the writable paths have no mechanism at all."
    assert "uid=${local.container_uid}" in tmpfs.group(1), tmpfs.group(1)
    assert "gid=${local.container_uid}" in tmpfs.group(1), tmpfs.group(1)

    # The mount's owner and the container's user are ONE value. Split, a mount is silently
    # unwritable by the process that needs it — which is the failure this whole change is about.
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
