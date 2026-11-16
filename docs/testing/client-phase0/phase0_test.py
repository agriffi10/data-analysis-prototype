"""Offline fixture corpus for ``phase0.py``: every verdict branch, asserted by its reason, and the log's guard.

Nobody can run the checks against AWS from here, so the verdicts are the part that can be proved in
advance: given what a run would record, does each check say the right thing, for the right reason?
Each case asserts the verdict AND a phrase of the reason, because two branches often share a verdict.

Run from this directory with ``python3 -m unittest phase0_test``; it needs no AWS SDK.
"""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import phase0

T0 = "2026-12-01T10:00:00.000Z"
APP = "arn:aws:sso::111111111111:application/ssoins-aaaa/apl-bbbb"


def rec(
    label: str,
    ok: bool = True,
    code: str | None = None,
    message: str = "",
    data: dict[str, Any] | None = None,
    ts: str = T0,
) -> dict[str, Any]:
    """Build one evidence record as either half would write it.

    Args:
      label: The label.
      ok: Success.
      code: The error code on failure.
      message: The error message on failure.
      data: The data.
      ts: The timestamp.

    Returns:
      The record.

    Raises:
      None.
    """
    out: dict[str, Any] = {"ts": ts, "label": label, "ok": ok, "data": data or {}}
    if not ok:
        out.update(code=code, message=message)
    return out


