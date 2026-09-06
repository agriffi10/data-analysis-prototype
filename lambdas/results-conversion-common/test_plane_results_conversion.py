"""The results-conversion plane's own invariants: what its layer, its role and its rule hold.

Each test here is a fence, not a behaviour: the domain layer holds no algorithm, the role
holds no write and no query start, the timeout door is the event one, the refused-destination
set agrees with the picker the browser uses, and the two caps are computed rather than typed.
"""

import ast
import json
import os
import pathlib
import re
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "control-plane-common"))
sys.path.insert(0, str(_HERE.parent / "file-ops-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from cpcommon import app_managed
from cpcommon import messages as cpmessages
from rccommon import config, messages, reasons

_MODULE = _ROOT / "infra" / "modules" / "results-conversion"
_POLICY = _MODULE / "policies" / "execution.json.tftpl"
_ASL = _MODULE / "state-machine.asl.json.tftpl"
_LOCALS = _MODULE / "locals.tf"
_DOOR = _HERE.parent / "results-conversion-notify-failure" / "rc_notify_failure.py"

_ALGORITHM_NAMES = ("cas", "lock", "parse_sqs", "resolve")


def _render_policy() -> dict:
    """Renders the execution policy with every placeholder stubbed to a recognisable literal."""
    raw = _POLICY.read_text(encoding="utf-8")
    return json.loads(re.sub(r"\$\{([^}]+)\}", r"@\1@", raw))


def _actions(statement) -> set[str]:
    action = statement.get("Action")
    return set(action) if isinstance(action, list) else {action}


def _resources(statement) -> list[str]:
    resource = statement.get("Resource")
    return list(resource) if isinstance(resource, list) else [resource]


def test_the_domain_layer_defines_no_algorithm_of_its_own():
    """rccommon holds wording and rules; every algorithm is imported from cpcommon.

    A CAS loop, a lock, a queue parser or a message resolver written here would be a second
    copy of one the shared layer already owns, drifting from it silently.
    """
    offenders = []
    for path in sorted((_HERE / "rccommon").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                lowered = node.name.lower()
                if any(name in lowered for name in _ALGORITHM_NAMES):
                    offenders.append(f"{path.name}::{node.name}")
    assert offenders == [], f"rccommon defines an algorithm the shared layer owns: {offenders}"


def test_the_layer_sweep_sees_the_functions_it_reads():
    """The positive control for the sweep above: it finds this plane's real functions."""
    found = {
        node.name
        for path in (_HERE / "rccommon").glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    assert {"authorize_destination", "destination_key", "failure_message"} <= found


def test_the_execution_role_starts_no_query_and_writes_nothing():
    """Read-only by construction: no PutObject Allow and no StartQueryExecution anywhere."""
    allowed = set()
    for statement in _render_policy()["Statement"]:
        if statement["Effect"] == "Allow":
            allowed |= _actions(statement)
    assert "s3:PutObject" not in allowed, "the write grant belongs beside the verb that writes"
    assert "athena:StartQueryExecution" not in allowed, "the input is a result object, never a query"
    assert "states:DescribeExecution" not in allowed, "the timeout door reads the event, not the API"
    assert {"athena:GetQueryExecution", "athena:GetQueryResults", "s3:GetObject"} <= allowed


def test_the_deny_names_every_refused_destination_in_both_buckets():
    """The validator's refusal and the role's Deny are one rule stated twice, held equal here."""
    denies = [s for s in _render_policy()["Statement"] if s["Effect"] == "Deny"]
    assert len(denies) == 1 and _actions(denies[0]) == {"s3:PutObject"}
    denied = set(_resources(denies[0]))
    for bucket in ("@user_space_bucket_arn@", "@shared_space_bucket_arn@"):
        for folder in config.PROTECTED_DESTINATIONS:
            assert f"{bucket}/*/{folder}/*" in denied, f"{folder} is refused but not denied in {bucket}"


def test_the_deny_names_the_system_settings_prefix_itself_in_both_buckets():
    """The whole new prefix is denied, not only the three folders moving into it.

    The loop above walks ``PROTECTED_DESTINATIONS``, which does not yet name ``system_settings``,
    so without this assertion the two resources naming it are pinned by nothing at all — a
    statement no guard reads is how the same arc already shipped one that was invisible. It stays
    once the name joins that list: the loop then demands this shape through the list, while this
    says the bare prefix outright, which is the fact the per-folder siblings do not carry.
    """
    denies = [s for s in _render_policy()["Statement"] if s["Effect"] == "Deny"]
    denied = set(_resources(denies[0]))
    for bucket in ("@user_space_bucket_arn@", "@shared_space_bucket_arn@"):
        assert f"{bucket}/*/system_settings/*" in denied, f"system_settings itself is writable in {bucket}"


def test_no_denied_resource_is_wide_enough_to_cover_a_whole_bucket():
    """Every Deny resource names at least one LITERAL segment, so none of them is bucket-wide.

    The two assertions above are both membership tests, so neither can see a resource that was
    ADDED — measured by planting ``${user_space_bucket_arn}/*`` into this statement, which left
    every template guard in the repository green. That blind spot costs more now the statement
    carries ``*/system_settings/*``, a strict superset of three siblings beside it: widening one
    of these is a one-character edit.

    The direction that bites is over-width, not under: this role holds no write grant today, so a
    bucket-wide ``s3:PutObject`` Deny is invisible until the converter gains one, and then it
    refuses the plane's own output.

    A segment carrying ``*`` or ``?`` does not count, because both are S3 wildcards and the
    widening this guards against is a one-character edit — ``/*`` to ``/?*`` matches every key of
    length one or more while still reading as a path. The rule assumes an OBJECT-level Deny: the
    statement's actions are pinned to ``s3:PutObject`` above, and a bucket-level action added
    later would legitimately name the bucket ARN alone and redden this.
    """
    denies = [s for s in _render_policy()["Statement"] if s["Effect"] == "Deny"]
    for resource in _resources(denies[0]):
        segments = resource.split("/")[1:]
        literal = [seg for seg in segments if seg and not set(seg) & {"*", "?"}]
        assert literal, f"{resource} denies more than a folder"


def test_the_refused_set_is_the_pickers_and_a_superset_of_the_shared_enumerator():
    """The plane refuses exactly what the browser's picker never offers, and every folder the
    shared owner enumerates, so a folder moving under a new prefix moves for this plane too."""
    from focommon.config import PICKER_LOCKED_FOLDERS

    assert set(config.PROTECTED_DESTINATIONS) == set(PICKER_LOCKED_FOLDERS)
    assert set(app_managed.SPACE_FOLDERS) <= set(config.PROTECTED_DESTINATIONS)
    assert set(app_managed.SPACE_FOLDERS) == {
        app_managed.ATHENA_RESULTS_FOLDER,
        app_managed.RECEIPT_FOLDER,
        app_managed.SHARED_TABLES_FOLDER,
    }


def test_every_reason_is_worded_and_every_wording_is_a_reason():
    """The closed set and the wording table agree, base codes resolving through the base table."""
    for reason in reasons.REASONS:
        assert cpmessages.is_known_reason(reason), f"{reason} is raised but never registered"
        assert "something went wrong" not in messages.failure_message(reason) or reason == reasons.UNEXPECTED
    assert set(messages._BODIES) <= reasons.REASONS
    assert reasons.REASONS - set(messages._BODIES) == {reasons.MALFORMED_EVENT, reasons.FORBIDDEN}


def test_the_wording_names_the_format_and_the_file_where_they_are_known():
    sentence = messages.failure_message(
        reasons.PROTECTED_LOCATION, {"format": "xlsx", "filename": "q1.xlsx"}
    )
    assert sentence.startswith("Couldn't save the query results as Excel: ")
    assert '"q1.xlsx"' in sentence
    assert "GB" in messages.failure_message(reasons.RESULTS_TOO_LARGE)
    assert messages.failure_message(reasons.FORBIDDEN) == "You don't have access to save results there."
    assert messages.failure_message(reasons.MALFORMED_EVENT, {"format": "json"}).startswith(
        "Couldn't save the query results as JSON: "
    )


def test_the_size_cap_is_computed_from_the_provisional_converter_budget():
    """PROVISIONAL: the converter is not built yet. The cap must fit the memory the converter is
    expected to run with, at the assumed CSV-to-frame expansion, and leave the scratch disk
    room for the result object and the written file side by side. The spec that builds the
    converter re-derives all three numbers in the test that sizes it."""
    by_memory = config.CONVERTER_MEMORY_MB * 1024**2 // config.CONVERTER_EXPANSION
    by_disk = config.CONVERTER_EPHEMERAL_MB * 1024**2 // 2
    assert 0 < config.RESULTS_MAX_BYTES <= min(by_memory, by_disk)
    assert config.RESULTS_MAX_BYTES % 1024**2 == 0, "the cap must render in whole units to a user"


def test_the_ceiling_clears_the_longest_path_the_machine_can_walk():
    """The machine's ceiling is a ceiling, not a guess: every Task's timeout times its attempts,
    plus the backoff between attempts, along the longest path through the machine."""
    locals_text = _LOCALS.read_text(encoding="utf-8")
    ceiling = int(re.search(r"state_machine_timeout_seconds\s*=\s*(\d+)", locals_text).group(1))
    assert ceiling == config.MACHINE_TIMEOUT_SECONDS, (
        "the Terraform ceiling and the constant the timeout notification words have diverged; "
        "the user would be told a duration the machine no longer runs for"
    )
    assert "an hour" in messages.failure_message(reasons.CONVERSION_TIMED_OUT)
    timeouts = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r'"([a-z-]+)"\s*=\s*\{[^}]*timeout\s*=\s*(\d+)', locals_text)
    }
    assert set(timeouts) == {"validate-authorize", "describe-results", "notify-failure"}
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", _ASL.read_text(encoding="utf-8"))
    states = json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw))["States"]
    longest = 0
    for name, key in (
        ("ValidateAuthorize", "validate-authorize"),
        ("DescribeResults", "describe-results"),
        ("NotifyFailure", "notify-failure"),
    ):
        retry = states[name]["Retry"][0]
        attempts = retry["MaxAttempts"] + 1
        backoff = sum(retry["IntervalSeconds"] * retry["BackoffRate"] ** i for i in range(retry["MaxAttempts"]))
        longest += timeouts[key] * attempts + backoff
    assert ceiling > longest, f"the ceiling {ceiling}s cannot hold the longest path, {longest}s"


