<!--
Internal note, not for the client: this list is derived from docs/transition_plan.md, which stays
authoritative. When the plan changes what we ask of the Identity Center administrators, change this
file in the same pull request. Every value in angle brackets is a placeholder to fill in per
environment before sending.
-->

# Data Quarry: requests for the IAM Identity Center administrators

Data Quarry is a web portal where people upload, browse and query data in AWS. It is moving into
`<PORTAL_ACCOUNT_NAME>`, a member account of your AWS Organization. People will sign in with their
Entra ID accounts, and their own identity, not a shared role, will decide what data they can reach.
AWS calls that mechanism **trusted identity propagation**: the portal exchanges each user's sign-in
token for an Identity Center token. Lake Formation, Athena and S3 Access Grants then enforce that
user's own permissions.

That exchange runs through your organization's Identity Center instance. **We will not create or
change any Identity Center infrastructure ourselves**: no instance (account or organization), no
application, no trusted token issuer and no permission set. Everything on this list is a change
inside your instance. It is made by your team, through your Landing Zone Accelerator (LZA) process.
In our own member account we create only resources that use your instance, and Section 8 lists them
so that nothing there surprises you.

Each request below says what we need, why we need it, and what we hand you to do it. Values in angle
brackets, such as `<PORTAL_ACCOUNT_ID>`, are placeholders. We will send the real values for each
environment (non-production first, then production) when you are ready for them.

## Summary

| # | Request | From you | From us | When |
|---|---|---|---|---|
| 1 | Your change process and lead time | How a change reaches your instance, and how long it takes | This list, and a target date | **Now**: this sets the schedule for everything else |
| 2 | Confirm SCIM from Entra is live | Yes or no, plus three details | Nothing | Now |
| 3 | Trusted token issuer for our Cognito user pool | Create it | Issuer URL, claim name, audience | Before the client-environment checks (Section 7) |
| 4 | Customer-managed application | Create it, with its grants and scopes | Application name, scope list | Before the client-environment checks |
| 5 | Actor policy on the application | Add it | Our server's role ARN | With item 4 |
| 6 | Assignment settings | Your decision, and the assignment if required | Nothing | With item 4 |
| 7 | Cooperation on four client-environment checks | Test users, a test application, a test permission set and a few minutes of console time | The test plan, the test policies and the results | Once items 3 to 6 exist in non-production |
| 8 | The four values we need back | Four values per environment | Nothing | As each environment is configured |

Items 3 to 6 are needed **twice**: once for non-production and once for production. The two
environments have separate user pools, roles and applications.

---

## 1. Your change process and lead time

**This is the largest schedule risk in the move, so we are asking it first.** Every other item is a
change inside your Identity Center instance, and we cannot start the identity work, or the checks in
Section 7, until those changes exist.

**What we need to know:**

- Who owns the organization Identity Center instance, and whether customer-managed applications are
  created in the **management account** or in a **delegated administrator** account.
- Whether applications, trusted token issuers and their policies go through **LZA configuration**,
  through a separate pipeline, or by hand in the console. If LZA cannot express one of them (for
  example, application access scopes or the actor policy in item 5), we would like to know how you
  handle that.
- How a change is requested, who approves it, and the **typical lead time** from request to live,
  for non-production and for production separately.
- Whether there is a change freeze or a release calendar we should plan around.
- A named contact on your team for the checks in Section 7, which need a few minutes of console time
  at an agreed time.

**Why:** your lead time decides when we can start, so we want to plan around it now rather than
discover it later.

**What we hand you:** this list, a target date for the non-production configuration, and a short
call if that is easier than a ticket.

---

## 2. Confirm SCIM provisioning from Entra is live

**What we need:** confirmation that users and groups are provisioned from Entra ID into Identity
Center through SCIM, plus three details:

1. **The external ID is set from the Entra object ID.** Our sign-in tokens carry each user's Entra
   object ID, and item 3 maps that claim to the Identity Center **external ID**. If SCIM fills
   `externalId` from something else, or leaves it empty, no user can be matched.
2. **Which users and groups are in scope.** Every portal user must already exist in Identity
   Center, and the groups we grant data access to must be provisioned too.
3. **How long a change in Entra takes to reach Identity Center**, so we know how soon after
   joining a new user can use the portal's data features.

**Why:** the exchange matches a sign-in to exactly one existing Identity Center user. AWS does not
create users at sign-in, so a user SCIM has not provisioned cannot use any data features. Lake
Formation grants are also made to Identity Center users and groups, so those must exist before we
can grant anything.

