/**
 * Offline tests for the exchanger: what it records and keeps, asserted by reason, with fake SDK clients.
 *
 * Run from this directory with `node --test exchange_test.mjs`; it needs no AWS SDK.
 */
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { Evidence } from './evidence.mjs';
import { JWT_BEARER, applicationAccount, runExchange } from './exchange.mjs';

const APP = 'arn:aws:sso::111111111111:application/ssoins-aaaa/apl-bbbb';
const CONTEXT = 'opaque-identity-context-value';

class CreateTokenWithIAMCommand {
  constructor(input) {
    this.input = input;
  }
}
class GetCallerIdentityCommand {
  constructor(input) {
    this.input = input;
  }
}
const commands = { CreateTokenWithIAMCommand, GetCallerIdentityCommand };

/**
 * A compact JWT with the given payload and a dummy signature.
 * @param {Record<string, unknown>} payload The claims.
 * @returns {string} The token.
 */
function jwt(payload) {
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  return `${enc({ alg: 'RS256' })}.${enc(payload)}.signaturepart`;
}

/**
 * A fresh evidence log in a temporary directory.
 * @returns {{evidence: Evidence, lines: () => Record<string, any>[]}} The log and a reader.
 */
function freshLog() {
  const dir = mkdtempSync(join(tmpdir(), 'phase0-'));
  const path = join(dir, 'evidence.jsonl');
  return { evidence: new Evidence(path), lines: () => readFileSync(path, 'utf8').trim().split('\n').map((l) => JSON.parse(l)) };
}

const sts = { send: async () => ({ Account: '222222222222', Arn: 'arn:aws:sts::222222222222:assumed-role/task-role/s' }) };

test('a successful exchange records the context from both sources and keeps the tokens', async () => {
  const { evidence, lines } = freshLog();
  const idToken = jwt({ sub: 'user-id-1', exp: 1_900_000_000, 'sts:identity_context': CONTEXT, jti: 'abc' });
  let sent;
  const oidc = {
    send: async (cmd) => {
      sent = cmd.input;
      return { accessToken: 'atatatatatatat', refreshToken: 'rtrtrtrtrtrtrt', idToken, scope: ['openid'], expiresIn: 3600, awsAdditionalDetails: { identityContext: CONTEXT } };
    },
  };
  const kept = await runExchange({ oidc, sts, commands, evidence, mode: 'jwt', appArn: APP, credential: jwt({ sub: 'cognito' }), label: 'C1.exchange' });
  assert.equal(sent.grantType, JWT_BEARER);
  assert.equal(kept.identityContext, CONTEXT);
  assert.equal(kept.identityStoreUserId, 'user-id-1');
  const [caller, exchange] = lines();
  assert.equal(caller.label, 'C1.exchange.caller');
  assert.equal(exchange.data.appAccount, '111111111111');
  assert.deepEqual(exchange.data.context.fieldMatchesClaim, true);
  assert.equal(exchange.data.idTokenClaims['sts:identity_context'].len, CONTEXT.length);
  const raw = readFileSync(evidence.path, 'utf8');
  for (const secret of [CONTEXT, 'atatatatatatat', 'rtrtrtrtrtrtrt', idToken]) assert.ok(!raw.includes(secret), 'a secret reached the log');
});

test('an SDK that drops awsAdditionalDetails still yields the context from the idToken claim', async () => {
  const { evidence, lines } = freshLog();
  const oidc = { send: async () => ({ accessToken: 'atatatatatatat', idToken: jwt({ sub: 'u', 'sts:identity_context': CONTEXT }) }) };
  const kept = await runExchange({ oidc, sts, commands, evidence, mode: 'refresh', appArn: APP, credential: 'rtrtrtrtrtrtrt', label: 'C4.refresh.before' });
  assert.equal(kept.identityContext, CONTEXT);
  assert.equal(kept.refreshToken, 'rtrtrtrtrtrtrt');
  const ctx = lines()[1].data.context;
  assert.deepEqual([ctx.fromField, ctx.fromClaim, ctx.fieldMatchesClaim], [false, true, null]);
});

test('a refusal records the service code, and a failure that never reached AWS is marked Local', async () => {
  const { evidence, lines } = freshLog();
  const refused = Object.assign(new Error('UnknownError'), {
    name: 'InvalidGrantException',
    error: 'invalid_grant',
    error_description: 'Assertion has already been used',
    $metadata: { httpStatusCode: 400 },
  });
  const local = Object.assign(new Error('Could not load credentials'), { name: 'CredentialsProviderError' });
  for (const err of [refused, local]) {
    const kept = await runExchange({ oidc: { send: async () => { throw err; } }, sts, commands, evidence, mode: 'jwt', appArn: APP, credential: 'x'.repeat(20), label: 'C1.exchange' });
    assert.equal(kept, null);
  }
  const exchanges = lines().filter((l) => l.label === 'C1.exchange');
  assert.equal(exchanges[0].code, 'InvalidGrantException');
  assert.equal(exchanges[0].message, 'Assertion has already been used');
  assert.equal(exchanges[0].data.caller.account, '222222222222');
  assert.equal(exchanges[1].code, 'Local:CredentialsProviderError');
});

test('the log refuses a JWT and a path inside a checkout', () => {
  const { evidence } = freshLog();
  assert.throws(() => evidence.record('x', { ok: true, data: { t: jwt({ a: 1 }) } }), /holds a JWT/);
  evidence.addSecrets('opaque-secret-value');
  assert.throws(() => evidence.record('x', { ok: true, data: { t: 'xopaque-secret-valuex' } }), /registered secret/);
  const repo = mkdtempSync(join(tmpdir(), 'phase0-repo-'));
  mkdirSync(join(repo, '.git'));
  assert.throws(() => new Evidence(join(repo, 'e.jsonl')), /inside the git checkout/);
  assert.equal(applicationAccount('arn:aws:iam::1:role/x'), null);
});
