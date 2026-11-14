import 'server-only';

/** Every variable the session routes read, by the name the task definition sets. */
export const SESSION_VARIABLES = [
  'PORTAL_ORIGIN',
  'API_ORIGIN',
  'OIDC_ISSUER',
  'OIDC_CLIENT_ID',
  'OIDC_CLIENT_SECRET',
  'OIDC_AUTHORIZE_URL',
  'OIDC_TOKEN_URL',
  'OIDC_REVOKE_URL',
  'OIDC_LOGOUT_URL',
  'SESSION_TABLE_NAME',
  'SESSION_MAX_AGE_SECONDS',
  'AWS_REGION'
] as const;

/** The session routes' configuration, read when a route runs. */
export type SessionConfig = {
  portalOrigin: string;
  apiOrigin: string;
  issuer: string;
  clientId: string;
  clientSecret: string;
  authorizeUrl: string;
  tokenUrl: string;
  revokeUrl: string;
  logoutUrl: string;
  tableName: string;
  maxAgeSeconds: number;
  region: string;
};

/** A session setting is missing or unusable. Its message names the variable and never a value. */
export class SessionConfigError extends Error {
  readonly variable: string;

  constructor(variable: string) {
    super(`session setting ${variable} is unset or unusable`);
    this.name = 'SessionConfigError';
    this.variable = variable;
  }
}

/**
 * Read one variable, refusing an unset, empty or whitespace value.
 *
 * @param name - The variable.
 * @returns Its value.
 * @throws SessionConfigError naming the variable.
 */
function required(name: (typeof SESSION_VARIABLES)[number]): string {
  const value = process.env[name];
  if (value === undefined || value.trim() === '') throw new SessionConfigError(name);
  return value;
}

/** Hosts the server may reach over plain HTTP: its own machine, where a local harness runs. */
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);

/**
 * Read a URL the server sends credentials to, refusing anything but HTTPS off this machine.
 *
 * The server skips the ID token's signature check because the token comes straight from the token
 * endpoint over TLS (OIDC Core §3.1.3.7), and it sends the client secret and the bearer to these
 * hosts, so a plain `http:` value would expose the secret and admit a forged token.
 *
 * @param name - The variable.
 * @returns Its value.
 * @throws SessionConfigError naming the variable when it is not HTTPS or loopback HTTP.
 */
function secureUrl(name: 'API_ORIGIN' | 'OIDC_TOKEN_URL' | 'OIDC_REVOKE_URL'): string {
  const value = required(name);
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new SessionConfigError(name);
  }
  if (url.protocol === 'https:' || (url.protocol === 'http:' && LOOPBACK.has(url.hostname))) return value;
  throw new SessionConfigError(name);
}

/**
 * Read the session configuration from the server's environment.
 *
 * Called by each route as it runs and never at import or at startup: a server that read these while
 * booting would refuse to start when one is unset, taking every page down with the session routes.
 * No page uses them yet, so the routes answer 503 instead.
 *
 * @returns The configuration.
 * @throws SessionConfigError naming the first variable that is unset or unusable.
 */
export function sessionConfig(): SessionConfig {
  const maxAge = Number(required('SESSION_MAX_AGE_SECONDS'));
  if (!Number.isInteger(maxAge) || maxAge <= 0) throw new SessionConfigError('SESSION_MAX_AGE_SECONDS');
  return {
    portalOrigin: required('PORTAL_ORIGIN'),
    apiOrigin: secureUrl('API_ORIGIN'),
    issuer: required('OIDC_ISSUER'),
    clientId: required('OIDC_CLIENT_ID'),
    clientSecret: required('OIDC_CLIENT_SECRET'),
    authorizeUrl: required('OIDC_AUTHORIZE_URL'),
    tokenUrl: secureUrl('OIDC_TOKEN_URL'),
    revokeUrl: secureUrl('OIDC_REVOKE_URL'),
    logoutUrl: required('OIDC_LOGOUT_URL'),
    tableName: required('SESSION_TABLE_NAME'),
    maxAgeSeconds: maxAge,
    region: required('AWS_REGION')
  };
}
