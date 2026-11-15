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

/** One session variable, by name. */
export type SessionVariable = (typeof SESSION_VARIABLES)[number];

/** Why one session variable cannot be used. Named by variable and never by value. */
export type SessionProblem = {variable: SessionVariable; reason: 'unset-or-empty' | 'unusable'};

/** Hosts the server may reach over plain HTTP: its own machine, where a local harness runs. */
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);

/**
 * The URLs the server sends credentials to. The server skips the ID token's signature check because
 * the token comes straight from the token endpoint over TLS (OIDC Core §3.1.3.7), and it sends the
 * client secret and the bearer to these hosts, so a plain `http:` value would expose the secret and
 * admit a forged token.
 */
const CREDENTIAL_URLS: ReadonlySet<SessionVariable> = new Set(['API_ORIGIN', 'OIDC_TOKEN_URL', 'OIDC_REVOKE_URL']);

/**
 * Whether a set value is one the server can use.
 *
 * @param name - The variable.
 * @param value - Its value, already known to be non-blank.
 * @returns False for a credential URL that is not HTTPS or loopback HTTP, and for a session ceiling that
 *   is not a positive whole number of seconds.
 */
function usable(name: SessionVariable, value: string): boolean {
  if (CREDENTIAL_URLS.has(name)) {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      return false;
    }
    return url.protocol === 'https:' || (url.protocol === 'http:' && LOOPBACK.has(url.hostname));
  }
  if (name === 'SESSION_MAX_AGE_SECONDS') {
    const seconds = Number(value);
    return Number.isInteger(seconds) && seconds > 0;
  }
  return true;
}

/**
 * Every session variable that is unset, blank or unusable, in the order the server reads them.
 *
 * The one statement of each rule: the start-time check collects them all so one run names every
 * problem, and `sessionConfig` refuses on the first.
 *
 * @param env - The environment to read; the process's own by default.
 * @returns The problems, empty when every variable is usable.
 */
export function sessionProblems(env: NodeJS.ProcessEnv = process.env): SessionProblem[] {
  const problems: SessionProblem[] = [];
  for (const variable of SESSION_VARIABLES) {
    const value = env[variable];
    if (value === undefined || value.trim() === '') problems.push({variable, reason: 'unset-or-empty'});
    else if (!usable(variable, value)) problems.push({variable, reason: 'unusable'});
  }
  return problems;
}

/**
 * Read the session configuration from the server's environment.
 *
 * Called by each route as it runs. The start-time check refuses to start a server missing any of these,
 * so a route reaches the refusal only in a process that skipped that check, and answers 503 rather than
 * throwing.
 *
 * @param env - The environment to read; the process's own by default.
 * @returns The configuration.
 * @throws SessionConfigError naming the first variable that is unset or unusable.
 */
export function sessionConfig(env: NodeJS.ProcessEnv = process.env): SessionConfig {
  const [first] = sessionProblems(env);
  if (first) throw new SessionConfigError(first.variable);
  const value = (name: SessionVariable): string => env[name] as string;
  return {
    portalOrigin: value('PORTAL_ORIGIN'),
    apiOrigin: value('API_ORIGIN'),
    issuer: value('OIDC_ISSUER'),
    clientId: value('OIDC_CLIENT_ID'),
    clientSecret: value('OIDC_CLIENT_SECRET'),
    authorizeUrl: value('OIDC_AUTHORIZE_URL'),
    tokenUrl: value('OIDC_TOKEN_URL'),
    revokeUrl: value('OIDC_REVOKE_URL'),
    logoutUrl: value('OIDC_LOGOUT_URL'),
    tableName: value('SESSION_TABLE_NAME'),
    maxAgeSeconds: Number(value('SESSION_MAX_AGE_SECONDS')),
    region: value('AWS_REGION')
  };
}
