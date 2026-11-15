---
type: Decision
title: "The Identity Pool is retired, and no one's sign-in changed (SPEC-202)"
description: "The Cognito Identity Pool is deleted while the User Pool, Managed Login v2 and sign-in are untouched; the browser holds no AWS credentials, and since SPEC-262 no token either."
---

**The conflation this entry exists to prevent.** The Cognito **User Pool** authenticates people:
Managed Login v2, the Hosted UI round trip, Amplify in the tab (the portal server's own routes since
SPEC-262), the ID token. The Cognito **Identity
Pool** did something else entirely — it exchanged that ID token for temporary AWS credentials so the
browser could call AWS. SPEC-202 deleted the second and touched the first not at all. A reader who
reads "Cognito is retired" into this will go looking for a sign-in change that does not exist.

**What actually came out.** The pool itself, its principal-tag map, its role attachment, the portal
role's `AssumeRoleWithWebIdentity` trust statement (two statements to one — what remains admits the
API's execution role), `cognitoIdentityPoolId` from the runtime document, and the browser's last two
credential modules. `lib/awsCredentials.ts` became `lib/idToken.ts` with one export, `getIdToken`:
named for a JWT rather than for credentials **deliberately**, because there are no AWS credentials
in the browser to name and a module called `awsCredentials` invites putting some back.
`credentialRetry.ts` went with it — the expired-credential retry that used to wrap every AWS call is
a server-side re-assume now.

**The load-bearing negative could not be observed until the pool was gone, which is why the order
was not a preference.** `lib/amplify.ts` configures `identityPoolId` whenever the key is present, and
every `fetchAuthSession()` then vends pool credentials — including the one `getIdToken` makes on
every API call. So *"the browser makes no AWS call other than presigned S3 bytes"* reads as false
while the pool exists no matter how much code has been deleted, and running that check before the
retirement and calling it a pass is the failure the spec was ordered around. Measured after, in
Chromium: four hosts blocked by the CSP (`cognito-identity.`, `athena.`, `glue.`, `sqs.`), two
allowed and required (`cognito-idp.`, the Hosted UI host).

**A retirement is proved by an absence, and an absence needs a positive form.** Two ids were captured
**before** the merges, because the Terraform outputs that name them do not survive:
`describe-identity-pool` on the recorded pool id returns `ResourceNotFoundException`, `get-role`
returns exactly one trust statement. "Gone from the plan" is not the same claim.

**What did not change is the part worth asserting.** FR-010 re-ran SPEC-196's IAM simulation against
the deployed roles after the retirement, row for row: `alice/` allowed, `bob/` implicit-deny, every
denial paired with an allowed control on the same bucket so an ungranted action is distinguishable
from a mistyped ARN. **No row moved.** The retired browser grants stayed retired. The SPA task role
was asserted by **absence** — no attached and no inline policies — rather than by simulation,
because a role with no policies returns `implicitDeny` for everything with no control available, and
an unpaired `implicitDeny` presented as a pass is exactly what the rest of that check exists to
avoid.

## History

### 2026-11-15

- **Changed:** the fence no longer says the browser holds an ID token; since SPEC-262 the portal
  server holds it.

### 2026-09-02

- **Settled:** SPEC-202.