def test_the_timed_out_door_reads_the_event_and_never_describes_the_execution():
    """One claim in two places: the policy grants no DescribeExecution, so the door must not
    reach for the shared helper that falls back to it."""
    source = _DOOR.read_text(encoding="utf-8")
    assert "timed_out_execution_input" not in source
    assert "describe_execution" not in source
    assert 'detail.get("input")' in source


def test_the_timeout_rule_matches_timed_out_and_never_failed():
    text = (_MODULE / "stepfunction.tf").read_text(encoding="utf-8")
    assert 'status          = ["TIMED_OUT"]' in text
    assert "FAILED" not in text.split("event_pattern")[1].split("})")[0]
    assert '"TimeoutSeconds": ${state_machine_timeout_seconds}' in _ASL.read_text(encoding="utf-8")


def test_no_queue_resource_policy_is_added_anywhere_in_the_fleet():
    """The notifications writer's boundary is a runtime denylist of one; a queue policy would
    silence notifying roles invisibly."""
    offenders = [
        str(p.relative_to(_ROOT))
        for p in (_ROOT / "infra" / "modules").rglob("*.tf")
        if "aws_sqs_queue_policy" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_module_ships_no_moved_block():
    """A cutover-era guard counts moved blocks against the frozen fixture; a new module has
    nothing to move."""
    assert not (_MODULE / "moved.tf").exists()


@pytest.mark.parametrize("fixture", ["module_dir", "policy", "asl"])
def test_the_files_this_suite_reads_exist(fixture):
    path = {"module_dir": _MODULE, "policy": _POLICY, "asl": _ASL}[fixture]
    assert path.exists(), f"{path} is missing, so the assertions over it are vacuous"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
