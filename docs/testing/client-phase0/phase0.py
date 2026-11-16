"""The Python half of the client-environment Phase 0 checks: the assumer, the probes and the verdicts.

The exchanger (``exchange.mjs``) stands in for the Next.js server's task role; this script stands in
for the API's role, which assumes the carrier with the identity context and then acts. Every step
appends what it saw to the shared evidence file the moment it sees it, and ``verdict`` reads that
file back and states each check's outcome as a REASON, never an exit code: a refusal that never
reached AWS, or a control that failed, makes a check INCONCLUSIVE rather than a FAIL.

Attributes:
  PROVIDER_ARN: The context provider STS expects for an Identity Center identity context.
  ALLOW_LIST_ARN: The AWS managed policy whose Deny check 2 asks about.
  GUID_SHAPE: The shape of an Entra object id.
  JWT_SHAPE: A pattern no evidence line may match.
  DENIED: Error codes that mean an authorization refusal rather than a broken request.
  PROBES: Check 2's probes, each with the IAM action the allow-list would have to deny.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeGuard

if TYPE_CHECKING:
    from collections.abc import Callable

PROVIDER_ARN = "arn:aws:iam::aws:contextProvider/IdentityCenter"
ALLOW_LIST_ARN = (
    "arn:aws:iam::aws:policy/AWSIAMIdentityCenterAllowListForIdentityContext"
)
GUID_SHAPE = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
DENIED = {"AccessDenied", "AccessDeniedException", "AuthorizationError"}
PROBES = {
    "getobject_other": "s3:GetObject",
    "putobject": "s3:PutObject",
    "listobjects": "s3:ListBucket",
    "sqs_send": "sqs:SendMessage",
}

Record = dict[str, Any]


def fingerprint(value: str | None) -> dict[str, Any] | None:
    """Reduce a secret to a length and a hash prefix, comparable across records but not replayable.

    Args:
      value: The secret, or None.

    Returns:
      ``{"len", "sha256_12"}``, or None when there was no value.

    Raises:
      None.
    """
    if value is None:
        return None
    return {
        "len": len(value),
        "sha256_12": hashlib.sha256(value.encode()).hexdigest()[:12],
    }


def refuse_inside_checkout(path: Path) -> None:
    """Refuse a path inside a git checkout, so evidence and tokens cannot be committed by accident.

    Args:
      path: A file or directory.

    Returns:
      None.

    Raises:
      SystemExit: When an ancestor holds a ``.git`` entry.
    """
    for parent in [path.resolve(), *path.resolve().parents]:
        if (parent / ".git").exists():
            raise SystemExit(
                f"{path} is inside the git checkout at {parent}; keep evidence and tokens outside any repository"
            )


def env(name: str) -> str:
    """Read a required environment variable.

    Args:
      name: The variable.

    Returns:
      Its value.

    Raises:
      SystemExit: When it is unset or empty.
    """
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"{name} is not set; source your copy of config.example.env first"
        )
    return value


class Evidence:
    """Appends observations to the shared JSON-lines evidence file, one synced line at a time."""

    def __init__(self, path: Path) -> None:
        """Open the log for appending.

        Args:
          path: The evidence file; refused inside a checkout.

        Returns:
          None.

        Raises:
          SystemExit: When the path is inside a checkout.
        """
        refuse_inside_checkout(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.secrets: list[str] = []

    def add_secrets(self, *values: str | None) -> None:
        """Register values that must never be written.

        Args:
          *values: Secrets seen so far; short or missing ones are ignored.

        Returns:
          None.

        Raises:
          None.
        """
        self.secrets.extend(v for v in values if isinstance(v, str) and len(v) >= 8)

    def record(self, label: str, outcome: Record) -> Record:
        """Write one observation and sync it before returning.

        Args:
          label: The runbook label the observation answers.
          outcome: ``ok`` plus ``code``/``message`` on failure and ``data``.

        Returns:
          The record as written.

        Raises:
          ValueError: When the line would hold a JWT or a registered secret; nothing is written then.
        """
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "label": label,
            "source": "python",
            **outcome,
        }
        line = json.dumps(entry, default=str)
        if JWT_SHAPE.search(line):
            raise ValueError(f"refused to log {label}: the record holds a JWT")
        if any(secret in line for secret in self.secrets):
            raise ValueError(
                f"refused to log {label}: the record holds a registered secret"
            )
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (line + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        shown = (
            "ok"
            if outcome.get("ok")
            else f"{outcome.get('code')}: {outcome.get('message')}"
        )
        print(f"[{label}] {shown}")
        return entry


def attempt(call: Callable[[], Any]) -> tuple[Record, Any]:
    """Run one AWS call and reduce its outcome to what the verdicts read.

    A ``Local:`` code marks a failure that never reached AWS (no credentials, no network), which a
    verdict must not read as a refusal.

    Args:
      call: The call.

    Returns:
      The outcome, and the call's result when it succeeded.

    Raises:
      None.
    """
    from botocore.exceptions import ClientError

    try:
        return {"ok": True}, call()
    except ClientError as err:
        error = err.response.get("Error", {})
        status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return {
            "ok": False,
            "code": error.get("Code", "Unknown"),
            "message": error.get("Message", ""),
            "data": {"httpStatus": status},
        }, None
    except Exception as err:  # noqa: BLE001
        return {
            "ok": False,
            "code": f"Local:{type(err).__name__}",
            "message": str(err),
            "data": {},
        }, None


def secrets_dir() -> Path:
    """The private directory the Node scripts keep tokens in.

    Args:
      None.

    Returns:
      Its path.

    Raises:
      SystemExit: When unset or inside a checkout.
    """
    path = Path(env("PHASE0_SECRETS"))
    refuse_inside_checkout(path)
    return path


def read_kept(name: str) -> dict[str, Any]:
    """Read a token file ``exchange.mjs`` wrote.

    Args:
      name: The ``--out`` name it was written under.

    Returns:
      Its contents.

    Raises:
      SystemExit: When it does not exist.
    """
    path = secrets_dir() / f"idc-{name}.json"
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist; run exchange.mjs with --out {name} first"
        )
    kept: dict[str, Any] = json.loads(path.read_text())
    return kept


def session(profile: str | None = None, creds: dict[str, str] | None = None) -> Any:
    """A boto3 session from a named profile or from temporary credentials.

    Args:
      profile: An AWS CLI profile name.
      creds: ``AccessKeyId``/``SecretAccessKey``/``SessionToken``.

    Returns:
      The session.

    Raises:
      None.
    """
    import boto3

    region = env("AWS_REGION")
    if creds is not None:
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
    return boto3.Session(profile_name=profile, region_name=region)


def principal_of(arn: str | None) -> str | None:
    """The role behind a caller or policy ARN, so two sessions of one role, and the role a policy names, compare equal.

    An assumed-role ARN carries the role's name but not its path, so a role ARN's path is dropped too.

    Args:
      arn: A ``GetCallerIdentity`` ARN, or a principal from a policy.

    Returns:
      ``<account>:role/<name>`` for a role, ``<account>:<rest>`` otherwise, or None.

    Raises:
      None.
    """
    if not arn:
        return None
    match = re.match(r"arn:aws[a-z-]*:sts::(\d{12}):assumed-role/([^/]+)/", arn)
    if match:
        return f"{match.group(1)}:role/{match.group(2)}"
    match = re.match(r"arn:aws[a-z-]*:iam::(\d{12}):role/(?:.*/)?([^/]+)$", arn)
    if match:
        return f"{match.group(1)}:role/{match.group(2)}"
    match = re.match(r"arn:aws[a-z-]*:iam::(\d{12}):(.+)$", arn)
    return f"{match.group(1)}:{match.group(2)}" if match else arn


def whoami(evidence: Evidence, sess: Any, label: str) -> Record:
    """Record which principal a session is.

    Args:
      evidence: The log.
      sess: The session.
      label: The evidence label.

    Returns:
      The record written.

    Raises:
      None.
    """
    outcome, res = attempt(lambda: sess.client("sts").get_caller_identity())
    if res is not None:
        outcome["data"] = {"account": res["Account"], "arn": res["Arn"]}
    return evidence.record(label, outcome)


def assume_carrier(
    evidence: Evidence,
    assumer: Any,
    label: str,
    context: str | None,
    context_exp: int | None,
) -> dict[str, str] | None:
    """Assume the carrier role, with the identity context or without it, and record the result.

    Args:
      evidence: The log.
      assumer: The assumer's session.
      label: The evidence label.
      context: The identity context, or None for the control.
      context_exp: The context's expiry (epoch seconds), to compare with the session's.

    Returns:
      The carrier credentials, or None when refused.

    Raises:
      None.
    """
    kwargs: dict[str, Any] = {
        "RoleArn": env("CARRIER_ROLE_ARN"),
        "RoleSessionName": f"phase0-{int(time.time())}",
    }
    if context is not None:
        kwargs["ProvidedContexts"] = [
            {"ProviderArn": PROVIDER_ARN, "ContextAssertion": context}
        ]
    outcome, res = attempt(lambda: assumer.client("sts").assume_role(**kwargs))
    if res is None:
        evidence.record(label, outcome)
        return None
    creds: dict[str, Any] = res["Credentials"]
    evidence.add_secrets(creds["SecretAccessKey"], creds["SessionToken"])
    expiration = creds["Expiration"]
    outcome["data"] = {
        "withContext": context is not None,
        "assumedRoleArn": res["AssumedRoleUser"]["Arn"],
        "expiration": expiration.isoformat(),
        "contextExp": context_exp,
        "expirationEqualsContextExp": (int(expiration.timestamp()) == context_exp)
        if context_exp
        else None,
        "packedPolicySize": res.get("PackedPolicySize"),
    }
    evidence.record(label, outcome)
    return creds


def caller_grants(evidence: Evidence, sess: Any, label: str) -> None:
    """Record how many Access Grants the session's caller sees: none unless it is identity-enhanced.

    Args:
      evidence: The log.
      sess: The carrier session.
      label: The evidence label.

    Returns:
      None.

    Raises:
      None.
    """
    account = os.environ.get("ACCESS_GRANTS_ACCOUNT_ID")
    if not account:
        evidence.record(
            label,
            {
                "ok": False,
                "code": "Local:Skipped",
                "message": "ACCESS_GRANTS_ACCOUNT_ID is not set",
                "data": {},
            },
        )
        return
    outcome, res = attempt(
        lambda: sess.client("s3control").list_caller_access_grants(AccountId=account)
    )
    if res is not None:
        grants = res.get("CallerAccessGrantsList", [])
        outcome["data"] = {
            "count": len(grants),
            "scopes": [g.get("GrantScope") for g in grants],
        }
    evidence.record(label, outcome)


def cmd_assume(args: argparse.Namespace, evidence: Evidence) -> None:
    """Check 1's assumption half, and check 4's assumption on an old context.

    Args:
      args: ``--context`` (the kept name) and ``--prefix`` (the label prefix).
      evidence: The log.

    Returns:
      None.

    Raises:
      None.
    """
    kept = read_kept(args.context)
    context = kept.get("identityContext")
    evidence.add_secrets(
        context, kept.get("refreshToken"), kept.get("accessToken"), kept.get("idToken")
    )
    assumer = session(profile=env("ASSUMER_PROFILE"))
    whoami(evidence, assumer, f"{args.prefix}.assumer")
    with_ctx = assume_carrier(
        evidence, assumer, f"{args.prefix}.assume.with", context, kept.get("contextExp")
    )
    if args.no_control:
        return
    without = assume_carrier(
        evidence, assumer, f"{args.prefix}.assume.without", None, None
    )
    if with_ctx is not None:
        caller_grants(evidence, session(creds=with_ctx), f"{args.prefix}.grants.with")
    if without is not None:
        caller_grants(evidence, session(creds=without), f"{args.prefix}.grants.without")


def allow_list_listing(evidence: Evidence, sess: Any) -> None:
    """Record the live allow-list version and whether each probe's action escapes its Deny.

    A probe whose action the allow-list itself exempts cannot tell the Deny apart from its absence,
    so the verdict needs this before reading a probe's result.

    Args:
      evidence: The log.
      sess: A session allowed ``iam:GetPolicy`` and ``iam:GetPolicyVersion``.

    Returns:
      None.

    Raises:
      None.
    """
    iam = sess.client("iam")
    outcome, policy = attempt(lambda: iam.get_policy(PolicyArn=ALLOW_LIST_ARN))
    if policy is None:
        evidence.record("C2.allowlist.policy", outcome)
        return
    version = policy["Policy"]["DefaultVersionId"]
    outcome, doc = attempt(
        lambda: iam.get_policy_version(PolicyArn=ALLOW_LIST_ARN, VersionId=version)
    )
    if doc is None:
        evidence.record("C2.allowlist.policy", outcome)
        return
    document = doc["PolicyVersion"]["Document"]
    if isinstance(document, str):
        from urllib.parse import unquote

        document = json.loads(unquote(document))
    exempt: list[str] = []
    for statement in document.get("Statement", []):
        if statement.get("Effect") == "Deny":
            actions = statement.get("NotAction", [])
            exempt.extend([actions] if isinstance(actions, str) else actions)
    listed = {
        name: any(
            fnmatch.fnmatchcase(action.lower(), pattern.lower()) for pattern in exempt
        )
        for name, action in PROBES.items()
    }
    evidence.record(
        "C2.allowlist.policy",
        {
            "ok": True,
            "data": {
                "versionId": version,
                "exemptCount": len(exempt),
                "exempt": listed,
            },
        },
    )


def run_probes(evidence: Evidence, sess: Any, suffix: str) -> None:
    """Run check 2's four probes on one session.

    Args:
      evidence: The log.
      sess: The carrier session, with or without the context.
      suffix: ``with`` or ``without``.

    Returns:
      None.

    Raises:
      None.
    """
    s3 = sess.client("s3")
    bucket = env("PROBE_BUCKET")
    calls: dict[str, Callable[[], Any]] = {
        "getobject_other": lambda: s3.get_object(
            Bucket=bucket, Key=env("OTHER_USER_KEY")
        )["Body"].read(64),
        "putobject": lambda: s3.put_object(
            Bucket=bucket,
            Key=f"{env('PUT_PREFIX')}probe-{suffix}.txt",
            Body=b"phase0 allow-list probe",
        ),
        "listobjects": lambda: s3.list_objects_v2(
            Bucket=bucket, Prefix=env("LIST_PREFIX"), MaxKeys=5
        ).get("KeyCount"),
        "sqs_send": lambda: sess.client("sqs").send_message(
            QueueUrl=env("SCRATCH_QUEUE_URL"), MessageBody="phase0 allow-list probe"
        )["MessageId"],
    }
    for name, call in calls.items():
        outcome, _ = attempt(call)
        evidence.record(f"C2.{name}.{suffix}", outcome)


def cmd_allowlist(args: argparse.Namespace, evidence: Evidence) -> None:
    """Check 2: the same probes on the carrier with the context and without it.

    Args:
      args: ``--context``.
      evidence: The log.

    Returns:
      None.

    Raises:
      None.
    """
    kept = read_kept(args.context)
    context = kept.get("identityContext")
    evidence.add_secrets(
        context, kept.get("refreshToken"), kept.get("accessToken"), kept.get("idToken")
    )
    assumer = session(profile=env("ASSUMER_PROFILE"))
    allow_list_listing(evidence, assumer)
    for suffix, ctx in (("with", context), ("without", None)):
        creds = assume_carrier(
            evidence,
            assumer,
            f"C2.assume.{suffix}",
            ctx,
            kept.get("contextExp") if ctx else None,
        )
        if creds is None:
            continue
        carrier = session(creds=creds)
        caller_grants(evidence, carrier, f"C2.grants.{suffix}")
        run_probes(evidence, carrier, suffix)


def run_query(evidence: Evidence, sess: Any, label: str) -> None:
    """Run the probe query on the Identity Center workgroup and record how it ended.

    Args:
      evidence: The log.
      sess: The session to query from.
      label: The evidence label.

    Returns:
      None.

    Raises:
      None.
    """
    athena = sess.client("athena")
    outcome, started = attempt(
        lambda: athena.start_query_execution(
            QueryString=env("PROBE_QUERY"), WorkGroup=env("IDC_WORKGROUP")
        )
    )
    if started is None:
        evidence.record(label, outcome)
        return
    query_id = started["QueryExecutionId"]
    status: dict[str, Any] = {}
    for _ in range(60):
        outcome, res = attempt(
            lambda: athena.get_query_execution(QueryExecutionId=query_id)
        )
        if res is None:
            evidence.record(label, outcome)
            return
        status = res["QueryExecution"]["Status"]
        if status["State"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            break
        time.sleep(2)
    evidence.record(
        label,
        {
            "ok": True,
            "data": {
                "queryId": query_id,
                "state": status.get("State"),
                "stateChangeReason": status.get("StateChangeReason"),
            },
        },
    )


def read_object(s3: Any, bucket: str, key: str) -> Callable[[], Any]:
    """A deferred read of an object's first bytes, for ``attempt``.

    Args:
      s3: An S3 client.
      bucket: The bucket.
      key: The key.

    Returns:
      The call.

    Raises:
      None.
    """
    return lambda: s3.get_object(Bucket=bucket, Key=key)["Body"].read(64)


def cmd_pgates(args: argparse.Namespace, evidence: Evidence) -> None:
    """Check 3: P1 to P3 on credentials the SSO portal API vends for the user's permission set.

    Args:
      args: ``--token`` (the kept name of an exchange on the ``sso:account:access`` application).
      evidence: The log.

    Returns:
      None.

    Raises:
      None.
    """
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    kept = read_kept(args.token)
    token = kept.get("accessToken")
    evidence.add_secrets(
        token,
        kept.get("refreshToken"),
        kept.get("identityContext"),
        kept.get("idToken"),
    )
    sso = boto3.Session(region_name=env("AWS_REGION")).client(
        "sso", config=Config(signature_version=UNSIGNED)
    )
    account, role = env("PSET_ACCOUNT_ID"), env("PSET_NAME")
    outcome, res = attempt(lambda: sso.list_accounts(accessToken=token))
    if res is not None:
        outcome["data"] = {
            "count": len(res.get("accountList", [])),
            "targetListed": any(
                a["accountId"] == account for a in res.get("accountList", [])
            ),
        }
    evidence.record("P.accounts", outcome)
    outcome, res = attempt(
        lambda: sso.list_account_roles(accessToken=token, accountId=account)
    )
    if res is not None:
        outcome["data"] = {
            "roles": [r["roleName"] for r in res.get("roleList", [])],
            "roleListed": any(r["roleName"] == role for r in res.get("roleList", [])),
        }
    evidence.record("P.roles", outcome)
    outcome, res = attempt(
        lambda: sso.get_role_credentials(
            roleName=role, accountId=account, accessToken=token
        )
    )
    if res is None:
        evidence.record("P.creds", outcome)
        return
    rc = res["roleCredentials"]
    evidence.add_secrets(rc["secretAccessKey"], rc["sessionToken"])
    evidence.record(
        "P.creds", {"ok": True, "data": {"expiration": rc.get("expiration")}}
    )
    pset = session(
        creds={
            "AccessKeyId": rc["accessKeyId"],
            "SecretAccessKey": rc["secretAccessKey"],
            "SessionToken": rc["sessionToken"],
        }
    )
    whoami(evidence, pset, "P.caller")
    caller_grants(evidence, pset, "P1.grants")
    run_query(evidence, pset, "P1.query")
    s3 = pset.client("s3")
    bucket = env("PROBE_BUCKET")
    for label, key in (
        ("P2.own", env("P2_OWN_KEY")),
        ("P2.other", env("P2_OTHER_KEY")),
        ("P3.get", f"{env('P3_PREFIX')}seed.txt"),
    ):
        outcome, _ = attempt(read_object(s3, bucket, key))
        evidence.record(label, outcome)
    outcome, _ = attempt(
        lambda: s3.put_object(
            Bucket=bucket, Key=f"{env('P3_PREFIX')}put.txt", Body=b"phase0 p3 probe"
        )
    )
    evidence.record("P3.put", outcome)
    outcome, _ = attempt(
        lambda: s3.list_objects_v2(
            Bucket=bucket, Prefix=env("P3_PREFIX"), MaxKeys=5
        ).get("KeyCount")
    )
    evidence.record("P3.list", outcome)


def cmd_entra_hop(args: argparse.Namespace, evidence: Evidence) -> None:
    """Check 5's Identity Center side: what the trusted token issuer maps, and whom it resolved.

    Run with a profile allowed ``identitystore:DescribeUser`` and ``sso:DescribeTrustedTokenIssuer``
    on the organization instance; an Identity Center admin can run this subcommand alone, passing
    ``--user-id`` instead of a kept exchange. It records what is expected first, so a refused
    exchange, which keeps nothing, still reaches its verdict.

    Args:
      args: ``--token`` or ``--user-id``, and ``--profile``.
      evidence: The log.

    Returns:
      None.

    Raises:
      None.
    """
    user_id = args.user_id
    if not user_id and args.token:
        path = secrets_dir() / f"idc-{args.token}.json"
        if path.exists():
            user_id = json.loads(path.read_text()).get("identityStoreUserId")
    evidence.record(
        "C5.expected",
        {
            "ok": True,
            "data": {
                "oid": env("ENTRA_TEST_USER_OID"),
                "userName": env("EXPECTED_IDC_USERNAME"),
                "idpName": env("ENTRA_IDP_NAME"),
                "oidClaim": os.environ.get("OID_CLAIM", "entra_oid"),
                "userId": user_id,
            },
        },
    )
    admin = session(profile=args.profile)
    tti_arn = os.environ.get("TTI_ARN")
    if tti_arn:
        outcome, res = attempt(
            lambda: admin.client("sso-admin").describe_trusted_token_issuer(
                TrustedTokenIssuerArn=tti_arn
            )
        )
        if res is not None:
            jwt = res.get("TrustedTokenIssuerConfiguration", {}).get(
                "OidcJwtConfiguration", {}
            )
            outcome["data"] = {
                "issuerUrl": jwt.get("IssuerUrl"),
                "claimAttributePath": jwt.get("ClaimAttributePath"),
                "identityStoreAttributePath": jwt.get("IdentityStoreAttributePath"),
            }
        evidence.record("C5.tti", outcome)
    if not user_id:
        evidence.record(
            "C5.user",
            {
                "ok": False,
                "code": "Local:NoUserId",
                "message": "no exchange was kept and no --user-id was given",
                "data": {},
            },
        )
        return
    outcome, res = attempt(
        lambda: admin.client("identitystore").describe_user(
            IdentityStoreId=env("IDENTITY_STORE_ID"), UserId=user_id
        )
    )
    if res is not None:
        outcome["data"] = {
            "userId": res.get("UserId"),
            "userName": res.get("UserName"),
            "externalIds": res.get("ExternalIds", []),
        }
    evidence.record("C5.user", outcome)


def cmd_actor_policy(args: argparse.Namespace, evidence: Evidence) -> None:
    """Record which principals the application's actor policy names, so a refused exchange can be attributed.

    Without it, a member-account refusal beside a successful same-account control could be the
    account boundary or a policy that simply omits the member role; this tells the two apart.

    Args:
      args: ``--profile`` (allowed ``sso:GetApplicationAuthenticationMethod``) and ``--app-arn``.
      evidence: The log.

    Returns:
      None.

    Raises:
      None.
    """
    app = args.app_arn or env("IDC_APPLICATION_ARN")
    admin = session(profile=args.profile)
    outcome, res = attempt(
        lambda: admin.client("sso-admin").get_application_authentication_method(
            ApplicationArn=app, AuthenticationMethodType="IAM"
        )
    )
    if res is not None:
        policy = (
            res.get("AuthenticationMethod", {}).get("Iam", {}).get("ActorPolicy", {})
        )
        if isinstance(policy, str):
            policy = json.loads(policy)
        principals: list[str] = []
        for statement in policy.get("Statement", []):
            if statement.get("Effect") != "Allow":
                continue
            principal = statement.get("Principal")
            named = (
                principal.get("AWS", []) if isinstance(principal, dict) else [principal]
            )
            principals.extend([named] if isinstance(named, str) else named)
        outcome["data"] = {"appArn": app, "principals": principals}
    evidence.record("C1.actor", outcome)


def cmd_mark(args: argparse.Namespace, evidence: Evidence) -> None:
    """Record a manual step, such as the admin ending a session, at the moment it happened.

    Args:
      args: ``--label`` and ``--note``.
      evidence: The log.

    Returns:
      None.

    Raises:
      None.
    """
    data: dict[str, Any] = {"note": args.note}
    if args.sessions_ended is not None:
        data["sessionsEnded"] = args.sessions_ended
    evidence.record(args.label, {"ok": True, "data": data})


def load(path: Path) -> list[Record]:
    """Read every record in the evidence file, in the order written.

    Args:
      path: The evidence file.

    Returns:
      The records.

    Raises:
      None.
    """
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def latest(records: list[Record]) -> dict[str, Record]:
    """The last record for each label, since a re-run step supersedes its earlier attempt.

    Args:
      records: The log, in order.

    Returns:
      Label to record.

    Raises:
      None.
    """
    out: dict[str, Record] = {}
    for record in records:
        out[record["label"]] = record
    return out


def is_ok(record: Record | None) -> TypeGuard[Record]:
    """Whether a step was recorded and succeeded.

    Args:
      record: The record, or None.

    Returns:
      True on success.

    Raises:
      None.
    """
    return record is not None and bool(record.get("ok"))


def is_local(record: Record | None) -> TypeGuard[Record]:
    """Whether a step failed before reaching AWS.

    Args:
      record: The record, or None.

    Returns:
      True for a ``Local:`` failure.

    Raises:
      None.
    """
    return (
        record is not None
        and not record.get("ok")
        and str(record.get("code", "")).startswith("Local:")
    )


def is_refused(record: Record | None) -> TypeGuard[Record]:
    """Whether AWS answered a step with an error.

    Args:
      record: The record, or None.

    Returns:
      True for a service error.

    Raises:
      None.
    """
    return record is not None and not record.get("ok") and not is_local(record)


def why(record: Record | None) -> str:
    """A record's error as one phrase.

    Args:
      record: The record, or None.

    Returns:
      ``code: message``, or a note that it was never recorded.

    Raises:
      None.
    """
    if record is None:
        return "never recorded"
    return f"{record.get('code')}: {record.get('message')}"


def data(record: Record | None) -> dict[str, Any]:
    """A record's data, empty when absent.

    Args:
      record: The record, or None.

    Returns:
      Its ``data``.

    Raises:
      None.
    """
    return (record or {}).get("data") or {}


def grants_note(
    with_r: Record | None, without_r: Record | None
) -> tuple[bool | None, str]:
    """Compare Access Grants seen with the context and without it.

    Args:
      with_r: The identity-enhanced session's count.
      without_r: The plain session's count.

    Returns:
      True when the context showed more grants, False when it did not, None when not measured; and a phrase.

    Raises:
      None.
    """
    if not (is_ok(with_r) and is_ok(without_r)):
        return None, "Access Grants were not compared"
    n_with, n_without = data(with_r).get("count", 0), data(without_r).get("count", 0)
    return (
        n_with > n_without,
        f"Access Grants saw {n_with} grant(s) with the context and {n_without} without",
    )


def verdict_c1(obs: dict[str, Record]) -> tuple[str, str]:
    """Check 1: a member-account role exchanges on the organization's application, another role assumes.

    Args:
      obs: The latest record per label.

    Returns:
      The verdict and its reason.

    Raises:
      None.
    """
    exchange, caller = obs.get("C1.exchange"), obs.get("C1.exchange.caller")
    if exchange is None:
        return "INCONCLUSIVE", "C1.exchange was never recorded"
    if is_local(exchange) or not is_ok(caller):
        return (
            "INCONCLUSIVE",
            f"the exchange never reached AWS or its caller is unknown: {why(exchange if is_local(exchange) else caller)}",
        )
    app_account, caller_account = (
        data(exchange).get("appAccount"),
        data(caller).get("account"),
    )
    if app_account is None:
        return (
            "INCONCLUSIVE",
            "the application ARN did not parse, so the accounts cannot be compared",
        )
    if app_account == caller_account:
        return (
            "INCONCLUSIVE",
            "the exchanger is in the application's own account, so this repeats G10 and does not test the cross-account premise",
        )
    if is_refused(exchange):
        exchanger = principal_of(data(caller).get("arn"))
        if "identity-based policy" in str(exchange.get("message")):
            return (
                "INCONCLUSIVE",
                f"the exchanger's own IAM policy does not allow the call ({why(exchange)}); grant sso-oauth:CreateTokenWithIAM on the application and rerun",
            )
        control = obs.get("C1.control.exchange")
        if not (
            is_ok(control)
            and data(control).get("appAccount")
            == data(control).get("caller", {}).get("account")
        ):
            return (
                "INCONCLUSIVE",
                f"the member-account exchange was refused ({why(exchange)}), and no same-account control exchange succeeded, so the refusal cannot be laid on the account boundary",
            )
        actor = obs.get("C1.actor")
        if not is_ok(actor):
            return (
                "INCONCLUSIVE",
                f"the member-account exchange was refused ({why(exchange)}) while the application's own account exchanged, but the actor policy was not read, so a policy that omits the member role is not ruled out (run phase0.py actor-policy)",
            )
        named = data(actor).get("principals", [])
        if "*" not in named and exchanger not in {principal_of(p) for p in named}:
            return (
                "INCONCLUSIVE",
                f"the application's actor policy does not name the member-account exchanger {exchanger}, so the refusal ({why(exchange)}) is the fixture's, not the account boundary's",
            )
        return (
            "FAIL",
            f"the member-account exchange was refused ({why(exchange)}) although the actor policy names {exchanger}, while the same application accepted an exchange from its own account, so the account boundary is the cause",
        )
    if not data(exchange).get("context", {}).get("present"):
        return (
            "FAIL",
            "the cross-account exchange succeeded but returned no identity context, in neither awsAdditionalDetails nor the idToken claim",
        )
    assumer, with_r, without_r = (
        obs.get("C1.assumer"),
        obs.get("C1.assume.with"),
        obs.get("C1.assume.without"),
    )
    if not is_ok(assumer) or with_r is None:
        return "INCONCLUSIVE", "the assumption was never recorded"
    if principal_of(data(assumer).get("arn")) == principal_of(data(caller).get("arn")):
        return (
            "INCONCLUSIVE",
            "the assumer is the exchanger's own role, so the split between two principals was not tested",
        )
    if is_local(with_r):
        return "INCONCLUSIVE", f"the assumption never reached AWS: {why(with_r)}"
    if is_refused(with_r):
        if "SetContext" in str(with_r.get("message")):
            return (
                "INCONCLUSIVE",
                f"the carrier's trust policy does not grant sts:SetContext to the assumer: {why(with_r)}",
            )
        if not is_ok(without_r):
            return (
                "INCONCLUSIVE",
                f"the carrier refused the assumer even without a context ({why(without_r)}), so its trust policy, not the context, decides",
            )
        return (
            "FAIL",
            f"STS refused a context minted on the organization instance ({why(with_r)}), though the same assumer reached the carrier without one",
        )
    enhanced, note = grants_note(
        obs.get("C1.grants.with"), obs.get("C1.grants.without")
    )
    if enhanced is False:
        return (
            "INCONCLUSIVE",
            f"the assumption succeeded, but {note}, so the session's identity is not shown; give the test user one grant",
        )
    who = f"{data(caller).get('arn')} in account {caller_account} exchanged on the application in account {app_account}"
    expiry = data(with_r).get("expirationEqualsContextExp")
    return (
        "PASS",
        f"{who}, and {data(assumer).get('arn')} assumed the carrier with the context; {note}; carrier expiry equals context expiry: {expiry}",
    )


def probe_status(obs: dict[str, Record], name: str) -> str:
    """One check 2 probe's reading, with the control and the allow-list's own exemptions applied.

    A probe is read only once the allow-list has been read and does not exempt its action: an
    unread list cannot show that a probe discriminates at all.

    Args:
      obs: The latest record per label.
      name: A key of ``PROBES``.

    Returns:
      ``allowed``, ``denied``, or a reason the probe cannot be read.

    Raises:
      None.
    """
    with_r, without_r = obs.get(f"C2.{name}.with"), obs.get(f"C2.{name}.without")
    if with_r is None or without_r is None:
        return "not recorded"
    if not is_ok(without_r):
        return (
            f"control refused ({why(without_r)}), so the carrier's own policy decides"
        )
    policy = obs.get("C2.allowlist.policy")
    if not is_ok(policy):
        return f"not shown to discriminate: the allow-list was not read ({why(policy)})"
    if data(policy).get("exempt", {}).get(name):
        return f"not discriminating: the allow-list exempts {PROBES[name]}"
    if is_ok(with_r):
        return "allowed"
    if is_local(with_r):
        return f"never reached AWS ({why(with_r)})"
    if with_r.get("code") in DENIED:
        return "denied"
    return f"failed otherwise ({why(with_r)})"


def verdict_c2(obs: dict[str, Record]) -> tuple[str, str]:
    """Check 2: is the allow-list's Deny in effect on the organization instance?

    Args:
      obs: The latest record per label.

    Returns:
      ``MEASURED:<outcome>`` or ``INCONCLUSIVE``, and the reason.

    Raises:
      None.
    """
    if not is_ok(obs.get("C2.assume.with")):
        return (
            "INCONCLUSIVE",
            f"no identity-enhanced carrier session: {why(obs.get('C2.assume.with'))}",
        )
    statuses = {name: probe_status(obs, name) for name in PROBES}
    unreadable = {n: s for n, s in statuses.items() if s not in {"allowed", "denied"}}
    if unreadable:
        return "INCONCLUSIVE", "; ".join(f"{n}: {s}" for n, s in unreadable.items())
    enhanced, note = grants_note(
        obs.get("C2.grants.with"), obs.get("C2.grants.without")
    )
    if enhanced is False:
        return (
            "INCONCLUSIVE",
            f"the carrier was assumed with the context, but {note}, so the session's identity is not shown",
        )
    policy = data(obs.get("C2.allowlist.policy"))
    version = policy.get("versionId", "unread")
    s3 = {statuses[n] for n in ("getobject_other", "putobject", "listobjects")}
    sqs = statuses["sqs_send"]
    tail = f"(allow-list version {version}; {note})"
    if s3 == {"allowed"} and sqs == "allowed":
        return (
            "MEASURED:DENY_ABSENT",
            f"plain S3 and SQS all succeeded with the context, as without it: the Deny is not in effect on the organization instance either {tail}",
        )
    if s3 == {"denied"} and sqs == "denied":
        return (
            "MEASURED:DENY_IN_EFFECT",
            f"plain S3 and SQS were denied only with the context: the Deny is in effect here, unlike on the account instance {tail}",
        )
    if s3 == {"allowed"} and sqs == "denied":
        return (
            "MEASURED:S3_ONLY_GAP",
            f"SQS was denied with the context but plain S3 was not: the Deny is in effect and S3 escapes it {tail}",
        )
    if s3 == {"denied"} and sqs == "allowed":
        return (
            "MEASURED:S3_DENIED_SQS_ALLOWED",
            f"plain S3 was denied with the context but SQS was not {tail}",
        )
    return "MEASURED:MIXED_S3", "plain S3 split: " + ", ".join(
        f"{n} {statuses[n]}" for n in ("getobject_other", "putobject", "listobjects")
    ) + f"; sqs {sqs} {tail}"


def verdict_p(obs: dict[str, Record]) -> list[tuple[str, str, str]]:
    """Check 3: gates P1, P2 and P3 on permission-set credentials.

    Only an authorization refusal fails a gate; a missing table or object, which the fixture's
    ``ListBucket`` grants make read as ``NoSuchKey`` rather than 403, is inconclusive.

    Args:
      obs: The latest record per label.

    Returns:
      One ``(gate, verdict, reason)`` per gate.

    Raises:
      None.
    """
    creds = obs.get("P.creds")
    if not is_ok(creds):
        accounts = obs.get("P.accounts")
        reason = f"no permission-set credentials: {why(creds)}; P.accounts {data(accounts) if is_ok(accounts) else why(accounts)}"
        return [(g, "INCONCLUSIVE", reason) for g in ("P1", "P2", "P3")]
    out: list[tuple[str, str, str]] = []
    query = obs.get("P1.query")
    q = data(query)
    failure = str(q.get("stateChangeReason") or "").lower()
    if is_ok(query) and q.get("state") == "SUCCEEDED":
        out.append(
            (
                "P1",
                "PASS",
                "the permission-set session ran the probe query on the Identity Center workgroup under a Lake Formation grant made only to the Identity Center user (that the workgroup refuses a session without a context was measured on 2026-11-15, not repeated here)",
            )
        )
    elif is_refused(query) and "do not have access" in str(query.get("message")):
        out.append(
            (
                "P1",
                "FAIL",
                f"the Identity Center workgroup refused the permission-set session, so it carries no identity context: {why(query)}",
            )
        )
    elif (
        is_ok(query)
        and q.get("state") == "FAILED"
        and any(s in failure for s in ("no accessible columns", "lake formation"))
    ):
        out.append(
            (
                "P1",
                "FAIL",
                f"the workgroup accepted the session but Lake Formation refused the query: {q.get('stateChangeReason')}",
            )
        )
    elif is_ok(query) and q.get("state") == "FAILED":
        out.append(
            (
                "P1",
                "INCONCLUSIVE",
                f"the query failed for a reason that is not an authorization refusal ({q.get('stateChangeReason')}); check the table, the workgroup's result location and PROBE_QUERY",
            )
        )
    else:
        out.append(
            (
                "P1",
                "INCONCLUSIVE",
                f"the probe query did not settle: {q if is_ok(query) else why(query)}",
            )
        )
    own, other = obs.get("P2.own"), obs.get("P2.other")
    if is_ok(own) and is_refused(other) and other.get("code") in DENIED:
        out.append(
            (
                "P2",
                "PASS",
                "the key named by the user's own tag was readable and another user's was denied, so ${aws:PrincipalTag/username} resolved from Identity Center",
            )
        )
    elif (
        is_refused(own)
        and own.get("code") in DENIED
        and is_refused(other)
        and other.get("code") in DENIED
    ):
        out.append(
            (
                "P2",
                "FAIL",
                f"the user's own tagged key was denied too ({why(own)}), where a missing object would read NoSuchKey: the session carries no username tag",
            )
        )
    elif is_ok(own) and is_ok(other):
        out.append(
            (
                "P2",
                "INCONCLUSIVE",
                "both keys were readable, so the permission set's policy is broader than the tag and proves nothing",
            )
        )
    else:
        out.append(
            (
                "P2",
                "INCONCLUSIVE",
                f"own {'ok' if is_ok(own) else why(own)}; other {'ok' if is_ok(other) else why(other)}",
            )
        )
    p3 = {name: obs.get(f"P3.{name}") for name in ("get", "put", "list")}
    if all(is_ok(r) for r in p3.values()):
        out.append(
            (
                "P3",
                "PASS",
                "plain GetObject, PutObject and ListObjectsV2 all succeeded on the permission-set credentials",
            )
        )
    elif any(is_refused(r) and r.get("code") in DENIED for r in p3.values()):
        denied = ", ".join(
            f"{n} ({why(r)})"
            for n, r in p3.items()
            if is_refused(r) and r.get("code") in DENIED
        )
        out.append(
            (
                "P3",
                "FAIL",
                f"plain S3 was denied on the permission-set credentials: {denied}",
            )
        )
    else:
        out.append(
            (
                "P3",
                "INCONCLUSIVE",
                "; ".join(f"{n} {'ok' if is_ok(r) else why(r)}" for n, r in p3.items()),
            )
        )
    return out


def when(record: Record) -> datetime:
    """A record's timestamp, whichever half wrote it.

    Node writes ``...Z`` with milliseconds and Python ``...+00:00`` with microseconds, so the strings
    do not sort against each other; compare these instead. Parsing ``Z`` needs Python 3.11.

    Args:
      record: The record.

    Returns:
      Its time, timezone-aware.

    Raises:
      None.
    """
    return datetime.fromisoformat(str(record["ts"]))


def minutes_after(record: Record, start: Record) -> float:
    """Minutes between two records.

    Args:
      record: The later record.
      start: The earlier one.

    Returns:
      The gap in minutes.

    Raises:
      None.
    """
    return (when(record) - when(start)).total_seconds() / 60


def verdict_c4(records: list[Record], obs: dict[str, Record]) -> tuple[str, str]:
    """Check 4: after an admin ends the user's Identity Center session, what still works?

    Args:
      records: Every record, in order, since check 4 repeats one step over time.
      obs: The latest record per label.

    Returns:
      ``MEASURED:<outcome>`` or ``INCONCLUSIVE``, and the reason.

    Raises:
      None.
    """
    before, deleted = obs.get("C4.refresh.before"), obs.get("C4.deleted")
    if not is_ok(before):
        return (
            "INCONCLUSIVE",
            f"the refresh before the deletion did not succeed, so there is no baseline: {why(before)}",
        )
    if deleted is None:
        return (
            "INCONCLUSIVE",
            "the deletion was never marked (phase0.py mark --label C4.deleted)",
        )
    ended = data(deleted).get("sessionsEnded")
    if ended is None:
        return (
            "INCONCLUSIVE",
            "the deletion was marked without --sessions-ended, so whether any session was ended is not recorded",
        )
    if ended < 1:
        return (
            "INCONCLUSIVE",
            "the admin ended no session: the exchange's session did not appear under Active sessions, so nothing was revoked to observe",
        )
    after = [
        r
        for r in records
        if r["label"].startswith("C4.refresh.after")
        and not r["label"].endswith(".caller")
        and when(r) > when(deleted)
        and not is_local(r)
    ]
    if not after:
        return "INCONCLUSIVE", "no refresh was recorded after the deletion"
    first_refusal = next((r for r in after if is_refused(r)), None)
    last = after[-1]
    if first_refusal is not None:
        refresh_phrase = f"the Identity Center refresh was refused {minutes_after(first_refusal, deleted):.0f} min after the deletion ({why(first_refusal)})"
    elif minutes_after(last, deleted) < 30:
        return (
            "INCONCLUSIVE",
            f"refresh still succeeded at {minutes_after(last, deleted):.0f} min, short of the 30 minutes AWS allows an application session to end; refresh again after 30",
        )
    else:
        refresh_phrase = f"the Identity Center refresh still succeeded {minutes_after(last, deleted):.0f} min after the deletion"
    minted, reexchange = (
        obs.get("C4.cognito.refresh.after"),
        obs.get("C4.reexchange.after"),
    )
    old = obs.get("C4.old.assume.with")
    old_phrase = (
        ""
        if old is None
        else f"; the context minted before the deletion {'still assumed' if is_ok(old) else 'was refused: ' + why(old)}"
    )
    if (
        not (is_ok(minted) and when(minted) > when(deleted))
        or reexchange is None
        or is_local(reexchange)
        or when(reexchange) < when(minted)
    ):
        return (
            "INCONCLUSIVE",
            f"{refresh_phrase}, but no re-exchange of a Cognito token minted after the deletion was recorded{old_phrase}",
        )
    if first_refusal is not None and is_ok(reexchange):
        return (
            "MEASURED:REEXCHANGE_BYPASSES",
            f"{refresh_phrase}, yet a Cognito token minted after the deletion exchanged into a new session: an automatic re-exchange would undo the admins' revocation{old_phrase}",
        )
    if first_refusal is not None:
        return (
            "MEASURED:DELETION_HOLDS",
            f"{refresh_phrase}, and the re-exchange was refused too ({why(reexchange)}): a refused refresh means signing in again{old_phrase}",
        )
    if is_ok(reexchange):
        return (
            "MEASURED:DELETION_NOT_SEEN",
            f"{refresh_phrase}, and the re-exchange succeeded: ending the session stopped nothing observed{old_phrase}",
        )
    return (
        "MEASURED:REFRESH_OUTLIVES_DELETION",
        f"{refresh_phrase}, though the re-exchange was refused ({why(reexchange)}){old_phrase}",
    )


def verdict_c5(obs: dict[str, Record]) -> tuple[str, str]:
    """Check 5: Entra to Cognito to Identity Center, resolved on ``externalId`` to the right user.

    A PASS needs the mapping itself read: resolving to the right user on some other attribute
    would look the same from the user record alone.

    Args:
      obs: The latest record per label.

    Returns:
      The verdict and its reason.

    Raises:
      None.
    """
    expected, login = data(obs.get("C5.expected")), obs.get("C5.login")
    if not expected:
        return (
            "INCONCLUSIVE",
            "C5.expected was never recorded (run phase0.py entra-hop)",
        )
    if not is_ok(login):
        return "INCONCLUSIVE", f"the Entra sign-in did not complete: {why(login)}"
    token = data(login).get("idToken", {})
    federated = token.get("federated")
    claim, value, oid = (
        token.get("oidClaim"),
        token.get("oidClaimValue"),
        expected.get("oid"),
    )
    if not federated:
        return (
            "FAIL",
            "the Cognito ID token carries no federated identity, so the sign-in did not go through Entra",
        )
    if federated.get("providerName") != expected.get("idpName"):
        return (
            "INCONCLUSIVE",
            f"the sign-in came through provider {federated.get('providerName')!r}, not {expected.get('idpName')!r}; check ENTRA_IDP_NAME",
        )
    if value is None:
        return (
            "FAIL",
            f"the Cognito ID token carries no {claim!r} claim, so the trigger that emits the object id did not run",
        )
    if value != oid:
        if GUID_SHAPE.match(str(value)):
            return (
                "INCONCLUSIVE",
                f"the {claim!r} claim is an object id but not ENTRA_TEST_USER_OID; check the config, or whether the sign-in was as another user",
            )
        return (
            "FAIL",
            f"the {claim!r} claim is not an object id (federated subject {federated.get('userId')!r}), so the federation's subject is not keyed on the object id",
        )
    tti = obs.get("C5.tti")
    mapping = data(tti)
    if is_ok(tti) and (
        mapping.get("identityStoreAttributePath") != "externalIds.value"
        or mapping.get("claimAttributePath") != claim
    ):
        return (
            "INCONCLUSIVE",
            f"the trusted token issuer maps {mapping.get('claimAttributePath')!r} to {mapping.get('identityStoreAttributePath')!r}, not the externalId mapping under test",
        )
    exchange = obs.get("C5.exchange")
    if is_refused(exchange):
        if exchange.get("code") in DENIED:
            return (
                "INCONCLUSIVE",
                f"the exchanger itself was refused ({why(exchange)}); C1 settles the cross-account exchange, and C5 needs one that succeeds",
            )
        if exchange.get("code") == "InvalidGrantException" and is_ok(tti):
            return (
                "FAIL",
                f"Identity Center refused the Entra-federated assertion ({why(exchange)}) with the mapping on externalIds.value: no user has this object id as an externalId, or the path is not accepted",
            )
        return (
            "INCONCLUSIVE",
            f"the exchange was refused ({why(exchange)}), and with the mapping {'unread' if not is_ok(tti) else 'as configured'} the cause is not shown",
        )
    if not is_ok(exchange):
        return "INCONCLUSIVE", f"the exchange did not run: {why(exchange)}"
    user = obs.get("C5.user")
    if is_refused(user):
        if user.get("code") == "ResourceNotFoundException":
            return (
                "INCONCLUSIVE",
                f"the idToken's sub did not resolve as an Identity Store user id ({why(user)}); read identitystore:UserId from the carrier's AssumeRole CloudTrail event and rerun entra-hop with --user-id",
            )
        return (
            "INCONCLUSIVE",
            f"the Identity Store read was refused ({why(user)}); IDSTORE_PROFILE needs identitystore:DescribeUser",
        )
    if not is_ok(user):
        return "INCONCLUSIVE", f"the Identity Store user was not read: {why(user)}"
    ids = [e.get("Id") for e in data(user).get("externalIds", [])]
    if oid not in ids:
        return (
            "FAIL",
            f"the exchange resolved to Identity Store user {data(user).get('userName')!r}, whose externalIds do not include the Entra object id ({len(ids)} externalId(s))",
        )
    if data(user).get("userName") != expected.get("userName"):
        return (
            "FAIL",
            f"the exchange resolved to {data(user).get('userName')!r}, not {expected.get('userName')!r}",
        )
    if not is_ok(tti):
        return (
            "INCONCLUSIVE",
            f"the exchange resolved to {expected.get('userName')!r}, whose externalIds include the object id, but the mapping was not read ({why(tti) if tti else 'TTI_ARN unset'}), so that it resolved on externalId is not shown",
        )
    return (
        "PASS",
        f"the Entra sign-in carried the object id in {claim!r}, the issuer maps it to externalIds.value, and the exchange resolved it to {expected.get('userName')!r}, whose externalIds include it",
    )


def cmd_verdict(args: argparse.Namespace, evidence: Evidence) -> None:
    """Compute the verdicts from the evidence file and append them to it.

    Args:
      args: ``check``, one of C1, C2, P, C4, C5 or all.
      evidence: The log.

    Returns:
      None.

    Raises:
      None.
    """
    records = load(evidence.path)
    obs = latest(records)
    results: list[tuple[str, str, str]] = []
    if args.check in {"C1", "all"}:
        results.append(("C1", *verdict_c1(obs)))
    if args.check in {"C2", "all"}:
        results.append(("C2", *verdict_c2(obs)))
    if args.check in {"P", "all"}:
        results.extend(verdict_p(obs))
    if args.check in {"C4", "all"}:
        results.append(("C4", *verdict_c4(records, obs)))
    if args.check in {"C5", "all"}:
        results.append(("C5", *verdict_c5(obs)))
    for check, verdict, reason in results:
        evidence.record(
            f"verdict.{check}",
            {"ok": True, "data": {"verdict": verdict, "reason": reason}},
        )
        print(f"  {check}: {verdict} - {reason}")


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run one subcommand.

    Args:
      argv: The arguments, or None for ``sys.argv``.

    Returns:
      None.

    Raises:
      SystemExit: On a usage error.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "assume", help="assume the carrier with a kept context, and without it"
    )
    p.add_argument("--context", required=True)
    p.add_argument("--prefix", default="C1")
    p.add_argument(
        "--no-control",
        action="store_true",
        help="skip the assumption without a context",
    )
    p.set_defaults(run=cmd_assume)
    p = sub.add_parser("allowlist", help="check 2's probes")
    p.add_argument("--context", required=True)
    p.set_defaults(run=cmd_allowlist)
    p = sub.add_parser("pgates", help="check 3, P1 to P3")
    p.add_argument("--token", required=True)
    p.set_defaults(run=cmd_pgates)
    p = sub.add_parser("entra-hop", help="check 5's Identity Center side")
    p.add_argument("--token")
    p.add_argument("--user-id")
    p.add_argument("--profile", default=os.environ.get("IDSTORE_PROFILE"))
    p.set_defaults(run=cmd_entra_hop)
    p = sub.add_parser(
        "actor-policy",
        help="check 1: which principals the application's actor policy names",
    )
    p.add_argument("--profile", default=os.environ.get("IDSTORE_PROFILE"))
    p.add_argument("--app-arn")
    p.set_defaults(run=cmd_actor_policy)
    p = sub.add_parser("mark", help="record a manual step as it happens")
    p.add_argument("--label", required=True)
    p.add_argument("--note", required=True)
    p.add_argument(
        "--sessions-ended",
        type=int,
        help="for C4.deleted: how many sessions the admin ended",
    )
    p.set_defaults(run=cmd_mark)
    p = sub.add_parser("verdict", help="state each check's outcome from the evidence")
    p.add_argument("check", choices=["C1", "C2", "P", "C4", "C5", "all"])
    p.set_defaults(run=cmd_verdict)
    args = parser.parse_args(argv)
    args.run(args, Evidence(Path(env("PHASE0_EVIDENCE"))))


if __name__ == "__main__":
    main(sys.argv[1:])
