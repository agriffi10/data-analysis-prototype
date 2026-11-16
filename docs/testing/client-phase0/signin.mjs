#!/usr/bin/env node
/**
 * Sign a test user in through the Cognito managed login, federated to Entra, and keep the Cognito
 * tokens for the exchanger.
 *
 * `login` runs the authorization-code flow with PKCE against a redirect on localhost, so the person
 * running it signs in through Entra in their own browser and no password passes through this script.
 * `refresh` redeems the kept refresh token for a new ID token, which carries a new `jti` and so is a
 * fresh assertion for `CreateTokenWithIAM`.
 *
 * Usage:
 *   node signin.mjs login   --user alice
 *   node signin.mjs refresh --user alice --label C4.cognito.refresh.after
 */
import { createHash, randomBytes } from 'node:crypto';
import { createServer } from 'node:http';
import { parseArgs } from 'node:util';
import { Evidence, decodeJwt, loggableClaims, readSecret, requireEnv, writeSecret } from './evidence.mjs';

/**
 * Call the Cognito token endpoint.
 * @param {URLSearchParams} form The form body.
 * @returns {Promise<{ok: true, body: Record<string, string>} | {ok: false, code: string, message: string, data: Record<string, unknown>}>} The tokens, or why not.
 */
async function tokenEndpoint(form) {
  const headers = { 'content-type': 'application/x-www-form-urlencoded' };
  const secret = process.env.COGNITO_CLIENT_SECRET;
  if (secret) {
    const basic = Buffer.from(`${requireEnv('COGNITO_CLIENT_ID')}:${secret}`).toString('base64');
    headers.authorization = `Basic ${basic}`;
  }
  let res;
  try {
    res = await fetch(`${requireEnv('COGNITO_DOMAIN')}/oauth2/token`, { method: 'POST', headers, body: form });
  } catch (err) {
    return { ok: false, code: 'Local:fetch', message: String(err), data: {} };
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    return { ok: false, code: `OAuth:${body.error ?? res.status}`, message: body.error_description ?? '', data: { httpStatus: res.status } };
  }
  return { ok: true, body };
}

/**
 * The loggable view of a Cognito ID token: its claims, plus the federation facts check 5 reads.
 * @param {string} idToken The ID token.
 * @returns {Record<string, unknown>} Claims and the federated provider, if any.
 */
function describeIdToken(idToken) {
  const claims = decodeJwt(idToken);
  let identities = claims.identities;
  if (typeof identities === 'string') identities = JSON.parse(identities);
  const first = Array.isArray(identities) && identities.length > 0 ? identities[0] : null;
  const oidClaim = process.env.OID_CLAIM || 'entra_oid';
  return {
    claims: loggableClaims(claims),
    federated: first ? { providerName: first.providerName, providerType: first.providerType, userId: first.userId } : null,
    oidClaim,
    oidClaimValue: claims[oidClaim] ?? null,
  };
}

/**
 * Wait for the single redirect that carries the authorization code.
 * @param {number} port The local port.
 * @param {string} state The state value the redirect must echo.
 * @returns {Promise<string>} The code.
 */
function awaitCode(port, state) {
  return new Promise((resolvePromise, reject) => {
    const timer = setTimeout(() => {
      server.close();
      reject(new Error('no redirect within 5 minutes'));
    }, 300_000);
    const server = createServer((req, res) => {
      const url = new URL(req.url ?? '/', `http://localhost:${port}`);
      if (url.pathname !== '/callback') {
        res.writeHead(404).end();
        return;
      }
      const error = url.searchParams.get('error');
      const ok = !error && url.searchParams.get('state') === state && url.searchParams.get('code');
      res.writeHead(ok ? 200 : 400, { 'content-type': 'text/plain' }).end(ok ? 'Signed in. Return to the terminal.' : 'Sign-in failed. Return to the terminal.');
      clearTimeout(timer);
      server.close();
      if (error) reject(new Error(`authorize returned ${error}: ${url.searchParams.get('error_description') ?? ''}`));
      else if (url.searchParams.get('state') !== state) reject(new Error('state mismatch on the redirect'));
      else resolvePromise(/** @type {string} */ (url.searchParams.get('code')));
    });
    server.listen(port, 'localhost');
  });
}

