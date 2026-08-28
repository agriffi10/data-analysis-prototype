"""The SPA image, and the agreements a response cannot observe.

Text assertions over a Dockerfile, two nginx templates, a shell script and some Terraform: the
image and the task definition must agree about a port, a health path, a uid and a writable set,
and the rendered document must carry the version the loader accepts. Which of these apply green
and fail elsewhere, and what the behaviour matrix owns instead, is in
``infra/modules/spa/README.md``.

Attributes:
  ROOT: The repository root.
  DOCKERFILE: The image's definition.
  NGINX_CONF: The main configuration, which must not include the base image's default site.
  SERVER_TEMPLATE: The server block, rendered at container start.
  HEADERS_TEMPLATE: The shared snippet every location includes.
  ENTRYPOINT: The script that refuses, then renders.
  MATRIX: The behaviour gate, asserted to exist and to be wired.
  PR_GATE: The pull-request workflow that runs the matrix before merge.
  DEPLOY: The pipeline that builds, proves, pushes and points the service.
  SPA_ECS: The task definition whose port, uid and mounts the image must agree with.
  SPA_VARIABLES: Where the health path and container port defaults live.
  ROOT_MAIN: Where the assembled policy is computed.
  APP_CLOUDFRONT: The distribution's header policy, reproduced byte for byte.
  CONFIG_TYPES: The runtime-configuration classification.
  CONFIG_LOADER: Where the accepted document version is declared.
  WRITABLE_PATHS: The two paths, a third copy on purpose — a shared constant would prove nothing.
"""

import pathlib
import re

from tf_blocks import join_list_items

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "apps" / "portal" / "Dockerfile"
NGINX_CONF = ROOT / "apps" / "portal" / "docker" / "nginx.conf"
SERVER_TEMPLATE = ROOT / "apps" / "portal" / "docker" / "portal" / "default.conf.template"
HEADERS_TEMPLATE = (
    ROOT / "apps" / "portal" / "docker" / "portal" / "snippets" / "security-headers.conf.template"
)
ENTRYPOINT = (
    ROOT
    / "apps"
    / "portal"
    / "docker"
    / "docker-entrypoint.d"
    / "40-render-portal-config.sh"
)
MATRIX = ROOT / ".github" / "scripts" / "spa-image-matrix.sh"
PR_GATE = ROOT / ".github" / "workflows" / "spa-image.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-spa-image.yml"
SPA_ECS = ROOT / "infra" / "modules" / "spa" / "ecs.tf"
SPA_VARIABLES = ROOT / "infra" / "modules" / "spa" / "variables.tf"
ROOT_MAIN = ROOT / "infra" / "main.tf"
APP_CLOUDFRONT = ROOT / "infra" / "modules" / "app" / "cloudfront.tf"
CONFIG_TYPES = ROOT / "apps" / "portal" / "src" / "types" / "runtimeConfig.types.ts"
MATRIX_SCRIPT = ROOT / ".github" / "scripts" / "spa-image-matrix.sh"
CONFIG_LOADER = ROOT / "apps" / "portal" / "src" / "lib" / "runtimeConfig.ts"

WRITABLE_PATHS = ("/tmp", "/var/cache/nginx")  # noqa: S108 — container paths, not host temp files


def test_the_image_writes_only_where_the_task_mounts() -> None:
    """A mount set missing one of these produces a container that never starts.

    And it reports as a generic essential-container exit, which during this arc's one verification
    is indistinguishable from the image-pull failure the whole no-NAT platform is tested by. The
    two halves are written in different repositories' worth of language — a Dockerfile and some
    HCL — so nothing but an assertion holds them together.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the image's declared writable pair differs from the task's mounts.
    """
    module = re.search(r"writable_paths\s*=\s*\[([^\]]+)\]", SPA_ECS.read_text())
    assert module, "No writable_paths local — the mounts are no longer derived from one list."
    mounted = tuple(sorted(re.findall(r'"([^"]+)"', module.group(1))))

    assert mounted == tuple(sorted(WRITABLE_PATHS)), (
        f"The task mounts {mounted}; the image is built to write {tuple(sorted(WRITABLE_PATHS))}."
    )

    # The image's own statement of the same pair. nginx's temp paths and the rendered output are
    # the only writes it makes, and both must land inside that set.
    conf = NGINX_CONF.read_text()
    for temp_path in re.findall(r"^\s*\w+_temp_path\s+(\S+);", conf, re.MULTILINE):
        assert temp_path.startswith(WRITABLE_PATHS), (
            f"nginx writes {temp_path}, which is not under a mounted path — the container dies at "
            "start on a permission error that reads as a container bug."
        )
    assert re.search(r"^\s*pid\s+/tmp/", conf, re.MULTILINE), (
        "The pid file is not under /tmp, which is the only writable path nginx has at start."
    )


def test_the_baked_policy_is_the_one_terraform_computes() -> None:
    """Every directive but ``connect-src``, byte for byte, against the root local.

    The seam: ``connect-src`` describes the ENVIRONMENT and arrives from the task definition, so
    the image must not carry it; every other directive describes the bundle and ships baked. Two
    copies of the same policy in two languages is exactly the drift a CSP is worst at showing —
    nothing observes one offline, and the symptom is one feature failing in one browser days later.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the image's directives differ from Terraform's, or when the image bakes
        a connect-src of its own.
    """
    separator, computed = join_list_items(ROOT_MAIN.read_text(), "content_security_policy")
    assert computed, "Terraform computes no policy — the parse went trivial."

    baked = re.search(r'add_header Content-Security-Policy "([^"]+)"', HEADERS_TEMPLATE.read_text())
    assert baked, "The image's snippet emits no Content-Security-Policy at all."
    emitted = tuple(directive.strip() for directive in baked.group(1).split(separator.strip()))

    expected = tuple(
        "connect-src ${PORTAL_CSP_CONNECT_SRC}"
        if directive.startswith("connect-src")
        else directive
        for directive in computed
    )
    assert emitted == expected, (
        "The image's policy and Terraform's have drifted.\n"
        f"  terraform: {expected}\n  image:     {emitted}\n"
        "Every directive but connect-src is a property of the bundle and must be identical; "
        "connect-src is the one the task definition supplies."
    )

    # The environment must not be frozen into the image. A baked connect-src carries one
    # deployment's hosts everywhere, which is the build-time-configuration failure the runtime
    # document exists to end.
    assert "${PORTAL_CSP_CONNECT_SRC}" in baked.group(1), (
        "The image bakes a literal connect-src instead of taking it from the task definition."
    )


def test_the_entrypoint_refuses_unset_and_empty_alike() -> None:
    """`[ -z "${VAR+x}" ]` passes the empty case, and empty is the case that actually happens.

    An unset repository variable, an unset Terraform input and an unsubstituted expansion all
    arrive as the empty string. A container that starts with an empty required value serves a
    shell that fails every call it makes.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the check tests only for unset, or does not exit non-zero.
    """
    # Comments dropped first. The script EXPLAINS the check it does not use, and a raw scan reads
    # that sentence as the violation it warns against.
    text = "\n".join(
        line for line in ENTRYPOINT.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    assert "+x}" not in text, (
        "The entrypoint tests for UNSET only. Empty is the case that reaches production."
    )
    assert re.search(r'\[ -n "\$value" \]', text), (
        "The entrypoint does not test required values for non-emptiness."
    )
    assert "exit 1" in text, "The entrypoint never exits non-zero, so nginx starts regardless."


