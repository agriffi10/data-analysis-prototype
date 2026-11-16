"""Drive each ``phase0.py`` subcommand through real botocore clients with stubbed responses.

Nobody can run these against AWS before the client environment exists, so this is where a wrong
parameter name or a misread response shape is caught: botocore validates every request against the
service model and Stubber validates every response, then the verdict is read from what was logged.

Run from this directory with ``python3 -m unittest phase0_stub_test``; it needs boto3 and no network.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

import boto3
import botocore.session
import phase0
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

EXP = datetime(2026, 12, 1, 11, 0, tzinfo=UTC)
CONTEXT = "opaque-identity-context-value"


class FakeSession:
    """Hands out one stubbed client per service, whatever credentials the code asked for."""

    def __init__(self) -> None:
        """Create no clients yet.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.clients: dict[str, Any] = {}
        self.stubbers: dict[str, Stubber] = {}

    def stub(self, name: str) -> Stubber:
        """The stubber for a service, creating its client on first use.

        Args:
          name: The service.

        Returns:
          Its stubber, activated.

        Raises:
          None.
        """
        if name not in self.clients:
            client = botocore.session.get_session().create_client(
                name,
                region_name="us-east-1",
                aws_access_key_id="AKIDEXAMPLE",
                aws_secret_access_key="x" * 20,
            )
            self.clients[name] = client
            self.stubbers[name] = Stubber(client)
            self.stubbers[name].activate()
        return self.stubbers[name]

    def client(self, name: str, **_: Any) -> Any:
        """The stubbed client for a service.

        Args:
          name: The service.
          **_: Ignored client options.

        Returns:
          The client.

        Raises:
          None.
        """
        self.stub(name)
        return self.clients[name]


def body(text: bytes) -> StreamingBody:
    """A GetObject body.

    Args:
      text: The bytes.

    Returns:
      The streaming body.

    Raises:
      None.
    """
    return StreamingBody(io.BytesIO(text), len(text))


def creds(n: int) -> dict[str, Any]:
    """An AssumeRole response.

    Args:
      n: Distinguishes sessions.

    Returns:
      The response.

    Raises:
      None.
    """
    return {
        "Credentials": {
            "AccessKeyId": f"ASIA{n:016d}",
            "SecretAccessKey": f"secret-access-key-{n}-xxxx",
            "SessionToken": f"session-token-{n}-xxxx",
            "Expiration": EXP,
        },
        "AssumedRoleUser": {
            "AssumedRoleId": f"AROA:s{n}",
            "Arn": f"arn:aws:sts::222222222222:assumed-role/carrier/s{n}",
        },
    }


def describe_user_response(client: Any, base: dict[str, Any]) -> dict[str, Any]:
    """A DescribeUser response valid for whichever botocore is installed.

    Newer models require ``UserArn`` and ``Revision``, and older ones refuse them, so add them only
    where the installed model has them.

    Args:
      client: The stubbed identitystore client.
      base: The fields every version accepts.

    Returns:
      The response.

    Raises:
      None.
    """
    members = client.meta.service_model.operation_model(
        "DescribeUser"
    ).output_shape.members
    extra = {
        "UserArn": "arn:aws:identitystore::111111111111:identitystore/d-1234567890/user/user-1",
        "Revision": "1",
    }
    return {**base, **{k: v for k, v in extra.items() if k in members}}