def obs(*records: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index records the way the verdicts read them.

    Args:
      *records: The records, in order.

    Returns:
      The latest record per label.

    Raises:
      None.
    """
    return phase0.latest(list(records))


def c1_pass() -> list[dict[str, Any]]:
    """A cross-account exchange and a split assumption that should pass.

    Args:
      None.

    Returns:
      The records.

    Raises:
      None.
    """
    caller = {
        "account": "222222222222",
        "arn": "arn:aws:sts::222222222222:assumed-role/task-role/s1",
    }
    return [
        rec("C1.exchange.caller", data=caller),
        rec(
            "C1.exchange",
            data={
                "appAccount": "111111111111",
                "caller": caller,
                "context": {"present": True},
            },
        ),
        rec(
            "C1.assumer",
            data={"arn": "arn:aws:sts::222222222222:assumed-role/api-role/s2"},
        ),
        rec("C1.assume.with", data={"expirationEqualsContextExp": True}),
        rec("C1.assume.without"),
        rec("C1.grants.with", data={"count": 1}),
        rec("C1.grants.without", data={"count": 0}),
    ]


def replace(records: list[dict[str, Any]], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Swap the record that shares ``new``'s label.

    Args:
      records: The base records.
      new: The replacement.

    Returns:
      A new list.

    Raises:
      None.
    """
    return [new if r["label"] == new["label"] else r for r in records]


class VerdictC1Test(unittest.TestCase):
    """Check 1, the cross-account exchange."""

    def test_reasons(self) -> None:
        """Each branch states its verdict and its reason."""
        base = c1_pass()
        same_caller = {
            "account": "111111111111",
            "arn": "arn:aws:sts::111111111111:assumed-role/x/s",
        }
        cases = [
            (
                "pass",
                base,
                "PASS",
                "exchanged on the application in account 111111111111",
            ),
            ("never recorded", [], "INCONCLUSIVE", "never recorded"),
            (
                "local",
                replace(
                    base,
                    rec(
                        "C1.exchange",
                        ok=False,
                        code="Local:CredentialsProviderError",
                        data={"appAccount": "111111111111"},
                    ),
                ),
                "INCONCLUSIVE",
                "never reached AWS",
            ),
            (
                "same account",
                replace(
                    replace(base, rec("C1.exchange.caller", data=same_caller)),
                    rec(
                        "C1.exchange",
                        data={
                            "appAccount": "111111111111",
                            "context": {"present": True},
                        },
                    ),
                ),
                "INCONCLUSIVE",
                "repeats G10",
            ),
            (
                "refused, no control",
                replace(
                    base,
                    rec(
                        "C1.exchange",
                        ok=False,
                        code="AccessDeniedException",
                        message="denied",
                        data={"appAccount": "111111111111"},
                    ),
                ),
                "INCONCLUSIVE",
                "cannot be laid on the account boundary",
            ),
            (
                "refused, control ok",
                [
                    *replace(
                        base,
                        rec(
                            "C1.exchange",
                            ok=False,
                            code="AccessDeniedException",
                            message="denied",
                            data={"appAccount": "111111111111"},
                        ),
                    ),
                    rec(
                        "C1.control.exchange",
                        data={"appAccount": "111111111111", "caller": same_caller},
                    ),
                ],
                "INCONCLUSIVE",
                "actor policy was not read",
            ),
            (
                "control from the member account is no control",
                [
                    *replace(
                        base,
                        rec(
                            "C1.exchange",
                            ok=False,
                            code="AccessDeniedException",
                            message="denied",
                            data={"appAccount": "111111111111"},
                        ),
                    ),
                    rec(
                        "C1.control.exchange",
                        data={
                            "appAccount": "111111111111",
                            "caller": {"account": "222222222222"},
                        },
                    ),
                ],
                "INCONCLUSIVE",
                "cannot be laid on the account boundary",
            ),
            (
                "no context",
                replace(
                    base,
                    rec(
                        "C1.exchange",
                        data={
                            "appAccount": "111111111111",
                            "context": {"present": False},
                        },
                    ),
                ),
                "FAIL",
                "no identity context",
            ),
            (
                "same principal",
                replace(
                    base,
                    rec(
                        "C1.assumer",
                        data={
                            "arn": "arn:aws:sts::222222222222:assumed-role/task-role/other"
                        },
                    ),
                ),
                "INCONCLUSIVE",
                "split between two principals",
            ),
            (
                "SetContext missing",
                replace(
                    base,
                    rec(
                        "C1.assume.with",
                        ok=False,
                        code="AccessDenied",
                        message="not authorized to perform: sts:SetContext",
                    ),
                ),
                "INCONCLUSIVE",
                "sts:SetContext",
            ),
            (
                "trust refuses both",
                replace(
                    replace(
                        base,
                        rec(
                            "C1.assume.with",
                            ok=False,
                            code="AccessDenied",
                            message="no",
                        ),
                    ),
                    rec(
                        "C1.assume.without", ok=False, code="AccessDenied", message="no"
                    ),
                ),
                "INCONCLUSIVE",
                "trust policy, not the context",
            ),
            (
                "context refused",
                replace(
                    base,
                    rec(
                        "C1.assume.with",
                        ok=False,
                        code="InvalidContextAssertion",
                        message="bad",
                    ),
                ),
                "FAIL",
                "STS refused a context",
            ),
            (
                "grants equal",
                replace(base, rec("C1.grants.with", data={"count": 0})),
                "INCONCLUSIVE",
                "identity is not shown",
            ),
        ]
        for name, records, verdict, phrase in cases:
            with self.subTest(name):
                got, reason = phase0.verdict_c1(obs(*records))
                self.assertEqual(got, verdict, reason)
                self.assertIn(phrase, reason)


def c2_records(
    with_codes: dict[str, str | None],
    exempt: dict[str, bool] | None = None,
    without_code: str | None = None,
) -> list[dict[str, Any]]:
    """A check 2 run: each probe with the context gets the given error code, or succeeds on None.

    Args:
      with_codes: Probe name to error code, None meaning allowed.
      exempt: The allow-list's exemptions per probe.
      without_code: An error code for every control call, or None for all allowed.

    Returns:
      The records.

    Raises:
      None.
    """
    out = [
        rec(
            "C2.allowlist.policy",
            data={
                "versionId": "v12",
                "exempt": exempt or dict.fromkeys(phase0.PROBES, False),
            },
        ),
        rec("C2.assume.with"),
        rec("C2.grants.with", data={"count": 1}),
        rec("C2.grants.without", data={"count": 0}),
    ]
    for name in phase0.PROBES:
        code = with_codes.get(name)
        out.append(rec(f"C2.{name}.with", ok=code is None, code=code, message="m"))
        out.append(
            rec(
                f"C2.{name}.without",
                ok=without_code is None,
                code=without_code,
                message="m",
            )
        )
    return out


class VerdictC2Test(unittest.TestCase):
    """Check 2, the allow-list re-run."""

    def test_reasons(self) -> None:
        """Each combination of probe results names its own outcome."""
        allowed = dict.fromkeys(phase0.PROBES)
        denied = dict.fromkeys(phase0.PROBES, "AccessDenied")
        cases = [
            ("absent", c2_records(allowed), "MEASURED:DENY_ABSENT", "not in effect"),
            (
                "in effect",
                c2_records(denied),
                "MEASURED:DENY_IN_EFFECT",
                "in effect here",
            ),
            (
                "s3 gap",
                c2_records({**allowed, "sqs_send": "AccessDenied"}),
                "MEASURED:S3_ONLY_GAP",
                "S3 escapes it",
            ),
            (
                "sqs escapes",
                c2_records({**denied, "sqs_send": None}),
                "MEASURED:S3_DENIED_SQS_ALLOWED",
                "SQS was not",
            ),
            (
                "mixed",
                c2_records({**allowed, "putobject": "AccessDenied"}),
                "MEASURED:MIXED_S3",
                "plain S3 split",
            ),
            (
                "control refused",
                c2_records(allowed, without_code="AccessDenied"),
                "INCONCLUSIVE",
                "control refused",
            ),
            (
                "exempt",
                c2_records(
                    allowed,
                    exempt={**dict.fromkeys(phase0.PROBES, False), "sqs_send": True},
                ),
                "INCONCLUSIVE",
                "allow-list exempts sqs:SendMessage",
            ),
            (
                "local",
                c2_records({**allowed, "listobjects": "Local:EndpointConnectionError"}),
                "INCONCLUSIVE",
                "never reached AWS",
            ),
            (
                "other error",
                c2_records({**allowed, "getobject_other": "NoSuchKey"}),
                "INCONCLUSIVE",
                "failed otherwise",
            ),
            (
                "no session",
                [r for r in c2_records(allowed) if r["label"] != "C2.assume.with"],
                "INCONCLUSIVE",
                "no identity-enhanced carrier session",
            ),
            (
                "grants equal",
                replace(c2_records(allowed), rec("C2.grants.with", data={"count": 0})),
                "INCONCLUSIVE",
                "identity is not shown",
            ),
        ]
        for name, records, verdict, phrase in cases:
            with self.subTest(name):
                got, reason = phase0.verdict_c2(obs(*records))
                self.assertEqual(got, verdict, reason)
                self.assertIn(phrase, reason)


def p_records(**over: dict[str, Any]) -> list[dict[str, Any]]:
    """A check 3 run that passes every gate, with named records overridden.

    Args:
      **over: Label (dots as underscores) to replacement record.

    Returns:
      The records.

    Raises:
      None.
    """
    base = [
        rec("P.accounts", data={"targetListed": True}),
        rec("P.creds"),
        rec("P1.query", data={"state": "SUCCEEDED"}),
        rec("P2.own"),
        rec("P2.other", ok=False, code="AccessDenied", message="m"),
        rec("P3.get"),
        rec("P3.put"),
        rec("P3.list"),
    ]
    for record in over.values():
        base = replace(base, record)
    return base


class VerdictPTest(unittest.TestCase):
    """Check 3, gates P1 to P3."""

    def test_reasons(self) -> None:
        """Each gate's branches state their own reason."""
        cases = [
            (
                "all pass",
                p_records(),
                {
                    "P1": ("PASS", "Identity Center workgroup"),
                    "P2": ("PASS", "resolved"),
                    "P3": ("PASS", "all succeeded"),
                },
            ),
            (
                "no creds",
                p_records(
                    c=rec("P.creds", ok=False, code="ForbiddenException", message="m")
                ),
                dict.fromkeys(
                    ("P1", "P2", "P3"),
                    ("INCONCLUSIVE", "no permission-set credentials"),
                ),
            ),
            (
                "P1 refused",
                p_records(
                    q=rec(
                        "P1.query",
                        ok=False,
                        code="InvalidRequestException",
                        message="You do not have access to wg",
                    )
                ),
                {"P1": ("FAIL", "carries no identity context")},
            ),
            (
                "P1 query failed",
                p_records(
                    q=rec(
                        "P1.query",
                        data={
                            "state": "FAILED",
                            "stateChangeReason": "no accessible columns",
                        },
                    )
                ),
                {"P1": ("FAIL", "no accessible columns")},
            ),
            (
                "P1 other",
                p_records(
                    q=rec("P1.query", ok=False, code="Local:Timeout", message="m")
                ),
                {"P1": ("INCONCLUSIVE", "did not settle")},
            ),
            (
                "P2 no tag",
                p_records(o=rec("P2.own", ok=False, code="AccessDenied", message="m")),
                {"P2": ("FAIL", "no username tag")},
            ),
            (
                "P2 broad",
                p_records(o=rec("P2.other")),
                {"P2": ("INCONCLUSIVE", "broader than the tag")},
            ),
            (
                "P3 denied",
                p_records(
                    p=rec(
                        "P3.put", ok=False, code="AccessDenied", message="explicit deny"
                    )
                ),
                {"P3": ("FAIL", "put (AccessDenied: explicit deny)")},
            ),
            (
                "P3 local",
                p_records(p=rec("P3.list", ok=False, code="Local:X", message="m")),
                {"P3": ("INCONCLUSIVE", "list Local:X")},
            ),
        ]
        for name, records, expect in cases:
            got = {
                gate: (verdict, reason)
                for gate, verdict, reason in phase0.verdict_p(obs(*records))
            }
            for gate, (verdict, phrase) in expect.items():
                with self.subTest(f"{name} {gate}"):
                    self.assertEqual(got[gate][0], verdict, got[gate][1])
                    self.assertIn(phrase, got[gate][1])


def at(minutes: int, node: bool = True) -> str:
    """A timestamp some minutes after the deletion, in either half's format.

    Args:
      minutes: Minutes after 10:00.
      node: True for Node's ``Z`` form, False for Python's ``+00:00`` form.

    Returns:
      The timestamp.

    Raises:
      None.
    """
    hh, mm = divmod(minutes, 60)
    return (
        f"2026-12-01T{10 + hh:02d}:{mm:02d}:00.000Z"
        if node
        else f"2026-12-01T{10 + hh:02d}:{mm:02d}:00.000000+00:00"
    )


def c4_records(
    after: list[tuple[int, str | None]],
    reexchange: str | None = "ok",
    minted_at: int = 2,
) -> list[dict[str, Any]]:
    """A check 4 run: the deletion at 10:00, refreshes after it, then a re-exchange.

    Args:
      after: ``(minutes, error code or None)`` per refresh after the deletion.
      reexchange: ``ok``, an error code, or None for not run.
      minted_at: Minutes after the deletion the fresh Cognito token was minted.

    Returns:
      The records.

    Raises:
      None.
    """
    out = [
        rec("C4.refresh.before", ts=at(0).replace("10:00", "09:55")),
        rec("C4.deleted", data={"sessionsEnded": 1}, ts=at(0, node=False)),
    ]
    for i, (minutes, code) in enumerate(after):
        out.append(rec(f"C4.refresh.after.{i}.caller", ts=at(minutes)))
        out.append(
            rec(
                f"C4.refresh.after.{i}",
                ok=code is None,
                code=code,
                message="m",
                ts=at(minutes),
            )
        )
    out.append(rec("C4.cognito.refresh.after", ts=at(minted_at)))
    if reexchange is not None:
        out.append(
            rec(
                "C4.reexchange.after",
                ok=reexchange == "ok",
                code=None if reexchange == "ok" else reexchange,
                message="m",
                ts=at(minted_at + 1),
            )
        )
    return out


class VerdictC4Test(unittest.TestCase):
    """Check 4, ending the Identity Center session."""

    def test_reasons(self) -> None:
        """Each outcome is named, and timing across the two halves' formats is honoured."""
        cases = [
            (
                "bypass",
                c4_records([(1, None), (12, "InvalidGrantException")]),
                "MEASURED:REEXCHANGE_BYPASSES",
                "refused 12 min after",
            ),
            (
                "holds",
                c4_records(
                    [(5, "InvalidGrantException")], reexchange="InvalidGrantException"
                ),
                "MEASURED:DELETION_HOLDS",
                "re-exchange was refused too",
            ),
            (
                "not seen",
                c4_records([(1, None), (35, None)]),
                "MEASURED:DELETION_NOT_SEEN",
                "35 min after",
            ),
            (
                "outlives",
                c4_records([(31, None)], reexchange="InvalidGrantException"),
                "MEASURED:REFRESH_OUTLIVES_DELETION",
                "re-exchange was refused",
            ),
            (
                "too early",
                c4_records([(10, None)]),
                "INCONCLUSIVE",
                "short of the 30 minutes",
            ),
            (
                "no reexchange",
                c4_records([(5, "InvalidGrantException")], reexchange=None),
                "INCONCLUSIVE",
                "no re-exchange",
            ),
            (
                "token minted before deletion",
                c4_records([(5, "InvalidGrantException")], minted_at=-3),
                "INCONCLUSIVE",
                "no re-exchange",
            ),
            (
                "no mark",
                [r for r in c4_records([(5, None)]) if r["label"] != "C4.deleted"],
                "INCONCLUSIVE",
                "never marked",
            ),
            (
                "no baseline",
                replace(
                    c4_records([(5, None)]),
                    rec(
                        "C4.refresh.before",
                        ok=False,
                        code="InvalidGrantException",
                        message="m",
                    ),
                ),
                "INCONCLUSIVE",
                "no baseline",
            ),
            (
                "only callers after",
                [
                    r
                    for r in c4_records([(5, None)])
                    if r["label"] != "C4.refresh.after.0"
                ],
                "INCONCLUSIVE",
                "no refresh was recorded",
            ),
        ]
        for name, records, verdict, phrase in cases:
            with self.subTest(name):
                got, reason = phase0.verdict_c4(records, obs(*records))
                self.assertEqual(got, verdict, reason)
                self.assertIn(phrase, reason)


def c5_records(**over: dict[str, Any]) -> list[dict[str, Any]]:
    """A check 5 run that passes, with named records overridden.

    Args:
      **over: Any key to a replacement record.

    Returns:
      The records.

    Raises:
      None.
    """
    base = [
        rec(
            "C5.expected",
            data={
                "oid": "oid-1",
                "userName": "alice",
                "idpName": "Entra",
                "oidClaim": "entra_oid",
            },
        ),
        rec(
            "C5.login",
            data={
                "idToken": {
                    "federated": {"providerName": "Entra", "userId": "oid-1"},
                    "oidClaim": "entra_oid",
                    "oidClaimValue": "oid-1",
                }
            },
        ),
        rec(
            "C5.tti",
            data={
                "claimAttributePath": "entra_oid",
                "identityStoreAttributePath": "externalIds.value",
            },
        ),
        rec("C5.exchange"),
        rec(
            "C5.user",
            data={"userName": "alice", "externalIds": [{"Issuer": "i", "Id": "oid-1"}]},
        ),
    ]
    for record in over.values():
        base = replace(base, record)
    return base


class VerdictC5Test(unittest.TestCase):
    """Check 5, the Entra hop and the externalId mapping."""

    def test_reasons(self) -> None:
        """Each link in the chain fails with its own reason."""

        def login(**tok: Any) -> dict[str, Any]:
            token = {
                "federated": {"providerName": "Entra", "userId": "oid-1"},
                "oidClaim": "entra_oid",
                "oidClaimValue": "oid-1",
                **tok,
            }
            return rec("C5.login", data={"idToken": token})

        cases = [
            ("pass", c5_records(), "PASS", "whose externalIds include it"),
            (
                "another provider",
                c5_records(l=login(federated={"providerName": "Other"})),
                "INCONCLUSIVE",
                "check ENTRA_IDP_NAME",
            ),
            (
                "no claim",
                c5_records(l=login(oidClaimValue=None)),
                "FAIL",
                "trigger that emits the object id did not run",
            ),
            (
                "wrong oid",
                c5_records(l=login(oidClaimValue="upn@x")),
                "FAIL",
                "not keyed on the object id",
            ),
            (
                "email mapping",
                c5_records(
                    t=rec(
                        "C5.tti",
                        data={
                            "claimAttributePath": "email",
                            "identityStoreAttributePath": "emails.value",
                        },
                    )
                ),
                "INCONCLUSIVE",
                "not the externalId mapping",
            ),
            (
                "refused",
                c5_records(
                    e=rec(
                        "C5.exchange",
                        ok=False,
                        code="InvalidGrantException",
                        message="m",
                    )
                ),
                "FAIL",
                "refused the Entra-federated assertion",
            ),
            (
                "sub unresolved",
                c5_records(
                    u=rec(
                        "C5.user",
                        ok=False,
                        code="ResourceNotFoundException",
                        message="m",
                    )
                ),
                "INCONCLUSIVE",
                "sub did not resolve",
            ),
            (
                "wrong user",
                c5_records(
                    u=rec(
                        "C5.user",
                        data={"userName": "alice", "externalIds": [{"Id": "other"}]},
                    )
                ),
                "FAIL",
                "do not include the Entra object id",
            ),
            (
                "wrong name",
                c5_records(
                    u=rec(
                        "C5.user",
                        data={"userName": "bob", "externalIds": [{"Id": "oid-1"}]},
                    )
                ),
                "FAIL",
                "not 'alice'",
            ),
            (
                "tti unread",
                [r for r in c5_records() if r["label"] != "C5.tti"],
                "INCONCLUSIVE",
                "mapping was not read (TTI_ARN unset)",
            ),
        ]
        for name, records, verdict, phrase in cases:
            with self.subTest(name):
                got, reason = phase0.verdict_c5(obs(*records))
                self.assertEqual(got, verdict, reason)
                self.assertIn(phrase, reason)


class EvidenceGuardTest(unittest.TestCase):
    """The log never holds a token, and never lives in a checkout."""

    def test_guard(self) -> None:
        """A JWT or a registered secret is refused and nothing is written; a clean record is synced."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.jsonl"
            log = phase0.Evidence(path)
            log.add_secrets("SECRETACCESSKEYVALUE")
            jwt = (
                ".".join(
                    base64.urlsafe_b64encode(json.dumps(part).encode())
                    .decode()
                    .rstrip("=")
                    for part in ({"alg": "RS256"}, {"sub": "x"})
                )
                + ".sig"
            )
            for name, payload, phrase in (
                ("jwt", {"t": jwt}, "holds a JWT"),
                ("secret", {"k": "xSECRETACCESSKEYVALUEx"}, "registered secret"),
            ):
                with self.subTest(name), self.assertRaises(ValueError) as caught:
                    log.record("x", {"ok": True, "data": payload})
                self.assertIn(phrase, str(caught.exception))
            self.assertFalse(path.exists())
            log.record(
                "clean",
                {
                    "ok": True,
                    "data": {"fp": phase0.fingerprint("SECRETACCESSKEYVALUE")},
                },
            )
            self.assertEqual(
                [json.loads(line)["label"] for line in path.read_text().splitlines()],
                ["clean"],
            )
            Path(tmp, ".git").mkdir()
            with self.assertRaises(SystemExit) as caught:
                phase0.Evidence(Path(tmp) / "inside" / "e.jsonl")
            self.assertIn("inside the git checkout", str(caught.exception))


class ReviewedBranchesTest(unittest.TestCase):
    """Branches and guards added after review: attribution, unread inputs, fixture errors and timing."""

    def test_c1_attribution(self) -> None:
        """A refusal fails C1 only when the exchanger's grant, the control and the actor policy are all shown sound."""
        refused = rec(
            "C1.exchange",
            ok=False,
            code="AccessDeniedException",
            message="denied",
            data={"appAccount": "111111111111"},
        )
        control = rec(
            "C1.control.exchange",
            data={"appAccount": "111111111111", "caller": {"account": "111111111111"}},
        )
        base = [*replace(c1_pass(), refused), control]

        def names(*principals: str) -> dict[str, Any]:
            return rec("C1.actor", data={"principals": list(principals)})

        cases = [
            (
                "actor names the role, path dropped",
                [*base, names("arn:aws:iam::222222222222:role/team/task-role")],
                "FAIL",
                "the account boundary is the cause",
            ),
            (
                "actor names everyone",
                [*base, names("*")],
                "FAIL",
                "the account boundary is the cause",
            ),
            (
                "actor omits the role",
                [*base, names("arn:aws:iam::222222222222:role/other")],
                "INCONCLUSIVE",
                "is the fixture's",
            ),
            (
                "actor unread",
                [
                    *base,
                    rec(
                        "C1.actor", ok=False, code="AccessDeniedException", message="m"
                    ),
                ],
                "INCONCLUSIVE",
                "actor policy was not read",
            ),
            (
                "exchanger lacks its own grant",
                [
                    *replace(
                        c1_pass(),
                        rec(
                            "C1.exchange",
                            ok=False,
                            code="AccessDeniedException",
                            message="because no identity-based policy allows the action",
                            data={"appAccount": "111111111111"},
                        ),
                    ),
                    control,
                ],
                "INCONCLUSIVE",
                "own IAM policy",
            ),
            (
                "unparsable application",
                replace(
                    c1_pass(),
                    rec(
                        "C1.exchange",
                        data={"appAccount": None, "context": {"present": True}},
                    ),
                ),
                "INCONCLUSIVE",
                "did not parse",
            ),
            (
                "a re-run supersedes a refusal",
                [refused, *c1_pass()],
                "PASS",
                "exchanged on the application",
            ),
        ]
        for name, records, verdict, phrase in cases:
            with self.subTest(name):
                got, reason = phase0.verdict_c1(obs(*records))
                self.assertEqual(got, verdict, reason)
                self.assertIn(phrase, reason)

    def test_c2_unread_allow_list(self) -> None:
        """Probes that all succeed say nothing about the Deny when the allow-list was never read."""
        records = replace(
            c2_records(dict.fromkeys(phase0.PROBES)),
            rec("C2.allowlist.policy", ok=False, code="AccessDenied", message="scp"),
        )
        got, reason = phase0.verdict_c2(obs(*records))
        self.assertEqual(got, "INCONCLUSIVE", reason)
        self.assertIn("allow-list was not read", reason)

    def test_p_fixture_errors(self) -> None:
        """A missing table or object is inconclusive, never a failed gate."""
        missing = {"code": "NoSuchKey", "message": "m", "ok": False}
        cases = [
            (
                p_records(
                    q=rec(
                        "P1.query",
                        data={
                            "state": "FAILED",
                            "stateChangeReason": "TABLE_NOT_FOUND",
                        },
                    )
                ),
                "P1",
                "not an authorization refusal",
            ),
            (p_records(o=rec("P2.own", **missing)), "P2", "own NoSuchKey"),
            (p_records(o=rec("P2.other", **missing)), "P2", "other NoSuchKey"),
            (
                p_records(
                    o=rec("P2.own", ok=False, code="AccessDenied", message="m"),
                    x=rec("P2.other", **missing),
                ),
                "P2",
                "other NoSuchKey",
            ),
            (p_records(p=rec("P3.get", **missing)), "P3", "get NoSuchKey"),
        ]
        for records, gate, phrase in cases:
            with self.subTest(phrase):
                got = {g: (v, r) for g, v, r in phase0.verdict_p(obs(*records))}
                self.assertEqual(got[gate][0], "INCONCLUSIVE", got[gate][1])
                self.assertIn(phrase, got[gate][1])

    def test_c4_timing_guards(self) -> None:
        """A refresh before the deletion, one that never reached AWS, and a re-exchange before its token are all ignored."""
        early = c4_records([(5, "InvalidGrantException")])
        early = [
            *early[:1],
            rec(
                "C4.refresh.after.0",
                ok=False,
                code="InvalidGrantException",
                message="m",
                ts="2026-12-01T09:58:00.000Z",
            ),
            *early[1:2],
        ]
        local = [r for r in c4_records([(5, "Local:Fetch")]) if True]
        backwards = [
            r if r["label"] != "C4.reexchange.after" else {**r, "ts": at(1)}
            for r in c4_records([(5, "InvalidGrantException")], minted_at=3)
        ]
        cases = [
            ("refresh before deletion", early, "no refresh was recorded"),
            ("local refresh", local, "no refresh was recorded"),
            ("re-exchange before its token", backwards, "no re-exchange"),
        ]
        for name, records, phrase in cases:
            with self.subTest(name):
                got, reason = phase0.verdict_c4(records, obs(*records))
                self.assertEqual(got, "INCONCLUSIVE", reason)
                self.assertIn(phrase, reason)

    def test_c5_attribution(self) -> None:
        """C5 fails only on a link it can attribute, and calls config or permission errors what they are."""
        guid = "0f8fad5b-d9cb-469f-a165-70867728950e"

        def token(**t: Any) -> dict[str, Any]:
            return rec(
                "C5.login",
                data={
                    "idToken": {
                        "federated": {"providerName": "Entra", "userId": "oid-1"},
                        "oidClaim": "entra_oid",
                        "oidClaimValue": "oid-1",
                        **t,
                    }
                },
            )

        cases = [
            (
                "no federated identity",
                c5_records(l=token(federated=None)),
                "FAIL",
                "did not go through Entra",
            ),
            (
                "another user's object id",
                c5_records(l=token(oidClaimValue=guid)),
                "INCONCLUSIVE",
                "check the config",
            ),
            (
                "exchanger refused",
                c5_records(
                    e=rec(
                        "C5.exchange",
                        ok=False,
                        code="AccessDeniedException",
                        message="m",
                    )
                ),
                "INCONCLUSIVE",
                "C1 settles",
            ),
            (
                "local exchange",
                c5_records(
                    e=rec(
                        "C5.exchange",
                        ok=False,
                        code="Local:CredentialsProviderError",
                        message="m",
                    )
                ),
                "INCONCLUSIVE",
                "did not run",
            ),
            (
                "refused, mapping unread",
                [
                    r
                    for r in c5_records(
                        e=rec(
                            "C5.exchange",
                            ok=False,
                            code="InvalidGrantException",
                            message="m",
                        )
                    )
                    if r["label"] != "C5.tti"
                ],
                "INCONCLUSIVE",
                "mapping unread",
            ),
            (
                "store read refused",
                c5_records(
                    u=rec(
                        "C5.user", ok=False, code="AccessDeniedException", message="m"
                    )
                ),
                "INCONCLUSIVE",
                "needs identitystore:DescribeUser",
            ),
            (
                "claim path differs",
                c5_records(
                    t=rec(
                        "C5.tti",
                        data={
                            "claimAttributePath": "email",
                            "identityStoreAttributePath": "externalIds.value",
                        },
                    )
                ),
                "INCONCLUSIVE",
                "not the externalId mapping",
            ),
        ]
        for name, records, verdict, phrase in cases:
            with self.subTest(name):
                got, reason = phase0.verdict_c5(obs(*records))
                self.assertEqual(got, verdict, reason)
                self.assertIn(phrase, reason)


class SessionCountTest(unittest.TestCase):
    """C4 reads nothing into a deletion that ended no session."""

    def test_count(self) -> None:
        """A missing or zero count is inconclusive, whatever the refreshes did."""
        for name, mark, phrase in (
            (
                "unrecorded",
                rec("C4.deleted", ts=at(0, node=False)),
                "without --sessions-ended",
            ),
            (
                "none ended",
                rec("C4.deleted", data={"sessionsEnded": 0}, ts=at(0, node=False)),
                "ended no session",
            ),
        ):
            records = replace(c4_records([(1, None), (35, None)]), mark)
            with self.subTest(name):
                got, reason = phase0.verdict_c4(records, obs(*records))
                self.assertEqual(got, "INCONCLUSIVE", reason)
                self.assertIn(phrase, reason)


if __name__ == "__main__":
    unittest.main()