**Why the external ID and not email:** Microsoft advises against using email to identify a user,
because an address can be reassigned to another person. The Entra object ID is never reused.

**What we hand you:** nothing. This is a confirmation.

---

## 3. A trusted token issuer for our Cognito user pool

**What we need:** a trusted token issuer on your instance, of type OpenID Connect (OIDC), pointing
at the Amazon Cognito user pool that handles the portal's sign-in.

| Setting | Value |
|---|---|
| Issuer URL | `https://cognito-idp.<REGION>.amazonaws.com/<USER_POOL_ID>` |
| Signing keys | Discovered from the issuer's OpenID configuration (Cognito publishes them there) |
| Token claim to map | `entra_object_id`: our ID tokens carry the user's Entra object ID in this claim |
| Identity Center attribute it maps to | **External ID** |

The **audience** our tokens carry is `<PORTAL_SERVER_CLIENT_ID>`, the ID of our server's Cognito app
client. It is not set on the issuer itself: it goes on the application in item 4, where that
application trusts this issuer.

**Why Cognito sits in the middle:** your organization already federates Cognito to Entra ID, and we
follow that pattern. Users authenticate at Entra, which signs them in to Cognito over SAML, and
Cognito turns that sign-in into a signed OIDC token. Identity Center needs a token of that kind for
the exchange, because trusted identity propagation does not accept SAML.

**This mapping depends on the Entra side matching it.** The Entra enterprise application that
Cognito federates to must send a persistent SAML `NameID` sourced from `user.objectid`, and release
the email address claim. That is a separate request to your Entra administrators. If they are your
team too, please treat it as part of this item. The object ID it carries must also be the value SCIM
writes into the external ID (item 2), or no user will match.

**What we commit to, for your security review.** The pool accepts no self-asserted identity:

- Self-registration is off, the pool has no local users, and Entra is its only identity provider.
  Every user signs in through Entra.
- The user's identity is keyed on the Entra object ID, which arrives as the SAML `NameID`. It is
  never keyed on an email or UPN that Entra could reassign.
- The claim in the table is written into the token from the identity Entra federated, at the moment
  Cognito issues the token. It is not copied from a stored user attribute, so editing an attribute
  could not change it.
- No user can edit their own attributes anyway: no app client may hold the token scope that allows
  it, and no app client allows a sign-in that bypasses Entra.
- No role the portal runs as may write user attributes in the pool.

**What we hand you:** the issuer URL, the claim name and the audience value for each environment.

---

## 4. A customer-managed application

**What we need:** one customer-managed (OAuth) application on your instance for the portal, with the
following configuration.

