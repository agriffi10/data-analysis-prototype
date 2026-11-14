# `session-store` — the portal server's sessions

One DynamoDB table and the customer-managed KMS key it is encrypted with. The portal's Next.js
server keeps each browser's session here, keyed by a digest of the opaque cookie it hands out, and
the item holds the ID and refresh tokens the browser never sees.

| File | Holds |
|---|---|
| `main.tf` | the key, its alias and the table |
| `names.tf` | the key alias the deploy role's grant is written against |
| `variables.tf` | the module interface; root names the table, so root builds its ARN from the same string |

## Why it sits outside the web tier's switch

`web_tier_enabled = false` removes `network` and `spa` whole ([`../../info/web-tier.md`](../../info/web-tier.md)).
Inside them, the key would be scheduled for deletion on every switch-off and every session would go
with the table. Out here it costs about a dollar a month for the key and nothing for an idle
on-demand table. Nothing in this module reads a `network` or `spa` output, which is the switch's
own rule.

## The key's policy names the account and nothing else

It delegates to IAM. The identity policies that use the key are the deploy role's (creating the
table makes DynamoDB use the key on its behalf) and the task role's (reading and writing items),
and each is conditioned on `kms:ViaService` for DynamoDB. A key policy naming the task role would
make a resource outside the switch depend on a role inside it.

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