/**
 * Sign in and keep the tokens.
 * @param {string} user The fixture user's short name, which names the token file.
 * @param {string} label The evidence label.
 * @returns {Promise<void>}
 */
async function login(user, label) {
  const evidence = new Evidence(requireEnv('PHASE0_EVIDENCE'));
  const port = Number(process.env.REDIRECT_PORT || '8766');
  const redirectUri = `http://localhost:${port}/callback`;
  const verifier = randomBytes(32).toString('base64url');
  const state = randomBytes(16).toString('base64url');
  const authorize = new URL(`${requireEnv('COGNITO_DOMAIN')}/oauth2/authorize`);
  authorize.search = new URLSearchParams({
    response_type: 'code',
    client_id: requireEnv('COGNITO_CLIENT_ID'),
    redirect_uri: redirectUri,
    scope: 'openid email profile',
    state,
    code_challenge: createHash('sha256').update(verifier).digest('base64url'),
    code_challenge_method: 'S256',
    ...(process.env.ENTRA_IDP_NAME ? { identity_provider: process.env.ENTRA_IDP_NAME } : {}),
  }).toString();
  process.stdout.write(`Open this in a browser and sign in as the ${user} test user:\n\n${authorize}\n\n`);
  const code = await awaitCode(port, state);
  const result = await tokenEndpoint(
    new URLSearchParams({ grant_type: 'authorization_code', client_id: requireEnv('COGNITO_CLIENT_ID'), code, redirect_uri: redirectUri, code_verifier: verifier }),
  );
  if (!result.ok) {
    evidence.record(label, result);
    process.exitCode = 1;
    return;
  }
  const { id_token: idToken, refresh_token: refreshToken, access_token: accessToken } = result.body;
  evidence.addSecrets(idToken, refreshToken, accessToken);
  writeSecret(`cognito-${user}.json`, { idToken, refreshToken, obtainedAt: new Date().toISOString() });
  evidence.record(label, { ok: true, data: { user, idToken: describeIdToken(idToken), hasRefreshToken: Boolean(refreshToken) } });
}

/**
 * Redeem the kept refresh token for a new ID token and keep it.
 * @param {string} user The fixture user's short name.
 * @param {string} label The evidence label.
 * @returns {Promise<void>}
 */
async function refresh(user, label) {
  const evidence = new Evidence(requireEnv('PHASE0_EVIDENCE'));
  const kept = readSecret(`cognito-${user}.json`);
  evidence.addSecrets(kept.idToken, kept.refreshToken);
  const result = await tokenEndpoint(
    new URLSearchParams({ grant_type: 'refresh_token', client_id: requireEnv('COGNITO_CLIENT_ID'), refresh_token: kept.refreshToken }),
  );
  if (!result.ok) {
    evidence.record(label, result);
    process.exitCode = 1;
    return;
  }
  const idToken = result.body.id_token;
  evidence.addSecrets(idToken, result.body.access_token);
  writeSecret(`cognito-${user}.json`, { idToken, refreshToken: kept.refreshToken, obtainedAt: new Date().toISOString() });
  evidence.record(label, { ok: true, data: { user, idToken: describeIdToken(idToken) } });
}

const { positionals, values } = parseArgs({
  allowPositionals: true,
  options: { user: { type: 'string' }, label: { type: 'string' } },
});
const [mode] = positionals;
if (!values.user || (mode !== 'login' && mode !== 'refresh')) {
  process.stderr.write('usage: node signin.mjs login|refresh --user <name> [--label <label>]\n');
  process.exit(2);
}
const label = values.label ?? `cognito.${mode}.${values.user}`;
await (mode === 'login' ? login(values.user, label) : refresh(values.user, label));
