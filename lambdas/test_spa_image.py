"""The portal image's agreements with the task definition that runs it.

Text assertions over a Dockerfile, two TypeScript modules and some Terraform: the parts written in
different languages that nothing but an assertion holds together. What the running container does
is the behaviour matrix's job (``.github/scripts/spa-image-matrix.sh``), which reads responses.

Attributes:
  ROOT: The repository root.
  DOCKERFILE: The image's definition.
  SPA_ECS: The task definition.
  PROXY: The request proxy, which emits the page policy.
  SERVER_DOCUMENT: The server module the proxy reads ``connect-src`` through.
  WRITABLE_PATHS: The one path the image writes, a second copy on purpose: a shared constant would
    prove nothing.
  CONTAINER_UID: The image's user, stated here for the same reason.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "apps" / "portal" / "Dockerfile"
SPA_ECS = ROOT / "infra" / "modules" / "spa" / "ecs.tf"
PROXY = ROOT / "apps" / "portal" / "src" / "proxy.ts"
SERVER_DOCUMENT = ROOT / "apps" / "portal" / "src" / "server" / "runtimeDocument.ts"

WRITABLE_PATHS = ("/tmp",)  # noqa: S108 — a container path, not a host temp file
CONTAINER_UID = "1000"


def test_the_image_and_the_task_agree_on_the_user() -> None:
    """A tmpfs mounted for one uid is silently unwritable by a process running as another.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the image's final user and the task's uid differ, or either is root.
    """
    users = re.findall(r"^USER\s+(\S+)\s*$", DOCKERFILE.read_text(), re.MULTILINE)
    assert users, "The Dockerfile declares no USER, so the image runs as root."
    assert users[-1] == CONTAINER_UID, f"The image's final user is {users[-1]}, not {CONTAINER_UID}."

    uid = re.search(r'container_uid\s*=\s*"(\d+)"', SPA_ECS.read_text())
    assert uid, "No container_uid local in the task definition."
    assert uid.group(1) == CONTAINER_UID, (
        f"The task runs as uid {uid.group(1)}; the image is built to run as {CONTAINER_UID}."
    )


def test_the_task_mounts_exactly_what_the_image_writes() -> None:
    """The Node server writes only to its temp directory; the root filesystem is read-only.

    A path the image writes that is not mounted is a container that dies on a permission error
    reading as a container bug. A path mounted that nothing writes is a leftover from the image
    this replaced, and it is how the nginx cache mount would have outlived nginx.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the task's mounts differ from the image's writable set.
    """
    paths = re.search(r"writable_paths\s*=\s*\[([^\]]+)\]", SPA_ECS.read_text())
    assert paths, "No writable_paths local — the mounts are no longer derived from one list."
    mounted = tuple(sorted(re.findall(r'"([^"]+)"', paths.group(1))))

    assert mounted == WRITABLE_PATHS, f"The task mounts {mounted}; the image writes {WRITABLE_PATHS}."
    assert re.search(r"readonlyRootFilesystem\s*=\s*true", SPA_ECS.read_text()), (
        "The root filesystem is writable, so a write outside the mounts would succeed silently."
    )


def test_connect_src_comes_from_the_task_definition_and_nothing_else() -> None:
    """The one environment-shaped directive must not be frozen into the image.

    A baked ``connect-src`` carries one deployment's hosts everywhere, which is the build-time
    configuration failure the runtime document exists to end. So the task definition supplies it,
    the server reads that variable, and the proxy names no host of its own.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the task stops supplying the variable, the server stops reading it, or
        the proxy carries a literal source list.
    """
    assert re.search(
        r'name\s*=\s*"PORTAL_CSP_CONNECT_SRC"\s*\n\s*value\s*=\s*var\.csp_connect_src', SPA_ECS.read_text()
    ), "The task definition no longer supplies PORTAL_CSP_CONNECT_SRC from root's computation."
    assert "'PORTAL_CSP_CONNECT_SRC'" in SERVER_DOCUMENT.read_text(), (
        "The server no longer reads PORTAL_CSP_CONNECT_SRC."
    )
    proxy = PROXY.read_text()
    assert "connectSource()" in proxy, "The proxy no longer reads connect-src through the server."
    assert not re.search(r"https://[a-z0-9.-]+\.(amazonaws\.com|amazoncognito\.com)", proxy), (
        "The proxy carries a literal AWS host, which bakes one environment into the image."
    )