| Setting | Value |
|---|---|
| Name | `<APPLICATION_NAME>`, for example "Data Quarry portal" plus the environment |
| Grant: JWT bearer | On, trusting the issuer from item 3, with authorized audience `<PORTAL_SERVER_CLIENT_ID>` (in the console, the issuer's "Aud claim") |
| Grant: refresh token | On |
| Access scopes | `lakeformation:query`, `athena:workgroup:read_write`, `s3:access_grants:read_write`, each **without** named target applications (see below) |
| Authentication method | IAM, with the actor policy in item 5 |
| Assignment | See item 6 |

**Why each setting:**

- **JWT bearer** is the exchange itself: our server presents the user's Cognito token and receives
  an Identity Center token for that user.
- **Refresh token** lets our server renew the Identity Center token each hour without repeating the
  exchange. That matters because the exchange has a limit of 10 requests per second, shared by every
  application on your instance, while refreshes have a separate and larger limit. Without the
  refresh grant, our server does not repeat the exchange to make up for it, so every user would be
  asked to sign in again each hour to keep reaching their data.
- **The three scopes** are the set AWS documents for an Identity Center enabled Athena workgroup.
  In our own test, Athena refused the user's session when `athena:workgroup:read_write` was missing,
  so that one is required, not optional.
- **No named targets on the scopes, at first.** Each scope can name the specific applications it
  applies to. Ours are the three that our member account registers on your instance (Section 8),
  and they exist only after you send us the values in Section 8, which in turn come after you create
  this application. So please add the scopes without targets. If your policy requires named targets,
  the order is: you create the application, we register ours, we send you their three application
  ARNs, and you add them as targets.

**We are not asking for the `sso:account:access` scope** on this application. It would let the
application reach users' permission-set roles across accounts, and the portal does not need that.
The one exception is the test application in check C of Section 7, which needs it.

**Why you must create it:** with an organization instance, only the management account or a
delegated administrator can create a customer-managed application. Our member account cannot.

**What we hand you:** the name and the settings above, per environment.

**A second application will follow later**, for desktop tools such as Excel, Access and Power BI.
These connect to Athena through ODBC or JDBC drivers, which also use trusted identity propagation.
As currently designed, that application trusts the same issuer with a separate audience, needs an
actor policy naming a separate role, and carries one tag that the drivers read. We will send its
details once that part of the design is final. **A third application is possible** if we later
broker access for other internal tools; nothing is decided there. We mention both now so that your
lead-time estimate can count them.

---

## 5. The actor policy naming our server's role

**What we need:** the application's IAM authentication method, with a policy that lets exactly one
role in our member account call `CreateTokenWithIAM` on this application. For example:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::<PORTAL_ACCOUNT_ID>:role/<SERVER_TASK_ROLE_NAME>" },
      "Action": "sso-oauth:CreateTokenWithIAM",
      "Resource": "*"
    }
  ]
}
```

Your LZA tooling may express this differently. What matters is that it names that one role: not
our account root, and no wildcard principal.

**Why:** the caller of `CreateTokenWithIAM` can obtain a token for any provisioned user who presents
a valid sign-in token. So this is a privileged identity, and naming one role keeps it narrow. The
role is the task role of the portal's web server, which runs on Amazon ECS. That server performs the
exchange when the user signs in. Our own side grants that role the matching permission on this
application's ARN only.

**What is still unproven:** the role lives in our member account, and the application is created
and managed from your management or delegated administrator account. We have tested this exchange only with the role and
the application in the same account. Check A in Section 7 confirms it works across accounts.

**What we hand you:** the role ARN for each environment. The non-production role exists before you
need it.

---

## 6. The application's assignment settings

**What we need:** your decision on whether the application **requires user and group assignment**
and, if it does, which groups you assign to it. We have not made this choice, and we would like your
view on it.

- **Requiring assignment** limits the exchange to the users and groups you assign, so it would be
  your team's lever over who can use the portal's data features at all. We expect it to stop new
  exchanges for a user you unassign. Whether it also ends a session that user already has open is
  not documented and we have not measured it, so check D below tests that too.
- **Not requiring assignment** also works. Our own test ran that way, and Lake Formation and S3
  Access Grants still limit each user to their own permissions.

**A related question:** applications that AWS services register on your instance (Section 8)
require assignment by default. Does your tooling enforce assignment on those as well? If so, we need
to know which groups to expect on them.

**What we hand you:** nothing, unless you want us to propose a group. Please tell us what you
decide, so that our runbooks describe the real lever.

---

## 7. Cooperation on four checks in the client environment

We have already tested the identity design in a throwaway AWS account of our own, using a small
Identity Center instance created only for the test, and the design passed. Four questions could not
be answered there, because they need an organization instance like yours. Each
check runs in our **non-production** member account against the non-production configuration from
items 3 to 6. Each needs little of your time, and we write up the results and share them with you.

**What every check needs from you:** one or two Entra **test users**, provisioned to Identity Center
by SCIM like real users, plus permission for us to sign them in during the checks.

### A. The cross-account exchange

- **What we do:** sign in a test user. Our server's role, in our member account, then calls
  `CreateTokenWithIAM` against the application in your account. With the token it gets back, we run
  one Athena query as that user.
- **What you do:** nothing beyond items 3 to 6.
- **Why:** every earlier test had the role and the application in the same account. Your
  configuration puts them in different accounts, so this check confirms the design works across
  accounts. It also covers two things our earlier test could not: the sign-in through Entra, and the
  mapping on the external ID from item 3.

### B. Re-running the allow-list check

- **What we do:** in the test user's identity-enhanced session, try a few plain S3 calls and one
  call to an unrelated service, and record which succeed.
- **What you do:** nothing beyond items 3 to 6. If you already know of any organization setting or
  SCP that restricts identity-enhanced sessions, please tell us.
- **Why:** AWS documents a managed policy, `AWSIAMIdentityCenterAllowListForIdentityContext`, that
  is meant to limit what an identity-enhanced session can do. In our test it was **not in effect**.
  We do not rely on it, because our own role and bucket policies are the controls, but we want to
  know how it behaves on your instance. Then both teams know which controls actually limit a
  session.

### C. Permission sets (three questions)

- **What we do:** sign in the test user through a **test** application that has the
  `sso:account:access` scope, obtain their permission-set credentials for our non-production
  account, and answer three questions:
  1. Do those credentials carry the user's identity through to Lake Formation?
  2. Do Identity Center's **attributes for access control** arrive on the session as tags?
  3. Do plain S3 calls work with those credentials?
- **What you do:**
  - Tell us whether **identity-enhanced sessions** are enabled on your instance. The check needs
    them, and they are an instance-wide setting, so if they are off, the decision to turn them on is
    yours and we will not ask lightly.
  - Create a separate **test application** with the `sso:account:access` scope. Like the portal's,
    it needs the JWT bearer grant trusting the issuer from item 3, an audience we give you, and an
    actor policy naming a test role in our non-production account. Assign the test user to it.
  - Create a **test permission set** and assign it to the test user on our non-production account
    only. Its policy allows `sts:SetContext`, plus read access to one Athena workgroup, the Lake
    Formation catalog and one scratch S3 bucket in that account. We will send the policy.
  - Tell us whether **attributes for access control** are enabled, and which attributes they carry.
    Question 2 cannot run while they are off. In that case we run questions 1 and 3 only, unless you
    choose to enable one test attribute.
  - Remove the test application and the permission set afterwards.
- **Why:** this decides whether a simpler storage design, fed by permission sets, is open to us.
  An account instance like ours has no permission sets, so the check can only run on yours. AWS
  documents that `sso:account:access` cannot be limited to particular accounts, which is why we ask
  for a separate test application rather than adding the scope to the portal's.

### D. Deleting a test user's Identity Center session

- **What we do:** sign in a test user and keep their portal session open. At a time we agree with
  you, you delete the session. We then try the hourly refresh and a fresh exchange, and record
  whether each still succeeds. If you require assignment (item 6), we repeat it once with the test
  user unassigned instead.
- **What you do:** delete that test user's active session in the Identity Center console, at the
  agreed time, and unassign them for the repeat. A few minutes of your time.
- **Why:** we have not measured what an application sees after an administrator deletes a user's
  session or unassigns them. Our server's behaviour at that moment is still to be designed, and this
  check tells us whether your action stops the refresh, the fresh exchange, both or neither.

---

## 8. The four values we need back, and what we create ourselves

**Please send these for each environment** once items 3 to 6 are configured there:

| Value | Shape | What we use it for |
|---|---|---|
| Identity Center instance ARN | `arn:aws:sso:::instance/ssoins-<…>` | Associating our S3 Access Grants instance, Lake Formation and the Athena workgroup with your instance |
| Identity store ID | `d-<…>` | Resolving users and groups when we make Lake Formation and S3 Access Grants grants |
| Application ARN | `arn:aws:sso::<ACCOUNT_ID>:application/ssoins-<…>/apl-<…>` | The application our server names when it calls `CreateTokenWithIAM` |
| Trusted token issuer audience | The audience value as you configured it | Our configuration checks that it matches the app client ID it creates. We supply this value in item 3, and ask for it back as entered so that a mismatch shows up before the first sign-in |

**Please also confirm the AWS Region your instance runs in.** Trusted identity propagation with
Athena works only in a listed set of Regions. Your instance, our Access Grants instance, our Athena
workgroup and our Lake Formation configuration must all be in that same Region.

**What we create in our own member account**, so that you know what will appear. Nothing here
changes your instance's configuration, and all of it stays off until the four values above arrive:

- An **S3 Access Grants instance**, associated with your Identity Center instance.
- The account's **Lake Formation Identity Center configuration**.
- An **Identity Center enabled Athena workgroup** for the portal.
- A **role that carries the user's identity** to these services, the **role S3 Access Grants uses**
  to reach the portal's bucket, and an encryption key used by the portal's server.
- Later, for the desktop-tool application in item 4: two more roles and a second Athena workgroup.

Associating the first three with your instance registers an AWS-managed application for each one on
your instance.

**Please check your SCPs and Identity Center settings against what our member account,
`<PORTAL_ACCOUNT_ID>`, has to do.** We would rather find out from you than from a failed deployment:

- Register those three AWS-managed applications on your instance.
- Call `sso-oauth:CreateTokenWithIAM` (the exchange in item 5).
- Call `identitystore` read actions, to look up users and groups when we make grants.
- Call the `sso` actions those registrations use.

AWS documents an SCP pattern that denies the `sso`, `sso-oauth` and `identitystore` action families
outside designated accounts, and an instance setting that shares identity information only with the
management account. Either would block us. If you use them, please tell us what exception process
applies.

**One last question:** do other applications on your instance already use trusted token issuers?
The exchange limit in item 4 (10 per second) is shared across the whole instance. If other
applications already use it, we may need to request a higher limit together.
