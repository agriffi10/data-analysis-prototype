import 'server-only';
import {OPTIONAL_CONFIG, REQUIRED_CONFIG} from '../types/runtimeConfig.types';
import type {RuntimeConfigDocument, RuntimeConfigKey} from '../types/runtimeConfig.types';
import {sessionProblems} from './session/config';

/** The document version the browser's loader accepts; it refuses any other whole. */
const DOCUMENT_VERSION = 1;

/** The variable the request proxy builds `connect-src` from. */
const CONNECT_SRC_VARIABLE = 'PORTAL_CSP_CONNECT_SRC';

/**
 * What a CSP source list may contain: hosts, schemes, keywords, wildcards.
 *
 * An allowlist rather than a scan for bad characters, because a scan can be outflanked by a
 * character nobody thought of. A `;` would append a directive of the sender's choosing to every
 * page's policy, and a `"` or a newline has no business in a header at all.
 */
const SOURCE_LIST = /^[A-Za-z0-9':/. _*-]+$/;

/** One reason the server will not start, named by variable and never by value. */
export type StartupProblem = {
  variable: string;
  reason: 'unset-or-empty' | 'invalid-characters' | 'unusable';
};

/**
 * Whether a variable carries a value, as distinct from being unset, empty or only whitespace.
 *
 * Whitespace is unset too: a source list of one space passed the allowlist and served
 * `connect-src  ;`, a policy that blocks every fetch, the document's included, from a server the
 * load balancer read as healthy.
 *
 * @param value - The variable's value, if any.
 * @returns True when there is something besides whitespace.
 */
function isSet(value: string | undefined): value is string {
  return value !== undefined && value.trim() !== '';
}

/**
 * The name of the environment variable that carries one configuration key.
 *
 * @param key - A classified key.
 * @returns `CONFIG_<key>`, the name the task definition renders for it.
 */
function variableFor(key: RuntimeConfigKey): string {
  return `CONFIG_${key}`;
}

/**
 * The runtime configuration document, rendered from the server's environment.
 *
 * Exactly the keys the browser classifies, read by name: never a sweep of every `CONFIG_*`
 * variable, because the document is world-readable and a sweep publishes whatever same-prefixed
 * variable an orchestrator or base image adds. An empty value is dropped, because the browser
 * reads an absent key and an empty one alike.
 *
 * @param env - The environment to read; the process's own by default.
 * @returns The document, version first.
 */
export function renderRuntimeDocument(env: NodeJS.ProcessEnv = process.env): RuntimeConfigDocument {
  const document: RuntimeConfigDocument = {version: DOCUMENT_VERSION};
  for (const key of [...REQUIRED_CONFIG, ...OPTIONAL_CONFIG]) {
    const value = env[variableFor(key)];
    if (isSet(value)) document[key] = value;
  }
  return document;
}

/**
 * Every reason this server must not start, collected so one run names them all.
 *
 * Unset, empty and whitespace-only are the same failure: an unset repository variable and an unset
 * task variable both arrive as the empty string, and a server that starts with an empty required value serves a
 * portal that fails every call it makes. The session variables are required too, because every page signs
 * in through the session routes: a server without them would serve pages nobody can sign in to.
 *
 * @param env - The environment to read; the process's own by default.
 * @returns The problems, empty when the server may start.
 */
export function startupProblems(env: NodeJS.ProcessEnv = process.env): StartupProblem[] {
  const problems: StartupProblem[] = REQUIRED_CONFIG.filter((key) => !isSet(env[variableFor(key)])).map((key) => ({
    variable: variableFor(key),
    reason: 'unset-or-empty'
  }));
  const connectSrc = env[CONNECT_SRC_VARIABLE];
  if (!isSet(connectSrc)) {
    problems.push({variable: CONNECT_SRC_VARIABLE, reason: 'unset-or-empty'});
  } else if (!SOURCE_LIST.test(connectSrc)) {
    problems.push({variable: CONNECT_SRC_VARIABLE, reason: 'invalid-characters'});
  }
  problems.push(...sessionProblems(env));
  return problems;
}

/**
 * The validated `connect-src` source list, read at request time.
 *
 * @param env - The environment to read; the process's own by default.
 * @returns The source list, or `'self'` when it is unusable. The start-time check stops a server
 *   with an unusable value before it answers anything, so the fallback is reached only by a
 *   process that skipped that check, and it fails closed.
 */
export function connectSource(env: NodeJS.ProcessEnv = process.env): string {
  const value = env[CONNECT_SRC_VARIABLE];
  return isSet(value) && SOURCE_LIST.test(value) ? value : "'self'";
}

/** How each reason reads on stderr, after the variable's name. */
const REASON_TEXT: Record<StartupProblem['reason'], string> = {
  'unset-or-empty': 'unset or empty',
  'invalid-characters': 'not a valid CSP source list',
  unusable:
    'not usable (a credential URL must be HTTPS, or HTTP to a loopback host, and the session ceiling a whole number of seconds)'
};

/**
 * Stop the process when any startup problem exists, naming each variable on stderr.
 *
 * It exits rather than throws. A throw from the instrumentation hook was measured to leave the
 * server up and answering 500 to every path, which a load balancer probes as an unhealthy target
 * for ever instead of seeing a task that stopped.
 *
 * @param env - The environment to read; the process's own by default.
 * @param exit - What stops the process; injectable so the refusal can be tested.
 * @returns Nothing; it does not return when there is a problem.
 */
export function refuseToStartWithoutConfiguration(
  env: NodeJS.ProcessEnv = process.env,
  exit: (code: number) => never = process.exit
): void {
  const problems = startupProblems(env);
  if (problems.length === 0) return;
  for (const {variable, reason} of problems) {
    console.error(`portal: refusing to start. ${variable} is ${REASON_TEXT[reason]}.`);
  }
  exit(1);
}
