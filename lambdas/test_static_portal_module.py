"""The static portal must serve what the container serves, and exactly one of them may exist.

Nothing offline observes a response header, so the two delivery paths are held together here. The
reasoning is in ``infra/modules/static-portal/README.md``.

Attributes:
  INFRA: The IaC tree.
  MODULE: The static portal module's directory.
  CLOUDFRONT: Its distribution and response headers policy.
  S3: Its bucket and the runtime configuration object.
  ROOT_MAIN: The root composition.
  GRANT: The deploy-role policy scoping the bucket by name.
  NGINX_HEADERS: The container's security headers, the posture this module has to match.
  NAMED_HEADERS: The headers each path sets as a plain name and value.
"""

import pathlib
import re

from tf_blocks import blocks, module_calls, span

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
MODULE = INFRA / "modules" / "static-portal"
CLOUDFRONT = MODULE / "cloudfront.tf"
S3 = MODULE / "s3.tf"
ROOT_MAIN = INFRA / "main.tf"
GRANT = (
    INFRA
    / "modules"
    / "base"
    / "policies"
    / "github-actions-deploy-portal-static.json.tftpl"
)
NGINX_HEADERS = (
    INFRA.parent
    / "apps"
    / "portal"
    / "docker"
    / "portal"
    / "snippets"
    / "security-headers.conf.template"
)
NAMED_HEADERS = (
    "Permissions-Policy",
    "Cross-Origin-Opener-Policy",
    "Cross-Origin-Resource-Policy",
)


def _nginx_header(name: str) -> str:
    """Read one header's value out of the container's snippet.

    Args:
      name: The header's name.

    Returns:
      The value nginx serves.

    Raises:
      AssertionError: When the snippet does not set that header.
    """
    match = re.search(
        rf'^add_header {re.escape(name)} "([^"]*)" always;',
        NGINX_HEADERS.read_text(),
        re.MULTILINE,
    )
    assert match, f"{name} is not in the container's snippet"
    return match.group(1)


def test_the_custom_headers_match_the_container() -> None:
    """Each header set by name carries nginx's value, byte for byte.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a value differs or a header is missing from the policy.
    """
    text = CLOUDFRONT.read_text()
    for name in NAMED_HEADERS:
        match = re.search(
            rf'header\s+= "{re.escape(name)}"\s+value\s+= "([^"]*)"', text
        )
        assert match, f"{name} is not in the response headers policy"
        assert match.group(1) == _nginx_header(name), (
            f"{name} differs from the container's"
        )


def test_hsts_matches_the_container_and_claims_no_preload() -> None:
    """The age and subdomain scope agree with nginx, and neither path claims a preload submission.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the max age, subdomain scope or preload setting disagrees.
    """
    served = _nginx_header("Strict-Transport-Security")
    assert served == "max-age=31536000; includeSubDomains"
    text = CLOUDFRONT.read_text()
    assert re.search(r"access_control_max_age_sec = 31536000\b", text)
    assert re.search(r"include_subdomains\s+= true\b", text)
    assert re.search(r"preload\s+= false\b", text)


def test_the_browser_policies_match_the_container() -> None:
    """Framing and referrer agree with nginx, and the CSP is root's, not a copy.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a value differs, or the policy stops reading the root computation.
    """
    text = CLOUDFRONT.read_text()
    assert f'frame_option = "{_nginx_header("X-Frame-Options")}"' in text
    assert f'referrer_policy = "{_nginx_header("Referrer-Policy")}"' in text
    assert "content_security_policy = var.content_security_policy" in text
    call = module_calls(ROOT_MAIN.read_text())["static_portal"]
    assert re.search(
        r"content_security_policy\s+= local\.content_security_policy\b", call
    )


def test_every_behaviour_attaches_the_headers_and_config_is_never_cached() -> None:
    """Both cache behaviours name the policy, and config.json takes the disabled cache policy.

    A response headers policy is per behaviour, so one left off serves that path with no CSP.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a behaviour lacks the policy, or config.json can be edge cached.
    """
    distribution = blocks(CLOUDFRONT.read_text(), "aws_cloudfront_distribution")[
        "portal"
    ]
    default = span(distribution, distribution.index("default_cache_behavior"))
    ordered = span(distribution, distribution.index("ordered_cache_behavior"))
    for behaviour in (default, ordered):
        assert (
            "response_headers_policy_id = aws_cloudfront_response_headers_policy.portal.id"
            in behaviour
        )
    assert 'path_pattern               = "config.json"' in ordered
    assert "cache_policy_id            = local.caching_disabled_policy_id" in ordered


def test_the_runtime_document_is_no_store_and_versioned() -> None:
    """The object carries the loader's version and the cache header the loader's contract needs.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the object can be cached, or the loader would refuse its version.
    """
    body = blocks(S3.read_text(), "aws_s3_object")["runtime_config"]
    assert 'cache_control = "no-store"' in body
    assert "{ version = 1 }" in body


def test_exactly_one_delivery_path_exists() -> None:
    """The static portal's count is the inverse of the web tier's.

    Two records for one name, or none, is a portal that does not resolve.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the two modules' counts are not each other's opposite.
    """
    calls = module_calls(ROOT_MAIN.read_text())
    assert "count  = local.web_tier_enabled ? 1 : 0" in calls["spa"]
    assert "count  = local.web_tier_enabled ? 1 : 0" in calls["network"]
    assert "count  = local.web_tier_enabled ? 0 : 1" in calls["static_portal"]


def test_the_bucket_name_is_inside_the_deploy_grant() -> None:
    """The bucket's name matches the pattern the deploy role is granted.

    A bucket named outside the grant applies as far as CreateBucket and then fails AccessDenied.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the name and the grant disagree.
    """
    assert (
        'bucket        = "${var.project_name}-${var.environment}-portal-static"'
        in S3.read_text()
    )
    assert "arn:aws:s3:::${project_name}-*-portal-static" in GRANT.read_text()


def test_the_deploy_runs_only_while_the_tier_is_off_and_names_the_module_bucket() -> (
    None
):
    """The workflow's gate is the static side of the switch, and its bucket is the module's.

    Inverted, the deploy fails every push with the tier on and leaves the portal unbuilt with it
    off, while the skip reads as passing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the gate or the bucket's name disagrees with the module.
    """
    workflow = (
        INFRA.parent / ".github" / "workflows" / "deploy-spa-static.yml"
    ).read_text()
    assert "if: vars.TF_VAR_web_tier_enabled == 'false'" in workflow
    assert "BUCKET=dat-prod-portal-static\n" in workflow
