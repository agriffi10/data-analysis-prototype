# `session-store` — the portal server's sessions

One DynamoDB table and the customer-managed KMS key it is encrypted with. The portal's Next.js
server keeps each browser's session here, keyed by a digest of the opaque cookie it hands out, and
the item holds the ID and refresh tokens the browser never sees.

Root calls it twice: `session_store` for the deployed server, and `dev_session_store` for local dev
servers, which `npm run dev:session-env` points at through the dev parameter.

| File | Holds |
|---|---|
| `main.tf` | the key, its alias and the table, and the choice between the two key policies |
| `policies/key-named.json.tftpl` | the deployed store's key policy, which names its principals |
| `policies/key-delegated.json.tftpl` | the dev store's key policy, which delegates to the account's IAM |
| `variables.tf` | the module interface; root names the table and the alias, and builds the grants' ARNs from the same strings |

## Why it sits outside the web tier's switch

`web_tier_enabled = false` removes `network` and `spa` whole ([`../../info/web-tier.md`](../../info/web-tier.md)).
Inside them, the key would be scheduled for deletion on every switch-off and every session would go
with the table. Out here it costs about a dollar a month for the key and nothing for an idle
on-demand table. Nothing in this module reads a `network` or `spa` output, which is the switch's
own rule.

## The deployed key's policy names who may use it

Root passes `named_principals`, and the key's own policy decides; no identity policy can widen it,
because the policy does not delegate to the account. Without that, any principal IAM allows to read
the table and use KMS (an administrator, a broad operations role) could read every refresh token.

- **The deploy role administers the key** and uses it only through DynamoDB, the minimum AWS
  documents for the principal that puts a table under a customer-managed key. It holds no item-level
  grant on the table, so it cannot read a token through that.
- **The web task role uses it for this table alone**: `Encrypt`, `Decrypt`, `GenerateDataKey*` and
  `ReEncrypt*` through DynamoDB, bound by the table-name encryption context, and `DescribeKey`
  through DynamoDB. It is matched by `aws:PrincipalArn` on a `"*"` principal, which KMS does not
  check exists, so this key outside the switch does not need the role inside it. Root builds the
  role's ARN from the name the `spa` module gives it, and a test holds the two equal.
- **The account root reads the key's metadata and nothing else** (`DescribeKey`, `GetKeyPolicy`,
  `GetKeyRotationStatus`, `ListResourceTags`), for a security reviewer, AWS Config and a local plan.
  It is not given `PutKeyPolicy`: that would hand the key to every principal an identity policy
  allows `kms:PutKeyPolicy` on `*`.
- **No `Deny`.** DynamoDB uses grants on the key whose grantee is its service principal, and a
  negated `aws:PrincipalArn` condition on a call that may carry no such key could deny DynamoDB
  itself. A policy that does not delegate already refuses every principal it does not name.

**What it rests on.** The deploy role is the trust root: its `PutKeyPolicy` lets it grant itself
anything. `aws:PrincipalArn` matches the task role by name, so only the deploy role may create,
re-trust or pass a role among the principals the IaC builds, and
`lambdas/test_only_the_deploy_role_can_become_another_role.py` holds that. Losing the deploy role
loses administration of the key (KMS stores a named role as its unique id), and the recovery is a
new store under new names, which costs every user one sign-in.

## The dev store's key delegates

A local dev server signs in with the developer's own credentials, whatever they are, so its key
delegates to the account's IAM and names no principal, as every store's did before. Its table holds
only sessions a dev server created; a session serves only the client that created it, so the deployed
server never reads one.

## Encryption is the table's, not the server's

A Cognito ID token can reach about five kilobytes when a user has every shared-space membership,
and KMS `Encrypt` takes at most 4,096 bytes of plaintext, so the server cannot encrypt tokens itself
in one call. The table's at-rest encryption under this key is what keeps them encrypted with a
customer-managed key.

## Expiry is checked on read; TTL is hygiene

DynamoDB deletes an expired item within days and returns it until then. The server treats an item
at or past its session expiry as absent and deletes it, so the TTL attribute only keeps the table
small. Point-in-time recovery is off on purpose: a backup would keep refresh tokens past the
sessions they belong to.
