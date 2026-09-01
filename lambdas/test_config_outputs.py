"""The one declared map from Terraform output name to runtime-configuration key.

Terraform computes these values; before this map existed a human read them out of ``tofu
output`` once and typed them into a repository settings page, and every one of them could
then go stale in the browser while infrastructure moved on. The map is what makes the
deploy read them instead, so it is the file that must not drift — a new hand-maintained
copy in place of the old one would be the same defect wearing a commit.

Four of the assertions here bind it to something that already exists: the browser's
classification, ``infra/outputs.tf``, and the container entrypoint's own key lists. The
fifth binds the deploy role, because the whole change rests on the claim that reading
remote state needs no new grant, and a claim nobody asserts is a claim that quietly stops
being true.

Attributes:
  ROOT: The repository root.
  MAPPING: The map under test.
  CONFIG_TYPES: The browser's runtime-configuration classification.
  OUTPUTS: The Terraform output declarations the map's left column must exist in.
  ENTRYPOINT: The container script that renders the served document.
  DEPLOY_POLICY: The deploy role's policy template.
  GENUINE_INPUTS: The two configuration keys no resource can tell you, which stay
    repository variables and are therefore absent from the map by design.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAPPING = ROOT / ".github" / "config-outputs.json"
CONFIG_TYPES = ROOT / "apps" / "portal" / "src" / "types" / "runtimeConfig.types.ts"
OUTPUTS = ROOT / "infra" / "outputs.tf"
ENTRYPOINT = (
    ROOT / "apps" / "portal" / "docker" / "docker-entrypoint.d" / "40-render-portal-config.sh"
)
DEPLOY_POLICY = (
    ROOT / "infra" / "modules" / "base" / "policies" / "github-actions-deploy.json.tftpl"
)

GENUINE_INPUTS = frozenset({"environment", "maxUploadBytes"})


def _mapping() -> dict[str, str]:
    """Reads the map, refusing an empty one so no comparison below can pass vacuously.

    Returns:
      Terraform output name to configuration key.

    Raises:
      AssertionError: If the map is empty, which every set comparison here would
        otherwise report as agreement with an equally empty other side.
    """
    loaded = json.loads(MAPPING.read_text())
    assert loaded, "config-outputs.json is empty — every comparison here would be vacuous"
    return loaded


def _ts_string_array(source: str, name: str) -> list[str]:
    """Reads a ``const NAME = [...] as const`` array of string literals.

    Restated here rather than imported from ``test_spa_image.py``, which parses the same
    two declarations for the container's own agreements. A suite that imported its
    subject's reader could pass by agreeing with a mistake it inherited, and these are
    the assertions that decide whether a deploy publishes the right document.

    Comments are stripped before the literal sweep: the classification's blocks carry
    prose about each key's degraded path, and one of them quotes a status value that a
    raw sweep would read as a configuration key.

    Args:
      source: The TypeScript module's text.
      name: The exported const to read.

    Returns:
      The string literals, in declaration order.

    Raises:
      AssertionError: If the declaration is absent or holds no literal.
    """
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.DOTALL)
    assert match, f"no {name} declaration found — this comparison has no subject"

    body = re.sub(r"//[^\n]*", "", match.group(1))
    literals = re.findall(r"'([A-Za-z][A-Za-z0-9]*)'", body)
    assert literals, f"{name} declares no key"
    return literals


def _shell_word_list(source: str, name: str) -> list[str]:
    """Reads a single-quoted space-separated shell assignment into a list.

    Args:
      source: The shell script's text.
      name: The variable to read, e.g. ``KEYS``.

    Returns:
      The words assigned, in declaration order.

    Raises:
      AssertionError: If the assignment is absent or empty, so a parser that matched
        nothing cannot report an empty list as agreement.
    """
    match = re.search(rf"^{name}='([^']+)'", source, re.MULTILINE)
    assert match, f"no {name}= assignment found in the entrypoint — this has no subject"
    words = match.group(1).split()
    assert words, f"{name} is empty"
    return words


def _derived_config_keys() -> set[str]:
    """The configuration keys Terraform is expected to supply.

    Every classified key minus the two genuine inputs. Deliberately not
    ``REQUIRED_CONFIG`` alone: that set is smaller, and a map trimmed to satisfy such a
    comparison would stop rendering the optional keys into the document — a portal that
    boots, reports ready, and has one feature silently unconfigured.

    Returns:
      The configuration keys the map must carry, exactly.

    Raises:
      AssertionError: If the classification parses to nothing.
    """
    source = CONFIG_TYPES.read_text()
    classified = set(_ts_string_array(source, "REQUIRED_CONFIG")) | set(
        _ts_string_array(source, "OPTIONAL_CONFIG")
    )
    assert "apiBaseUrl" in classified, (
        "the classification parsed without apiBaseUrl — the parse is broken, not the map"
    )
    return classified - GENUINE_INPUTS


def test_the_map_carries_every_configuration_key_terraform_supplies() -> None:
    """The map and the classification are one set, and drift either way is a defect.

    A key classified but unmapped ships a document without it. A key mapped but no longer
    classified renders a value the browser ignores today and would resurrect wrongly the
    day something classifies that name again.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two sets differ, either way.
    """
    mapping = _mapping()

    # SET EQUALITY CANNOT SEE A DUPLICATE. Two outputs mapped to one configuration key
    # collapse to one element here and pass, while the resolver writes that key twice and
    # GitHub silently keeps the last — so which output won would depend on file order.
    duplicated = sorted({key for key in mapping.values() if list(mapping.values()).count(key) > 1})
    assert duplicated == [], f"configuration keys mapped from more than one output: {duplicated}"

    assert set(mapping.values()) == _derived_config_keys()


def test_every_mapped_output_is_declared_in_terraform() -> None:
    """A renamed output fails here, at test time, rather than mid-deploy.

    The failure this replaces was a value that resolved to nothing and reached AWS as a
    malformed request far from its cause, so the whole point of the map is that its left
    column is checked against something rather than trusted.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any mapped output has no ``output`` block.
    """
    declared = set(re.findall(r'^output "([^"]+)"', OUTPUTS.read_text(), re.MULTILINE))
    assert "api_origin" in declared, "outputs.tf parsed to nothing recognisable"

    missing = sorted(name for name in _mapping() if name not in declared)
    assert missing == [], f"mapped outputs absent from infra/outputs.tf: {missing}"


def test_no_mapped_output_is_sensitive() -> None:
    """A sensitive output would be redacted by ``tofu output`` and published by ``-json``.

    The map's values reach a world-readable document, so a sensitive output joining it is
    a disclosure rather than a broken deploy — nothing would fail.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a mapped output declares ``sensitive = true``.
    """
    source = OUTPUTS.read_text()
    blocks = re.findall(r'^output "([^"]+)" \{(.*?)^\}', source, re.MULTILINE | re.DOTALL)
    assert blocks, "no output blocks parsed — this assertion has no subject"

    sensitive = {name for name, body in blocks if re.search(r"^\s*sensitive\s*=\s*true", body, re.MULTILINE)}
    offending = sorted(set(_mapping()) & sensitive)
    assert offending == [], f"mapped outputs declared sensitive: {offending}"


def test_the_entrypoint_renders_the_map_plus_the_genuine_inputs() -> None:
    """The leg that decides whether the container starts, bound to the map.

    The container refuses to start on an unset required key, so a key in the map and not
    in ``KEYS`` is a document the container will not serve. The reverse is the silent
    half: a key in ``KEYS`` that nothing supplies renders empty and is dropped, and the
    entrypoint's list is the only thing bounding what reaches a world-readable document.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the entrypoint's key list is not the map plus the two inputs.
    """
    rendered = set(_shell_word_list(ENTRYPOINT.read_text(), "KEYS"))

    assert rendered == set(_mapping().values()) | GENUINE_INPUTS


def test_the_deploy_role_already_reads_the_state_bucket() -> None:
    """The no-new-grant claim, asserted rather than believed.

    Reading ``tofu output`` against the remote state is a read the deploy role has held
    since the backend existed, which is why this spec adds no IAM. That is a claim about
    a policy document nobody was comparing, and the failure mode if it stops being true
    is a deploy that cannot resolve its configuration at all. ``s3:ListBucket`` is named
    beside ``s3:GetObject`` deliberately: without it S3 answers ``AccessDenied`` rather
    than ``NoSuchKey``, and a missing state object would read as a permissions fault.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the statement is absent or has lost either action.
    """
    rendered = DEPLOY_POLICY.read_text().replace("${state_bucket}", "dat-prod-tf-state")
    statements = [
        statement
        for statement in json.loads(re.sub(r"\$\{[a-z_]+\}", "placeholder", rendered))["Statement"]
        if statement.get("Sid") == "TofuStateS3"
    ]
    assert len(statements) == 1, "no single TofuStateS3 statement — this has no subject"

    actions = set(statements[0]["Action"])
    assert {"s3:GetObject", "s3:ListBucket"} <= actions
    assert "arn:aws:s3:::dat-prod-tf-state/*" in statements[0]["Resource"]
