"""The ASL against the verbs: the keys each Pass reads are the keys each verb really returns.

A Task hands its output on whole, so nothing in a Task-to-Task chain notices a renamed field
— while a Pass state's JSONPath hard-fails on an absent key with an uncatchable
``States.Runtime``. The two cross-check Pass states exist so that this file can hold the
template and the verbs' real return values equal, and the failure walk holds that every way
the machine can stop short of its terminal tells the user first.
"""

import json
import os
import pathlib
import re
import sys
import tempfile

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "control-plane-common"))
sys.path.insert(0, str(_HERE.parent / "results-conversion-validate-authorize"))
sys.path.insert(0, str(_HERE.parent / "results-conversion-describe-results"))
sys.path.insert(0, str(_HERE.parent / "results-conversion-convert"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import rc_convert as c
import rc_describe_results as d
import rc_validate_authorize as v
from cpcommon import clients, config

_ASL = _HERE.parent.parent / "infra" / "modules" / "results-conversion" / "state-machine.asl.json.tftpl"
_EXECUTION_ID = "11111111-2222-4333-8444-555555555555"


class _Athena:
    def __init__(self):
        self.execution = {
            "Status": {"State": "SUCCEEDED"},
            "StatementType": "DML",
            "ResultConfiguration": {
                "OutputLocation": f"s3://{config.USER_SPACE_BUCKET}/alice/athenaresults/{_EXECUTION_ID}.csv"
            },
        }

    def get_query_execution(self, **kwargs):
        return {"QueryExecution": self.execution}

    def get_query_results(self, **kwargs):
        return {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": [{"Name": "id", "Type": "bigint"}]}}}


_CSV = b'"id"\n"1"\n"2"\n'


class _S3:
    """Enough S3 for one conversion: a size, a download, and a write that records itself."""

    def __init__(self):
        self.written = []

    def head_object(self, **kwargs):
        return {"ContentLength": len(_CSV)}

    def download_fileobj(self, bucket, key, handle):
        handle.write(_CSV)

    def put_object(self, **kwargs):
        self.written.append(kwargs)
        return {}


def _machine() -> dict:
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", _ASL.read_text(encoding="utf-8"))
    return json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw))


def _reads(parameters: dict) -> set[str]:
    return {k.removesuffix(".$") for k in parameters}


def _event() -> list:
    body = {
        "requestId": "req-1",
        "queryExecutionId": _EXECUTION_ID,
        "format": "parquet",
        "destination": {"space": {"kind": "personal", "name": "alice"}, "prefix": "out/", "filename": "q1.parquet"},
        "onConflict": "refuse",
        "submittedAt": "2026-09-05T12:00:00+00:00",
        "identity": {"actor": "alice", "delegated_by": None, "assurance": "interactive"},
    }
    return [{"body": json.dumps(body)}]


@pytest.fixture
def _stubbed():
    clients._athena = _Athena()
    clients._s3 = _S3()
    v.notify.emit_notification = lambda *a, **kw: None
    d.notify.emit_notification = lambda *a, **kw: None
    c.notify.emit_notification = lambda *a, **kw: None
    c.SCRATCH_ROOT = pathlib.Path(tempfile.mkdtemp())


def test_validated_reads_exactly_the_keys_validate_authorize_returns(_stubbed):
    validated = v.handler(_event(), None)
    assert _reads(_machine()["States"]["Validated"]["Parameters"]) == set(validated)
    assert set(validated) == {
        "requestId", "username", "format", "onConflict", "queryExecutionId", "resultsKey", "destination",
    }
    assert set(validated["destination"]) == {"bucket", "key", "prefix", "spaceKind", "spaceName"}


def test_described_reads_exactly_the_keys_describe_results_returns(_stubbed):
    described = d.handler(v.handler(_event(), None), None)
    assert _reads(_machine()["States"]["Described"]["Parameters"]) == set(described)
    assert set(described) == _reads(_machine()["States"]["Validated"]["Parameters"]) | {"columns", "resultsBytes"}


def test_no_fail_state_is_reachable_except_through_notify_failure():
    """Every catch, on every state, routes through NotifyFailure before Fail."""
    states = _machine()["States"]
    edges = []
    for name, state in states.items():
        for target in (state.get("Next"), state.get("Default")):
            if target:
                edges.append((name, target))
        for catch in state.get("Catch", []) or []:
            edges.append((name, catch["Next"]))
        for choice in state.get("Choices", []) or []:
            edges.append((name, choice["Next"]))
    fails = [name for name, state in states.items() if state["Type"] == "Fail"]
    assert fails, "no Fail state, so the walk proves nothing"
    for fail in fails:
        sources = {src for src, dst in edges if dst == fail}
        assert sources == {"NotifyFailure"}, f"{fail} is reachable from {sorted(sources)}"
    assert states["NotifyFailure"]["Type"] == "Task"


def test_every_failure_seed_carries_the_username_the_request_id_and_the_format():
    states = _machine()["States"]
    for seed in ("ValidateFailureSeed", "RequestFailureSeed"):
        assert {"requestId", "username", "format", "raw", "tokens", "error"} == _reads(
            states[seed]["Parameters"]
        )
    assert states["ValidateFailureSeed"]["Parameters"]["error.$"] == "$"
    assert states["RequestFailureSeed"]["Parameters"]["error.$"] == "$.error"
    assert _reads(states["RecordFailure"]["Parameters"]) <= _reads(
        states["RequestFailureSeed"]["Parameters"]
    ) | {"status"}


def test_the_machine_starts_at_the_validator_with_a_top_level_ceiling():
    machine = _machine()
    assert machine["StartAt"] == "ValidateAuthorize"
    assert "TimeoutSeconds" in machine
    assert "Placeholder" not in machine["States"], (
        "the placeholder was replaced by Convert; a machine still carrying it writes nothing"
    )
    assert machine["States"]["Notify"]["Next"] == "Succeeded"


def test_converted_reads_exactly_the_keys_the_convert_verb_returns(_stubbed):
    """The third cross-check, and the one with the most to lose: this verb REPLACES the state,
    so any key a later state names and the verb does not return is an uncatchable
    States.Runtime on a request that had already been written to the user's space."""
    converted = c.handler(d.handler(v.handler(_event(), None), None), None)
    assert _reads(_machine()["States"]["Converted"]["Parameters"]) == set(converted)
    assert converted["outcome"] == "converted"
    assert {"columns", "resultsBytes"}.isdisjoint(converted), (
        "the described columns and size are deliberately dropped: nothing downstream reads "
        "either, and carrying the column list forward puts an unbounded value on the state"
    )


def test_the_refusal_seed_supplies_every_key_the_failure_terminal_reads(_stubbed):
    """A Pass state's JSONPath hard-fails on an absent key, so the three seeds and the state
    they all flow into have to agree — and a refusal is the only one of the three that arrives
    carrying a count for the sentence."""
    states = _machine()["States"]
    seeds = ("ValidateFailureSeed", "RequestFailureSeed", "ConvertRefusedSeed")
    for seed in seeds:
        assert "tokens" in _reads(states[seed]["Parameters"]), f"{seed} supplies no tokens"
    assert _reads(states["RecordFailure"]["Parameters"]) <= set.intersection(
        *(_reads(states[seed]["Parameters"]) for seed in seeds)
    ) | {"status"}
    assert states["ConvertRefusedSeed"]["Parameters"]["error"] == {"Error.$": "$.reason"}, (
        "the refusal must NOT arrive tagged as a TerminalError: notify-failure suppresses one "
        "as a duplicate of a verb notification that, on this path, never happened"
    )
    choice = states["ConversionOutcome"]
    assert choice["Type"] == "Choice" and choice["Default"] == "Notify"
    assert choice["Choices"] == [
        {"Variable": "$.outcome", "StringEquals": "refused", "Next": "ConvertRefusedSeed"}
    ]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
