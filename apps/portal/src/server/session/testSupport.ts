import 'server-only';
import {DEFAULT_USERNAME_CLAIM, type SessionConfig} from './config';
import {fakeDynamo} from './fakeDynamo';
import type {SessionDeps} from './handlers';
import {sessionKey} from './session';
import type {SessionItem} from './session.types';
import {dynamoSessionStore} from './store';

/**
 * Support for the session suites only: a configuration, ID tokens and a provider double.
 *
 * Tokens are built here at runtime and carry no signature, so nothing secret-shaped sits in the
 * history, and the server never verifies a signature anyway.
 */

export const PORTAL = 'https://portal.example.test';
export const API = 'https://api.example.test';

/** A configuration with every setting, pointing at doubles. */
export function testConfig(overrides: Partial<SessionConfig> = {}): SessionConfig {
  return {
    portalOrigin: PORTAL,
    apiOrigin: API,
    issuer: 'https://issuer.example.test/pool',
    clientId: 'server-client',
    clientSecret: ['client', 'secret', 'value'].join('-'),
    authorizeUrl: 'https://auth.example.test/oauth2/authorize',
    tokenUrl: 'https://auth.example.test/oauth2/token',
    revokeUrl: 'https://auth.example.test/oauth2/revoke',
    logoutUrl: 'https://auth.example.test/logout',
    tableName: 'test-sessions',
    maxAgeSeconds: 30 * 86400,
    region: 'us-east-1',
    usernameClaim: DEFAULT_USERNAME_CLAIM,
    ...overrides
  };
}

/** The current time the suites run at, epoch seconds. */
export const NOW = 1_800_000_000;

/**
 * An unsigned ID token with Cognito's claim shape.
 *
 * @param claims - Claims to add or replace.
 * @returns The token.
 */
export function idToken(claims: Record<string, unknown> = {}): string {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString('base64url');
  const body = {
    iss: 'https://issuer.example.test/pool',
    aud: 'server-client',
    token_use: 'id',
    iat: NOW,
    exp: NOW + 3600,
    'cognito:username': 'alice',
    email: 'alice@example.test',
    ...claims
  };
  return [encode({alg: 'none', typ: 'JWT'}), encode(body), 'unsigned'].join('.');
}

/** A stored session, with a cookie that names it. */
export function storedSession(overrides: Partial<SessionItem> = {}): {cookie: string; item: SessionItem} {
  const cookie = 'c'.repeat(43);
  return {
    cookie,
    item: {
      pk: sessionKey(cookie),
      idToken: idToken(),
      refreshToken: ['refresh', 'token', 'one'].join('-'),
      tokenExpiresAt: NOW + 3600,
      sessionExpiresAt: NOW + 30 * 86400,
      expiresAt: NOW + 30 * 86400,
      version: 0,
      ...overrides
    }
  };
}

/** Dependencies over a fresh fake table, with the fake exposed for assertions. */
export function testDeps(config: SessionConfig = testConfig()): SessionDeps & {dynamo: ReturnType<typeof fakeDynamo>} {
  const dynamo = fakeDynamo();
  return {config, store: dynamoSessionStore(config.tableName, dynamo.send), dynamo};
}

/** A JSON response, as the provider or the API would send it. */
export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json', ...headers}});
}
