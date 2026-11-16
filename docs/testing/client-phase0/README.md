# Client-environment Phase 0 checks: the runbook

Five identity checks that only the client's environment can answer, written as a hand-off. **Nobody
has run them**: they were written before anyone had client access, and only their offline suites
have run. The plan they serve is [`docs/transition_plan.md`](../../transition_plan.md) (Phase 0 and
§5.5). Its *What Phase 0 measured* block holds the 2026-11-15 run on an account instance, which these
checks extend to the organization instance.

| # | Check | Who must act besides the runner |
|---|---|---|
| C1 | Gate G11, the cross-account exchange: a member-account role exchanges on the organization's application, a different role assumes | Identity Center admins (application, actor policy) |
| C2 | The allow-list re-run, with an SQS probe off the list | none |
| P1 to P3 | §5.4's permission-set gates | Identity Center admins (permission set, `sso:account:access`, an ABAC attribute) |
| C4 | Ending the user's Identity Center session: does a refresh or a re-exchange survive? | An Identity Center admin, for one console action |
| C5 | Entra to Cognito to Identity Center, resolved on `externalId` to the right user | Entra owner (federation subject), Identity Center admins (trusted token issuer mapping) |

**How a result is stated.** Every step appends what it saw to one evidence file as it sees it, and
`phase0.py verdict` reads that file and states each check's outcome as a **reason**. A refusal that
never reached AWS (`Local:` codes), or a control that failed, gives **INCONCLUSIVE**, never FAIL.
C2 and C4 are measurements, so they report `MEASURED:<outcome>`; the tables below say what each
outcome changes. Do not read pass or fail from an exit code.

## 1. Set up the runner

You need Node 20 or later and Python 3.11 or later. If a launcher cannot run a version-manager shim,
give it the absolute path to `node` (`command -v node`). Work in a copy of this folder outside any
git checkout: the installs below then stay out of the repository, and the scripts refuse to keep
evidence or tokens inside a checkout anyway. Run the copy from the repository's root, or copy the
`client-phase0` folder you were given to the same place.

```bash
export WORK="$HOME/phase0-client" && mkdir -p "$WORK" && cp -R docs/testing/client-phase0 "$WORK/" && cd "$WORK/client-phase0"
```

