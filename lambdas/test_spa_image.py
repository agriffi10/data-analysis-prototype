"""The SPA image, and the agreements a response cannot observe.

The behaviour matrix in CI asserts what the container DOES — every header, every status, every
cache class, against a running container started the way ECS starts it. This file asserts the
things that are true of no single response: that the image and the task definition agree about a
port, a path, a uid and a writable set; that the policy the image bakes is the one Terraform
computes; and that the document the entrypoint renders is the one the browser is willing to read.

**Each of these applies green and fails somewhere else.** A health path the module does not probe
makes the balancer read `index.html`'s 200 and call every container healthy. A writable set the
task does not mount produces a container that never starts, reported as a generic
essential-container exit. A `version` literal that has drifted from the loader's ships a document
every browser refuses whole — a white screen, after a green deploy.

**What this file cannot prove.** These are text assertions over a Dockerfile, two nginx templates,
a shell script and some Terraform. That the rendered policy is what nginx emits, that the refusals
happen, that gzip_static serves the sibling — all of that is the matrix's, and it runs against a
real container.

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
  APP_CLOUDFRONT: The distribution's header policy, whose three custom header values the image
    must reproduce byte for byte.
  CONFIG_TYPES: The runtime-configuration classification.
  CONFIG_LOADER: Where the accepted document version is declared.
  WRITABLE_PATHS: The two paths, named here as a third copy on purpose — the assertion is an
    agreement between an image and a configuration, and a shared constant would prove nothing.
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
CONFIG_LOADER = ROOT / "apps" / "portal" / "src" / "lib" / "runtimeConfig.ts"

WRITABLE_PATHS = ("/tmp", "/var/cache/nginx")  # noqa: S108 — container paths, not host temp files


def _ts_string_array(text: str, name: str) -> tuple[str, ...]:
    """Returns the quoted members of an exported ``const <name> = [ … ] as const`` array.

    Args:
      text: The TypeScript source to read.
      name: The exported constant's name.

    Returns:
      Each member, unquoted, in declaration order.

    Read line by line rather than with one regex over the slice. These arrays are interleaved
    with comments, and a comment carrying an apostrophe — "the document's own defaults" — pairs
    with the next real quote and desynchronises every match after it, which yields a list of the
    gaps between the members rather than the members.

    Args:
      text: The TypeScript source to read.
      name: The exported constant's name.

    Returns:
      Each member, unquoted, in declaration order.

    Raises:
      AssertionError: When the constant or its closing bracket cannot be found, or a line inside
        it does not parse, so no comparison below runs against an empty tuple and passes.
    """
    start = text.find(f"export const {name} = [")
    assert start > -1, f"No `export const {name} = [` — the parse went trivial."
    end = text.find("]", start)
    assert end > start, f"`{name}` does not close where expected."

    members = []
    for raw in text[start:end].splitlines()[1:]:
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        member = re.fullmatch(r"'([^']+)',?", line)
        assert member, f"Unparsed line in {name}: {line!r}"
        members.append(member.group(1))
    return tuple(members)


def _shell_word_list(text: str, name: str) -> tuple[str, ...]:
    """Returns a single-quoted shell assignment's words, e.g. ``KEYS='a b c'``.

    Args:
      text: The shell source to read.
      name: The variable's name.

    Returns:
      The words, in order.

    Raises:
      AssertionError: When the assignment is absent, so no comparison runs vacuously.
    """
    found = re.search(rf"^{name}='([^']*)'", text, re.MULTILINE)
    assert found, f"No `{name}='…'` assignment in the entrypoint — the parse went trivial."
    return tuple(found.group(1).split())


def test_every_source_was_found() -> None:
    """Guards every assertion below: an empty read agrees with everything.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a file this suite does not own has moved or been renamed.
    """
    for path in (
        DOCKERFILE,
        NGINX_CONF,
        SERVER_TEMPLATE,
        HEADERS_TEMPLATE,
        ENTRYPOINT,
        MATRIX,
        PR_GATE,
        DEPLOY,
        SPA_ECS,
        SPA_VARIABLES,
        ROOT_MAIN,
        APP_CLOUDFRONT,
        CONFIG_TYPES,
        CONFIG_LOADER,
    ):
        assert path.exists(), f"{path} is gone; re-point this suite rather than deleting it."
        assert path.read_text().strip(), f"{path} is empty."


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


def test_the_health_endpoint_is_the_path_the_balancer_probes() -> None:
    """A mismatch means the balancer probes ``/``, reads the shell's 200, and never removes a task.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the served path and the probed path are not the same literal, or when
        the location is not an exact match.
    """
    probed = re.search(
        r'variable\s+"health_check_path"\s*\{.*?default\s*=\s*"([^"]+)"',
        SPA_VARIABLES.read_text(),
        re.DOTALL,
    )
    assert probed, "modules/spa no longer declares a health_check_path default."

    # EXACT MATCH, asserted as one claim with the path. As a prefix it is reachable by the
    # fallback, and a criterion that only checks "the path is /healthz" passes on a container with
    # no health endpoint whatsoever — the fallback answers 200 for everything.
    assert f"location = {probed.group(1)} {{" in SERVER_TEMPLATE.read_text(), (
        f"The image does not serve {probed.group(1)} as an EXACT-match location."
    )


def test_the_image_listens_where_the_task_definition_points() -> None:
    """The port is agreed in three places and the base image's own default is the fourth.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the listen port, the EXPOSE, or the module's default disagree.
    """
    declared = re.search(
        r'variable\s+"container_port"\s*\{.*?default\s*=\s*(\d+)', SPA_VARIABLES.read_text(), re.DOTALL
    )
    assert declared, "modules/spa no longer declares a container_port default."
    port = declared.group(1)

    assert f"listen {port};" in SERVER_TEMPLATE.read_text(), f"The server does not listen on {port}."
    assert f"EXPOSE {port}" in DOCKERFILE.read_text(), f"The image does not EXPOSE {port}."


def test_the_image_runs_as_the_uid_the_mounts_are_owned_by() -> None:
    """A tmpfs is created owned by the uid its mount options name; a different user cannot write it.

    That is the entire reason the mounts are tmpfs rather than task volumes, so the two values
    being one is what the mechanism rests on.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the image's final USER differs from the task's container uid.
    """
    task_uid = re.search(r'container_uid\s*=\s*"(\d+)"', SPA_ECS.read_text())
    assert task_uid, "modules/spa no longer names the container uid in one place."

    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE.read_text(), re.MULTILINE)
    assert users, "The Dockerfile declares no USER at all — the container would run as root."
    assert users[-1] == task_uid.group(1), (
        f"The image ends as USER {users[-1]}; the task mounts are owned by {task_uid.group(1)}. "
        "The mount would be silently unwritable by the process that has to write it."
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


def test_the_three_custom_headers_match_the_distribution_byte_for_byte() -> None:
    """Retyped from memory, these drift silently; read from the file, they cannot.

    Both delivery paths run side by side for the length of this arc, so a value that differs
    between them is a real difference in what a browser enforces depending on which origin served
    the page.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any of the three differs from the distribution's.
    """
    distribution = APP_CLOUDFRONT.read_text()
    image = HEADERS_TEMPLATE.read_text()

    for header in ("Permissions-Policy", "Cross-Origin-Opener-Policy", "Cross-Origin-Resource-Policy"):
        theirs = re.search(
            rf'header\s+=\s+"{header}"\s*\n\s*value\s+=\s+"([^"]+)"', distribution
        )
        assert theirs, f"The distribution no longer sets {header}; re-point this rather than deleting it."

        ours = re.search(rf'add_header {header} "([^"]+)"', image)
        assert ours, f"The image does not set {header}."
        assert ours.group(1) == theirs.group(1), (
            f"{header} differs between the two delivery paths.\n"
            f"  distribution: {theirs.group(1)}\n  image:        {ours.group(1)}"
        )


def test_the_embedder_policy_stays_absent_and_hsts_claims_no_preload() -> None:
    """Two decisions that a later reader would most naturally "fix".

    ``require-corp`` buys cross-origin isolation this app cannot use, at real risk to subresource
    loads, so its scanner alert stays open by decision. ``preload`` claims an hstspreload.org
    submission this deployment has not made, against a registrable domain it does not own.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either reappears anywhere in the image's configuration.
    """
    for source in (HEADERS_TEMPLATE, SERVER_TEMPLATE, NGINX_CONF):
        text = "\n".join(
            line for line in source.read_text().splitlines() if not line.lstrip().startswith("#")
        )
        assert "Cross-Origin-Embedder-Policy" not in text, (
            f"{source.name} sets COEP. It is absent by decision; revisit the decision rather than "
            "adding the header to clear a scanner Low."
        )
        assert "preload" not in text, (
            f"{source.name} claims HSTS preload, which this deployment has not submitted and does "
            "not intend to."
        )


def test_every_location_includes_the_shared_header_snippet() -> None:
    """nginx wipes inherited headers from any level that sets one of its own.

    Each location here sets its own ``Cache-Control``, which on its own removes every security
    header from that location's responses while the rest of the site looks perfect. The matrix
    proves it on responses; this catches a location added later that forgets, at the point it is
    written.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any location block omits the include, or any add_header omits `always`.
    """
    text = SERVER_TEMPLATE.read_text()
    blocks = re.findall(r"^\s{4}location\s+([^{]+)\{(.*?)^\s{4}\}", text, re.MULTILINE | re.DOTALL)
    assert len(blocks) >= 5, f"Parsed {len(blocks)} location blocks — the parse went trivial."

    for label, body in blocks:
        assert "include /tmp/nginx-conf/snippets/security-headers.conf;" in body, (
            f"location {label.strip()} does not include the shared header snippet. Its whole "
            "response class would carry no CSP at all, with every other class perfect."
        )
        assert "add_header Cache-Control" in body, (
            f"location {label.strip()} sets no Cache-Control. An absent header is the original "
            "bug: browsers then apply heuristic freshness."
        )

    # `always`, without which add_header applies only to a short list of success and redirect
    # codes — so the honest 404 loses the entire set. Measured, not assumed.
    for source in (SERVER_TEMPLATE, HEADERS_TEMPLATE):
        for line in source.read_text().splitlines():
            if line.lstrip().startswith("add_header"):
                assert line.rstrip().endswith("always;"), (
                    f"{source.name} has an add_header without `always`: {line.strip()}\n"
                    "Non-2xx responses would carry none of the set."
                )


def test_the_base_images_default_site_cannot_win() -> None:
    """Two servers on one port, and the first parsed becomes the default.

    The base image ships a default site that also listens on 8080 and sets no security header at
    all. Both halves are asserted, because either alone leaves the outcome to include ordering.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the file is not removed, or the conf.d include survives.
    """
    assert "rm -f /etc/nginx/conf.d/default.conf" in DOCKERFILE.read_text(), (
        "The base image's default site is still in the image."
    )
    conf = "\n".join(
        line for line in NGINX_CONF.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    assert "conf.d" not in conf, "nginx.conf still includes conf.d, where the base's default site lives."
    assert "include /tmp/nginx-conf/*.conf;" in conf, "nginx.conf includes no rendered configuration."


def test_the_entrypoint_renders_exactly_the_classified_keys() -> None:
    """A key missing here ships a container whose document lacks it, with every other leg green.

    The entrypoint is the sixth place the runtime-configuration key set is wired, and the one that
    will produce the served document after the cutover.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the rendered set or the required set differs from the classification.
    """
    types = CONFIG_TYPES.read_text()
    required = _ts_string_array(types, "REQUIRED_CONFIG")
    optional = _ts_string_array(types, "OPTIONAL_CONFIG")
    assert len(required) + len(optional) > 10, "The classification parsed nearly empty."

    entrypoint = ENTRYPOINT.read_text()
    assert sorted(_shell_word_list(entrypoint, "KEYS")) == sorted(required + optional), (
        "The entrypoint renders a different key set from the one the browser classifies."
    )
    # NAMED, never scooped. A bare CONFIG_* sweep publishes whatever same-prefixed variable an
    # orchestrator or a base image introduces — into a world-readable document.
    assert sorted(_shell_word_list(entrypoint, "REQUIRED")) == sorted(required), (
        "The entrypoint's required set differs from the classification's. Too few and it starts "
        "serving a document that cannot boot; too many and a healthy deployment refuses to start."
    )


def test_the_rendered_version_is_the_one_the_browser_accepts() -> None:
    """The loader refuses a document whose version differs — it does not guess.

    So a schema bump that raises the loader's constant and leaves this one behind ships a container
    every browser rejects whole: a white screen, after a deploy that was green everywhere.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the two literals differ.
    """
    accepted = re.search(r"const SUPPORTED_VERSION = (\d+);", CONFIG_LOADER.read_text())
    assert accepted, "The loader no longer declares SUPPORTED_VERSION."

    rendered = re.search(r"^VERSION=(\d+)", ENTRYPOINT.read_text(), re.MULTILINE)
    assert rendered, "The entrypoint no longer declares the document version it renders."

    assert rendered.group(1) == accepted.group(1), (
        f"The container renders version {rendered.group(1)}; the browser accepts only "
        f"{accepted.group(1)} and refuses anything else whole."
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


def test_the_render_substitutes_only_what_it_declares() -> None:
    """Given no list, envsubst replaces every variable it finds a definition for.

    A task definition carrying a variable named ``uri`` or ``host`` would then blank the nginx
    runtime variables of the same name and break routing, with nothing wrong in the configuration
    a reviewer would open.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When envsubst is invoked without an explicit variable list.
    """
    text = ENTRYPOINT.read_text()
    declared = re.search(r"^SUBSTITUTE='([^']+)'", text, re.MULTILINE)
    assert declared, "The entrypoint does not declare which variables it substitutes."

    invocations = re.findall(r"^\s*envsubst\s+(\S+)", text, re.MULTILINE)
    assert invocations, "The entrypoint invokes envsubst nowhere — the parse went trivial."
    for invocation in invocations:
        assert invocation == '"$SUBSTITUTE"', (
            f"envsubst is invoked as `envsubst {invocation}` — anything but the declared list "
            "substitutes every defined variable, nginx's own among them."
        )


def test_the_task_definition_overrides_no_command() -> None:
    """The base entrypoint runs its scripts only when its first argument is ``nginx``.

    A ``command`` on the container definition skips every one of them silently — no rendered
    configuration and no document — and an ``include`` matching zero files is not an nginx error.
    The container would start clean and serve nothing at all.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the container definition carries a command or an entryPoint override.
    """
    body = "\n".join(
        line for line in SPA_ECS.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    for override in ("command", "entryPoint"):
        assert not re.search(rf"^\s*{override}\s*=", body, re.MULTILINE), (
            f"The task definition sets {override}. The image's entrypoint scripts would not run, "
            "and the container would start clean serving no configuration at all."
        )


def test_the_pipeline_tags_by_commit_sha_and_never_mutably() -> None:
    """``latest`` makes the running revision unidentifiable and a rollback a rebuild.

    "Which commit is in production" is the question the whole stamping mechanism exists to answer,
    and a mutable tag makes it unanswerable — the registry is configured immutable partly so this
    cannot be done by accident, but a workflow can still ask.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any mutable tag appears, or the build does not stamp the sha.
    """
    text = DEPLOY.read_text()
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    assert ":latest" not in body and "latest\"" not in body, (
        "The deploy workflow names a `latest` tag somewhere."
    )
    assert "--build-arg BUILD_VERSION=" in body, "The build does not stamp BUILD_VERSION."
    assert "GITHUB_SHA" in body, "The tag is not derived from the commit sha."


def test_the_pipeline_proves_the_image_before_it_pushes() -> None:
    """A wrong cache header must never reach a registry it cannot be deleted from.

    The repository is immutable, so a bad image cannot be replaced at its tag — only superseded by
    a new commit. Running the gate after the push would make every failure permanent.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the matrix does not run, or does not run before the push.
    """
    text = DEPLOY.read_text()
    assert "spa-image-matrix.sh" in text, "The deploy pipeline never runs the behaviour matrix."

    matrix_at = text.index("spa-image-matrix.sh")
    push_at = text.index("docker push")
    assert matrix_at < push_at, (
        "The matrix runs after the push. The registry is immutable, so a bad image cannot be "
        "replaced at its tag."
    )


def test_the_deploy_waits_and_refuses_to_pass_on_a_vacuous_wait() -> None:
    """``update-service`` returns the moment the API accepts the request.

    So a container that crashes at start leaves the workflow green over a service still running
    last week's image. Waiting is what makes a bad image able to fail a deploy — and the wait is
    itself vacuous at a desired count of zero, where it returns instantly and the service reports
    the revision that was just set.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the wait, the zero-count guard or the settled-revision check is absent.
    """
    text = DEPLOY.read_text()

    assert "wait services-stable" in text, (
        "The pipeline does not wait, so a rolled-back deployment reports success."
    )
    assert 'desired" -eq 0' in text, (
        "Nothing refuses a desired count of zero, where every check below it is vacuous: the wait "
        "returns instantly and a deliberately broken image deploys green."
    )
    # THE ONE THAT CATCHES A ROLLBACK. A rolled-back service is stable and healthy — running the
    # PREVIOUS image — so stability alone is not evidence that this run's image is live.
    assert 'primary" != "$ARN"' in text, (
        "Nothing compares the settled revision with the one this run registered, so a rollback "
        "reads as a successful deploy."
    )


def test_the_deploy_clones_the_family_not_the_running_revision() -> None:
    """After a rollback the service points at an OLDER revision, and cloning it reverts config.

    The environment block is Terraform's, derived from the runtime-configuration map. Cloning a
    stale revision silently drops whatever was last added to it — a configuration key or a CSP
    term — and the deploy is green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the clone reads the service's revision, or does not verify the
        configuration survived.
    """
    text = DEPLOY.read_text()
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    assert 'describe-task-definition --task-definition "$FAMILY"' in body, (
        "The clone does not read the family's newest revision by name."
    )
    assert "services[0].taskDefinition" not in body, (
        "The clone reads the revision the SERVICE is running, which after a rollback is stale."
    )
    # The register call refuses these, with a parameter error that reads as a malformed request.
    for read_only in ("taskDefinitionArn", "requiresAttributes", "compatibilities", "registeredAt"):
        assert read_only in body, f"The clone does not strip {read_only}, which register rejects."
    assert 'startswith("CONFIG_")' in body, (
        "Nothing checks the cloned revision still carries the runtime-configuration block. A "
        "container missing part of its document refuses to start, and the workflow would report "
        "only that the deployment failed."
    )


def test_both_workflows_build_for_the_architecture_the_task_declares() -> None:
    """An arm64 image fails at task start with a manifest error that reads nothing like one.

    The runner is amd64 today, which is exactly what makes leaving this unwritten dangerous: it
    works until the day the runner image changes.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either workflow builds without naming the platform.
    """
    for workflow in (PR_GATE, DEPLOY):
        assert "--platform linux/amd64" in workflow.read_text(), (
            f"{workflow.name} builds without naming the platform."
        )


def test_the_deploy_is_serialized_and_never_cancelled_mid_flight() -> None:
    """Two overlapping deploys of one service is last-writer-wins.

    And cancelling one mid-flight leaves a half-rolled service, which is worse than the queueing it
    saves — the same reasoning the static-site deploy carries.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the workflow is unserialized or cancels in progress.
    """
    text = DEPLOY.read_text()
    assert "concurrency:" in text, "The deploy is not serialized."
    assert "cancel-in-progress: false" in text, (
        "The deploy cancels in-flight runs, which leaves a service half-rolled."
    )


def test_the_static_site_deploy_is_untouched() -> None:
    """Both delivery paths run side by side for the length of this transition, deliberately.

    The distribution stays the working portal while the container is being proved, so anything
    that stops it deploying turns a rollback into an outage.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the static-site workflow stops deploying on every push to main.
    """
    static = ROOT / ".github" / "workflows" / "deploy-app.yml"
    text = static.read_text()
    assert "branches: [main]" in text, (
        "deploy-app.yml no longer deploys on pushes to main. It is the working portal and the "
        "rollback for this whole transition."
    )
    assert "aws s3 sync" in text, "deploy-app.yml no longer publishes the bundle."