class StubbedRunTest(unittest.TestCase):
    """Each subcommand's AWS calls are well-formed, and a stubbed run reaches the intended verdict."""

    def setUp(self) -> None:
        """Point the scripts at a temporary evidence file and a kept exchange.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "secrets").mkdir()
        kept = {
            "identityContext": CONTEXT,
            "accessToken": "atatatatatatat",
            "refreshToken": "rfrfrfrfrfrfrf",
            "contextExp": int(EXP.timestamp()),
            "identityStoreUserId": "user-1",
        }
        (tmp / "secrets" / "idc-alice-1.json").write_text(json.dumps(kept))
        values = {
            "PHASE0_EVIDENCE": str(tmp / "evidence.jsonl"),
            "PHASE0_SECRETS": str(tmp / "secrets"),
            "AWS_REGION": "us-east-1",
            "ASSUMER_PROFILE": "assumer",
            "CARRIER_ROLE_ARN": "arn:aws:iam::222222222222:role/carrier",
            "ACCESS_GRANTS_ACCOUNT_ID": "222222222222",
            "PROBE_BUCKET": "probe-bucket",
            "OTHER_USER_KEY": "phase0-probe/other-user/secret.txt",
            "PUT_PREFIX": "phase0-probe/put/",
            "LIST_PREFIX": "phase0-probe/",
            "SCRATCH_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/222222222222/phase0-scratch",
            "PSET_ACCOUNT_ID": "222222222222",
            "PSET_NAME": "Phase0Probe",
            "PROBE_QUERY": "SELECT count(*) FROM phase0_db.phase0_t",
            "IDC_WORKGROUP": "phase0-idc",
            "P2_OWN_KEY": "phase0-probe/abac/alice/probe.txt",
            "P2_OTHER_KEY": "phase0-probe/abac/bob/probe.txt",
            "P3_PREFIX": "phase0-probe/p3/",
            "ENTRA_TEST_USER_OID": "oid-1",
            "EXPECTED_IDC_USERNAME": "alice",
            "ENTRA_IDP_NAME": "Entra",
            "IDENTITY_STORE_ID": "d-1234567890",
            "TTI_ARN": "arn:aws:sso::111111111111:trustedTokenIssuer/ssoins-aaaa/tti-bbbb",
        }
        self.env = mock.patch.dict(os.environ, values)
        self.env.start()
        self.fake = FakeSession()
        self.patch = mock.patch.object(
            phase0, "session", lambda profile=None, creds=None: self.fake
        )
        self.patch.start()
        self.sso_patch = mock.patch.object(boto3, "Session", lambda **_: self.fake)
        self.sso_patch.start()

    def tearDown(self) -> None:
        """Undo the patches and remove the temporary files.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        for stubber in self.fake.stubbers.values():
            stubber.assert_no_pending_responses()
        self.sso_patch.stop()
        self.patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def run_cli(self, *argv: str) -> dict[str, dict[str, Any]]:
        """Run a subcommand and index what it logged.

        Args:
          *argv: The arguments.

        Returns:
          The latest record per label.

        Raises:
          None.
        """
        phase0.main(list(argv))
        return phase0.latest(phase0.load(Path(os.environ["PHASE0_EVIDENCE"])))

    def test_assume_reaches_a_pass_shape(self) -> None:
        """Check 1's assumption sends ProvidedContexts and reads the grants back."""
        sts, s3c = self.fake.stub("sts"), self.fake.stub("s3control")
        sts.add_response(
            "get_caller_identity",
            {
                "Account": "222222222222",
                "Arn": "arn:aws:sts::222222222222:assumed-role/api-role/s",
            },
        )
        sts.add_response(
            "assume_role",
            creds(1),
            {
                "RoleArn": ANY,
                "RoleSessionName": ANY,
                "ProvidedContexts": [
                    {"ProviderArn": phase0.PROVIDER_ARN, "ContextAssertion": CONTEXT}
                ],
            },
        )
        sts.add_response(
            "assume_role", creds(2), {"RoleArn": ANY, "RoleSessionName": ANY}
        )
        s3c.add_response(
            "list_caller_access_grants",
            {
                "CallerAccessGrantsList": [
                    {
                        "GrantScope": "s3://probe-bucket/phase0-probe/alice/*",
                        "Permission": "READWRITE",
                    }
                ]
            },
            {"AccountId": "222222222222"},
        )
        s3c.add_response(
            "list_caller_access_grants",
            {"CallerAccessGrantsList": []},
            {"AccountId": "222222222222"},
        )
        obs = self.run_cli("assume", "--context", "alice-1")
        self.assertTrue(obs["C1.assume.with"]["data"]["expirationEqualsContextExp"])
        self.assertEqual(
            (
                obs["C1.grants.with"]["data"]["count"],
                obs["C1.grants.without"]["data"]["count"],
            ),
            (1, 0),
        )
        raw = Path(os.environ["PHASE0_EVIDENCE"]).read_text()
        for secret in (CONTEXT, "secret-access-key-1-xxxx", "session-token-2-xxxx"):
            self.assertNotIn(secret, raw)

    def test_allowlist_reads_the_policy_and_runs_every_probe(self) -> None:
        """Check 2 reads the live allow-list, then probes with and without the context; a refusal under the context reads as the Deny."""
        iam, sts, s3c, s3, sqs = (
            self.fake.stub(n) for n in ("iam", "sts", "s3control", "s3", "sqs")
        )
        doc = {
            "Statement": [
                {
                    "Effect": "Deny",
                    "NotAction": ["s3:GetAccessGrant*", "athena:*"],
                    "Resource": "*",
                }
            ]
        }
        iam.add_response(
            "get_policy",
            {"Policy": {"DefaultVersionId": "v12"}},
            {"PolicyArn": phase0.ALLOW_LIST_ARN},
        )
        iam.add_response(
            "get_policy_version",
            {"PolicyVersion": {"Document": json.dumps(doc), "VersionId": "v12"}},
            {"PolicyArn": phase0.ALLOW_LIST_ARN, "VersionId": "v12"},
        )
        denied = {
            "service_error_code": "AccessDenied",
            "service_message": "explicit deny in a session policy",
            "http_status_code": 403,
        }
        for n, refused in ((1, True), (2, False)):
            sts.add_response(
                "assume_role",
                creds(n),
                {
                    "RoleArn": ANY,
                    "RoleSessionName": ANY,
                    **({"ProvidedContexts": ANY} if refused else {}),
                },
            )
            s3c.add_response(
                "list_caller_access_grants",
                {"CallerAccessGrantsList": [{"Permission": "READ"}] if refused else []},
                {"AccountId": "222222222222"},
            )
            if refused:
                s3.add_client_error(
                    "get_object",
                    expected_params={
                        "Bucket": "probe-bucket",
                        "Key": "phase0-probe/other-user/secret.txt",
                    },
                    **denied,
                )
                s3.add_client_error(
                    "put_object",
                    expected_params={"Bucket": "probe-bucket", "Key": ANY, "Body": ANY},
                    **denied,
                )
                s3.add_client_error(
                    "list_objects_v2",
                    expected_params={
                        "Bucket": "probe-bucket",
                        "Prefix": "phase0-probe/",
                        "MaxKeys": 5,
                    },
                    **denied,
                )
                sqs.add_client_error(
                    "send_message",
                    expected_params={"QueueUrl": ANY, "MessageBody": ANY},
                    service_error_code="AccessDenied",
                    service_message="m",
                    http_status_code=403,
                )
            else:
                s3.add_response(
                    "get_object",
                    {"Body": body(b"secret")},
                    {
                        "Bucket": "probe-bucket",
                        "Key": "phase0-probe/other-user/secret.txt",
                    },
                )
                s3.add_response(
                    "put_object",
                    {},
                    {
                        "Bucket": "probe-bucket",
                        "Key": "phase0-probe/put/probe-without.txt",
                        "Body": ANY,
                    },
                )
                s3.add_response(
                    "list_objects_v2",
                    {"KeyCount": 2},
                    {"Bucket": "probe-bucket", "Prefix": "phase0-probe/", "MaxKeys": 5},
                )
                sqs.add_response(
                    "send_message",
                    {"MessageId": "m-1"},
                    {"QueueUrl": ANY, "MessageBody": ANY},
                )
        obs = self.run_cli("allowlist", "--context", "alice-1")
        self.assertEqual(
            obs["C2.allowlist.policy"]["data"]["exempt"],
            dict.fromkeys(phase0.PROBES, False),
        )
        self.assertEqual(phase0.verdict_c2(obs)[0], "MEASURED:DENY_IN_EFFECT")

    def test_pgates_calls_the_portal_api_and_every_probe(self) -> None:
        """Check 3 redeems the access token on the portal API, then runs P1 to P3 on what it vends."""
        sso, sts, s3c, athena, s3 = (
            self.fake.stub(n) for n in ("sso", "sts", "s3control", "athena", "s3")
        )
        token = {"accessToken": "atatatatatatat"}
        sso.add_response(
            "list_accounts", {"accountList": [{"accountId": "222222222222"}]}, token
        )
        sso.add_response(
            "list_account_roles",
            {"roleList": [{"roleName": "Phase0Probe", "accountId": "222222222222"}]},
            {**token, "accountId": "222222222222"},
        )
        sso.add_response(
            "get_role_credentials",
            {
                "roleCredentials": {
                    "accessKeyId": "ASIAPSET",
                    "secretAccessKey": "pspspspspspsps",
                    "sessionToken": "stststststststst",
                    "expiration": 1,
                }
            },
            {**token, "roleName": "Phase0Probe", "accountId": "222222222222"},
        )
        sts.add_response(
            "get_caller_identity",
            {
                "Account": "222222222222",
                "Arn": "arn:aws:sts::222222222222:assumed-role/AWSReservedSSO_Phase0Probe_x/alice",
            },
        )
        s3c.add_response(
            "list_caller_access_grants",
            {"CallerAccessGrantsList": []},
            {"AccountId": "222222222222"},
        )
        athena.add_client_error(
            "start_query_execution",
            service_error_code="InvalidRequestException",
            service_message="You do not have access to phase0-idc",
            expected_params={"QueryString": ANY, "WorkGroup": "phase0-idc"},
        )
        s3.add_response(
            "get_object",
            {"Body": body(b"own")},
            {"Bucket": "probe-bucket", "Key": "phase0-probe/abac/alice/probe.txt"},
        )
        s3.add_client_error(
            "get_object",
            service_error_code="AccessDenied",
            service_message="m",
            http_status_code=403,
            expected_params={
                "Bucket": "probe-bucket",
                "Key": "phase0-probe/abac/bob/probe.txt",
            },
        )
        s3.add_response(
            "get_object",
            {"Body": body(b"seed")},
            {"Bucket": "probe-bucket", "Key": "phase0-probe/p3/seed.txt"},
        )
        s3.add_response(
            "put_object",
            {},
            {"Bucket": "probe-bucket", "Key": "phase0-probe/p3/put.txt", "Body": ANY},
        )
        s3.add_response(
            "list_objects_v2",
            {"KeyCount": 2},
            {"Bucket": "probe-bucket", "Prefix": "phase0-probe/p3/", "MaxKeys": 5},
        )
        obs = self.run_cli("pgates", "--token", "alice-1")
        got = {gate: verdict for gate, verdict, _ in phase0.verdict_p(obs)}
        self.assertEqual(got, {"P1": "FAIL", "P2": "PASS", "P3": "PASS"})
        self.assertNotIn(
            "pspspspspspsps", Path(os.environ["PHASE0_EVIDENCE"]).read_text()
        )

    def test_entra_hop_reads_the_mapping_and_the_user(self) -> None:
        """Check 5 reads the trusted token issuer's mapping and the resolved user's externalIds."""
        admin, store = self.fake.stub("sso-admin"), self.fake.stub("identitystore")
        admin.add_response(
            "describe_trusted_token_issuer",
            {
                "TrustedTokenIssuerConfiguration": {
                    "OidcJwtConfiguration": {
                        "IssuerUrl": "https://issuer",
                        "ClaimAttributePath": "entra_oid",
                        "IdentityStoreAttributePath": "externalIds.value",
                        "JwksRetrievalOption": "OPEN_ID_DISCOVERY",
                    }
                }
            },
            {"TrustedTokenIssuerArn": os.environ["TTI_ARN"]},
        )
        store.add_response(
            "describe_user",
            describe_user_response(
                store.client,
                {
                    "IdentityStoreId": "d-1234567890",
                    "UserId": "user-1",
                    "UserName": "alice",
                    "ExternalIds": [{"Issuer": "entra", "Id": "oid-1"}],
                },
            ),
            {"IdentityStoreId": "d-1234567890", "UserId": "user-1"},
        )
        obs = self.run_cli("entra-hop", "--token", "alice-1", "--profile", "admin")
        self.assertEqual(
            obs["C5.tti"]["data"]["identityStoreAttributePath"], "externalIds.value"
        )
        self.assertEqual(
            obs["C5.user"]["data"]["externalIds"], [{"Issuer": "entra", "Id": "oid-1"}]
        )
        self.assertEqual(obs["C5.expected"]["data"]["userId"], "user-1")

    def test_actor_policy_lists_the_named_principals(self) -> None:
        """Check 1's attribution reads the IAM authentication method and keeps every named principal."""
        admin = self.fake.stub("sso-admin")
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": ["arn:aws:iam::222222222222:role/phase0-exchanger"]
                    },
                    "Action": "sso-oauth:CreateTokenWithIAM",
                    "Resource": "*",
                },
                {
                    "Effect": "Deny",
                    "Principal": {"AWS": "arn:aws:iam::333333333333:role/x"},
                    "Action": "*",
                    "Resource": "*",
                },
            ],
        }
        app = "arn:aws:sso::111111111111:application/ssoins-aaaa/apl-bbbb"
        admin.add_response(
            "get_application_authentication_method",
            {"AuthenticationMethod": {"Iam": {"ActorPolicy": policy}}},
            {"ApplicationArn": app, "AuthenticationMethodType": "IAM"},
        )
        obs = self.run_cli("actor-policy", "--profile", "admin", "--app-arn", app)
        self.assertEqual(
            obs["C1.actor"]["data"]["principals"],
            ["arn:aws:iam::222222222222:role/phase0-exchanger"],
        )

    def test_entra_hop_without_a_kept_exchange_still_records_what_was_expected(
        self,
    ) -> None:
        """A refused C5 exchange keeps no token file; entra-hop still records the expectation and the mapping."""
        admin = self.fake.stub("sso-admin")
        admin.add_response(
            "describe_trusted_token_issuer",
            {
                "TrustedTokenIssuerConfiguration": {
                    "OidcJwtConfiguration": {
                        "IssuerUrl": "https://issuer",
                        "ClaimAttributePath": "entra_oid",
                        "IdentityStoreAttributePath": "externalIds.value",
                        "JwksRetrievalOption": "OPEN_ID_DISCOVERY",
                    }
                }
            },
            {"TrustedTokenIssuerArn": os.environ["TTI_ARN"]},
        )
        obs = self.run_cli("entra-hop", "--token", "never-kept", "--profile", "admin")
        self.assertIsNone(obs["C5.expected"]["data"]["userId"])
        self.assertEqual(obs["C5.user"]["code"], "Local:NoUserId")


if __name__ == "__main__":
    unittest.main()