```bash
npm install --no-save @aws-sdk/client-sso-oidc@3.1169.0 @aws-sdk/client-sts@3.1169.0
```

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install boto3==1.44.3 botocore==1.44.3
```

**Why those pins.** botocore 1.35 drops `awsAdditionalDetails` from `CreateTokenWithIAM` without an
error, and the field arrived in botocore 1.37.22 and `@aws-sdk/client-sso-oidc` 3.777.0. Only the
Node exchanger calls `CreateTokenWithIAM`, and it also reads the Identity Center ID token's
`sts:identity_context` claim, which carries the same value. So the context survives an SDK that
drops the field, and the evidence records which source supplied it.

Then fill in `config.example.env` as `$WORK/config.env`. `AWS_REGION` must be the organization
instance's home Region, and every member-account fixture must be in that same Region. **Every new
shell**, including the one you return to during C4, starts with this line, because every command
below runs from the copy, under its venv, with the config loaded:

```bash
cd ~/phase0-client/client-phase0 && . .venv/bin/activate && set -a && . ../config.env && set +a
```

Prove the scripts work before touching AWS; both commands must exit 0:

```bash
python3 -m unittest phase0_test phase0_stub_test && node --test exchange_test.mjs
```

**Nothing real goes in the repository.** That covers account ids, user names, object ids and tokens.
The evidence file and the secrets directory stay in `$WORK`. Results go into the plan only as
sanitized prose, as the 2026-11-15 block does.

## 2. Fixtures

The test users are **alice**, who signs in, and **bob**, who never needs to. Both exist in Entra and
are provisioned by SCIM into the organization's Identity Center. The fixture files in `fixtures/`
use `<PLACEHOLDER>` names.

| Owner | Fixture | Settings that matter |
|---|---|---|
| Entra owner | The enterprise application the Cognito pool federates to, **over SAML only** | A persistent NameID whose source attribute is `user.objectid`, and the email-address claim released. Not OIDC: Cognito would record Entra's `sub`, which Microsoft documents as pairwise (unique to each application), not the object id, so `externalId` could never match. C5 fails, with that reason, if the subject is anything else |
| Us, member account | Cognito test pool | Federated to Entra. The app client allows the code grant, PKCE and `http://localhost:8766/callback`, and has token revocation on. A pre-token-generation (V1) trigger runs [`fixtures/pretoken_entra_oid.py`](fixtures/pretoken_entra_oid.py), which emits `entra_oid` |
| Identity Center admins | Trusted token issuer | The issuer is the test pool. Claim `entra_oid` maps to `externalIds.value`. AWS documents external ID as mappable but not this path string, so a refusal here is itself a finding |
| Identity Center admins | Application **catalog** (`IDC_APPLICATION_ARN`) | Customer-managed, in the management or delegated-admin account. It has the JWT-bearer grant with the issuer, the refresh-token grant, and assignment not required. Its scopes are `lakeformation:query`, `athena:workgroup:read_write` and `s3:access_grants:read_write`. Its actor policy is [`fixtures/application-actor-policy.json`](fixtures/application-actor-policy.json) |
| Identity Center admins | Application **portal** (`IDC_PORTAL_APP_ARN`) | A second application with the same issuer and actor policy, and the `sso:account:access` scope only (§5.1's separate application) |
| Identity Center admins | Permission set `Phase0Probe` | Its inline policy is [`fixtures/permission-set-policy.json`](fixtures/permission-set-policy.json). It is assigned to alice on the member account. An attribute for access control `username` maps to `${path:userName}` |
| Us, member account | Roles `phase0-exchanger`, `phase0-assumer` and `phase0-carrier` | Their policies are in `fixtures/` (the exchanger, the assumer, and the carrier's trust and permissions). **The exchanger and the assumer are different roles**: C1 is inconclusive otherwise |
| Us, member account | Scratch bucket and queue | The bucket holds `phase0-probe/other-user/secret.txt`, `phase0-probe/p3/seed.txt`, `phase0-probe/abac/<alice>/probe.txt` and `phase0-probe/abac/<bob>/probe.txt`, and has **no bucket policy**, so only role policies decide. The queue is a standard SQS queue `phase0-scratch` |
| Us, member account | Access Grants instance associated with the organization instance | One location for the bucket, and **one** READWRITE grant to alice on `phase0-probe/alice/*` |
| Us, member account | Lake Formation's Identity Center configuration | Created in the member account against the organization instance, so Lake Formation can grant to an Identity Center user |
| Us, member account | IdC Athena workgroup `phase0-idc`, table `phase0_db.phase0_t` | Created with Identity Center authentication, S3 Access Grants on and a service role. Its query results location is `s3://<PROBE_BUCKET>/phase0-probe/alice/athena-results/`, inside alice's one grant, or every query fails on the results location. Lake Formation `SELECT` on the table is granted to **alice's Identity Center user only**, not to any role |

## 3. Run order

One Cognito ID token can be exchanged once (replay is refused), so each exchange below follows its
own sign-in or Cognito refresh. Run the checks in this order: C5, C1, C2, P1 to P3, then C4 last,
because it ends alice's session. Every command assumes the config is loaded.

### C5: the Entra hop

```bash
node signin.mjs login --user alice --label C5.login
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs jwt --from alice --out alice-c5 --label C5.exchange
python3 phase0.py entra-hop --token alice-c5 --profile "$IDSTORE_PROFILE"
```

If the runner has no Identity Store read access, an admin runs the last line instead with
`--user-id <the sub from C5.exchange>`; the same holds for C1's `actor-policy`. **An admin's run
writes to their own evidence file**, so they need this folder set up as in §1 (the venv, and a
config with at least `PHASE0_EVIDENCE`, `PHASE0_SECRETS`, `AWS_REGION`, `IDENTITY_STORE_ID`,
`TTI_ARN`, `IDC_APPLICATION_ARN`, `ENTRA_TEST_USER_OID`, `EXPECTED_IDC_USERNAME`, `ENTRA_IDP_NAME`
and `OID_CLAIM`). They send the operator their evidence lines, which the operator appends before
running `verdict`: `cat admin-evidence.jsonl >> "$PHASE0_EVIDENCE"`. A later line for a label
supersedes an earlier one.

| Label | Expect |
|---|---|
| `C5.login` | `idToken.federated.providerName` = `$ENTRA_IDP_NAME`, and `oidClaimValue` = `$ENTRA_TEST_USER_OID` |
| `C5.tti` | `claimAttributePath` `entra_oid`, `identityStoreAttributePath` `externalIds.value`. `TTI_ARN` must be set: without the mapping read, C5 cannot pass |
| `C5.exchange` | ok. `idTokenClaims.sub` has an Identity Store user id's shape: a UUID, usually prefixed with ten hex digits and a hyphen |
| `C5.user` | `userName` = alice's, and `externalIds` includes the object id |

**PASS** means the object id travelled from Entra to Identity Center and resolved to alice through
the `externalIds.value` mapping: the issuer was read mapping `entra_oid` there, and the `sub`
described as alice, with the object id among her `externalIds`. AWS does not document that `sub` is
the Identity Store user id, and this check is what shows it. **FAIL** names the broken link: the
token carries no federated identity, the trigger did not run, the claim is not an object id at all
(so the federation's subject is not keyed on it), Identity Center refused the assertion
(`InvalidGrantException`) with the mapping read, or the exchange resolved to another user.
**INCONCLUSIVE** covers what looks like setup rather than a finding: another provider name (check
`ENTRA_IDP_NAME`), a different object id (check `ENTRA_TEST_USER_OID`), a mapping other than the one
under test or not read, an exchanger refused outright (C1 settles that), or an Identity Store read
that was refused. If `sub` is not a user id, read `identitystore:UserId` from the carrier's
`AssumeRole` event in CloudTrail and rerun with `--user-id`.

### C1: the cross-account exchange (gate G11)

```bash
node signin.mjs refresh --user alice --label C1.cognito
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs jwt --from alice --out alice-c1 --label C1.exchange
python3 phase0.py assume --context alice-c1
```

Only if `C1.exchange` was refused, run the control from the application's own account, and have an
Identity Center admin (or `IDSTORE_PROFILE`, if it may call `sso:GetApplicationAuthenticationMethod`)
record which principals the application's actor policy names:

```bash
node signin.mjs refresh --user alice --label C1.control.cognito
AWS_PROFILE=$CONTROL_PROFILE node exchange.mjs jwt --from alice --out alice-ctl --label C1.control.exchange
python3 phase0.py actor-policy --profile "$IDSTORE_PROFILE"
```

| Label | Expect. Values marked *measured* are from the 2026-11-15 account-instance run; the rest follow from this fixture |
|---|---|
| `C1.exchange.caller` | the member account and the `phase0-exchanger` role |
| `C1.exchange` | ok, with `appAccount` different from the caller's account. `expiresIn` 3600 (*measured*). `scope` includes `athena:workgroup:read_write` and `s3:access_grants:read_write`. `context.present` true, about 1,600 characters long (*measured*: 1,588 and 1,668). `fieldMatchesClaim` true (*measured*: the field and the claim were byte-identical) |
| `C1.assume.with` | ok, and `expirationEqualsContextExp` true (*measured*) |
| `C1.grants.with` / `.without` | 1 and 0, from the fixture's one grant (the 2026-11-15 run had two grants and saw 2 and 0) |

**PASS** means a member-account role exchanged on an application in another account, and a different
role assumed the carrier with the context. The verdict names both principals and both accounts.
**FAIL** comes in two forms. The member-account exchange can be refused although the exchanger's own
IAM policy allows it, the actor policy names it, and the control exchange from the application's own
account succeeds: then the account boundary is the cause, and §4.7 must move the exchange. Or STS
can refuse the context although the same assumer reaches the carrier without one. **INCONCLUSIVE**
covers the cases where a refusal could be the fixture's: the exchanger's own policy refuses
(*"no identity-based policy allows"*), the actor policy omits the exchanger or was not read, or no
control ran. It also covers an exchanger in the application's own account (that repeats G10), one
principal playing both roles, and a trust policy without `sts:SetContext`. A refusal's message is
the service's `error_description`, so read the reason, not the code alone.

### C2: the allow-list re-run

```bash
python3 phase0.py allowlist --context alice-c1
```

The command reads the live `AWSIAMIdentityCenterAllowListForIdentityContext` first. If the list
exempts a probe's action, that probe cannot tell the Deny from its absence, so the verdict calls it
not discriminating rather than reading it. The probes run twice, on the carrier with the context and
on the carrier without it. The second run is the control: a probe it refuses is decided by the
carrier's own policy.

| Label | Expect if the organization instance behaves as the account instance did. Only the three S3 results were *measured* on 2026-11-15; SQS was not probed then |
|---|---|
| `C2.allowlist.policy` | ok, with `exempt` false for all four probes (the 2026-11-15 read showed only the three Access Grants operations among S3 actions; SQS was not checked). If the read is refused, every probe is INCONCLUSIVE: an unread list cannot show that a probe discriminates |
| `C2.getobject_other`, `C2.putobject` and `C2.listobjects`, `.with` and `.without` | all ok (*measured* with the context on 2026-11-15) |
| `C2.sqs_send.with` and `.without` | ok |
| `C2.grants.with` / `.without` | 1 and 0, from the fixture's one grant |

| Outcome | What it means for the plan |
|---|---|
| `DENY_ABSENT` | The account-instance finding carries over. §3.6's amendment stands: the carrier's own policy and the bucket policies are the controls |
| `DENY_IN_EFFECT` | The organization instance enforces the Deny. §3.6's original reading holds here, and the carrier cannot make plain S3 calls. Check §3.9 and P3 against it |
| `S3_ONLY_GAP` | The Deny is in effect, but S3 escapes it. Record which actions escape |
| `S3_DENIED_SQS_ALLOWED` or `MIXED_S3` | Unexpected. Record every probe's code and message from the evidence |

### P1 to P3: the permission-set gates

```bash
node signin.mjs refresh --user alice --label P.cognito
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs jwt --from alice --out alice-p --label P.exchange --app-arn "$IDC_PORTAL_APP_ARN"
python3 phase0.py pgates --token alice-p
```

| Label | Expect |
|---|---|
| `P.exchange` | ok, and `scope` includes `sso:account:access` |
| `P.accounts` / `P.roles` | `targetListed` true / `roleListed` true |
| `P.caller` | an `AWSReservedSSO_Phase0Probe_…` role. Record whether the session name is the user, which is §5.2's audit-legibility claim |

| Gate | PASS | FAIL |
|---|---|---|
| P1 | The probe query succeeded on the IdC workgroup under a grant made only to the Identity Center user. That the workgroup refuses a session without a context was measured on 2026-11-15 and is not repeated | The workgroup refused the session (no identity context), or Lake Formation refused the query. A query that failed for another reason, such as a missing table, is INCONCLUSIVE |
| P2 | alice's own tagged key was readable and bob's was denied, so `${aws:PrincipalTag/username}` resolved | Both keys were denied with 403. The permission set may list `abac/`, so a missing object reads `NoSuchKey` and is INCONCLUSIVE, not a failure |
| P3 | Plain `GetObject`, `PutObject` and `ListObjectsV2` all succeeded | One was denied; the reason carries the code and message |

The gates read on through §5's outcomes. If P3 passes, a permission-set-fed base plane survives. If
P3 fails, §3.9 stands. If P1 passes too, the credential stories collapse into one.

### C4: ending the Identity Center session

Run `C4.refresh.before` immediately before the admin acts, so the context it mints is still inside
its hour when the end of the run assumes with it.

```bash
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs refresh --from alice-c1 --out alice-c4r0 --label C4.refresh.before
```

The admin then opens IAM Identity Center, goes to Users, then alice, then **Active sessions**,
selects them all, chooses **End sessions** and types `confirm`. Ask them **how many sessions were
listed and ended**. AWS documents that tab as sign-in sessions, and nobody has checked that a session
opened by a JWT-bearer exchange appears there. Mark the moment and the count as soon as they say it
is done; a count of 0 makes C4 inconclusive, because nothing was revoked to observe:

```bash
python3 phase0.py mark --label C4.deleted --sessions-ended <N> --note "ended by the admin"
```

Refresh at about 1, 10 and 35 minutes after the mark. AWS says application sessions end *"at their
next refresh attempt, typically within 30 minutes"*. It says that of AWS managed applications, so
applying it to a customer-managed application is this runbook's assumption, and observing past 30
minutes is what tests it: the verdict needs a refusal or a refresh later than 30 minutes. Each refresh starts from the previous one's output, so the chain holds even
if the organization instance rotates refresh tokens (the account instance did not); a
`refreshTokenRotated` of true in the evidence says it does. Once one refresh is refused, skip the
rest, since there is no newer token to refresh from.

```bash
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs refresh --from alice-c4r0 --out alice-c4r1 --label C4.refresh.after.1
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs refresh --from alice-c4r1 --out alice-c4r2 --label C4.refresh.after.10
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs refresh --from alice-c4r2 --out alice-c4r3 --label C4.refresh.after.35
```

After the last refresh, try the old context, then a fresh Cognito token:

```bash
python3 phase0.py assume --context alice-c4r0 --prefix C4.old --no-control
node signin.mjs refresh --user alice --label C4.cognito.refresh.after
AWS_PROFILE=$EXCHANGER_PROFILE node exchange.mjs jwt --from alice --out alice-c4x --label C4.reexchange.after
```

| Outcome | What it means for the Phase 5 server spec (§4.7's open question) |
|---|---|
| `REEXCHANGE_BYPASSES` | Ending the session stops the refresh, but a re-exchange opens a new session. An automatic re-exchange on a refused refresh would undo the admins' revocation, so mark the context absent until the next sign-in |
| `DELETION_HOLDS` | Both are refused, so a refused refresh can only mean signing in again |
| `DELETION_NOT_SEEN` | The refresh outlived the deletion by more than 30 minutes. The revocation the hazard assumes does not happen |
| `REFRESH_OUTLIVES_DELETION` | The refresh survived but a fresh exchange did not. Record both reasons |

`C4.old.assume.with` shows whether a context minted before the deletion still assumes. That is a
separate fact for de-provisioning, which the 2026-11-15 run could not test.

## 4. Verdicts, then teardown

```bash
python3 phase0.py verdict all
```

Each verdict is printed and appended to the evidence file as `verdict.<check>`. Bring the evidence
file, not a summary of it, to whoever records the results in the plan. Then delete everything this
run created, in the client's environment:

- the three roles, the bucket, the queue and the workgroup;
- the Access Grants grant and location, and the Lake Formation grant;
- the test pool and its trigger;
- the two applications, the trusted token issuer and the permission set (the admins delete these).

Finally, delete `$WORK/secrets`.
