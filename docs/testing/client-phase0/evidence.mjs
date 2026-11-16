/**
 * The Node half of the Phase 0 evidence log: one JSON line per observation, written and synced the
 * moment it is seen, and a secrets directory for the tokens the Python half reads back.
 *
 * Both halves append to the same file (`PHASE0_EVIDENCE`), so the record shape here matches
 * `Evidence.record` in `phase0.py`. Nothing secret is ever written to the log: tokens are reduced to
 * a length and a hash prefix, and a last check refuses any line that still holds a JWT or a value
 * registered as secret.
 */
import { createHash } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, writeSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const JWT_SHAPE = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/;

/**
 * Reduce a secret to something that can be compared across records but not replayed.
 * @param {string | undefined | null} value The secret, or nothing.
 * @returns {{len: number, sha256_12: string} | null} Its length and the first 12 hex characters of its SHA-256.
 */
export function fingerprint(value) {
  if (value === undefined || value === null) return null;
  return { len: value.length, sha256_12: createHash('sha256').update(value).digest('hex').slice(0, 12) };
}

/**
 * Decode a JWT's payload without verifying it; the scripts only read claims they already trust.
 * @param {string} token A compact JWT.
 * @returns {Record<string, unknown>} The payload's claims.
 */
export function decodeJwt(token) {
  const part = token.split('.')[1];
  if (!part) throw new Error('not a JWT: no payload segment');
  return JSON.parse(Buffer.from(part, 'base64url').toString('utf8'));
}

/** Claims whose values are themselves bearer material and never reach the log. */
const SECRET_CLAIMS = new Set(['sts:identity_context', 'sts:audit_context']);
/** Claims that are unique per token: logged as a fingerprint so replay and rotation stay visible. */
const FINGERPRINT_CLAIMS = new Set(['jti', 'origin_jti', 'at_hash', 'nonce']);

/**
 * The claims of a token that are safe to log, with bearer-material claims fingerprinted.
 * @param {Record<string, unknown>} claims A decoded payload.
 * @returns {Record<string, unknown>} A copy fit for the evidence log.
 */
export function loggableClaims(claims) {
  const out = {};
  for (const [key, value] of Object.entries(claims)) {
    if (SECRET_CLAIMS.has(key) || FINGERPRINT_CLAIMS.has(key)) out[key] = fingerprint(String(value));
    else out[key] = value;
  }
  return out;
}

/**
 * Refuse a path inside a git checkout, so neither tokens nor evidence can be committed by accident.
 * @param {string} path A file or directory path.
 * @returns {void}
 * @throws {Error} When any ancestor of the path holds a `.git` entry.
 */
export function refuseInsideCheckout(path) {
  let dir = resolve(path);
  for (;;) {
    if (existsSync(join(dir, '.git'))) {
      throw new Error(`${path} is inside the git checkout at ${dir}; keep evidence and tokens outside any repository`);
    }
    const parent = dirname(dir);
    if (parent === dir) return;
    dir = parent;
  }
}

/**
 * Read a required environment variable.
 * @param {string} name The variable.
 * @returns {string} Its value.
 * @throws {Error} When it is unset or empty.
 */
export function requireEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set; source your copy of config.example.env first`);
  return value;
}

/** Appends observations to the shared evidence file. */
export class Evidence {
  /**
   * @param {string} path The JSON-lines evidence file.
   * @param {string[]} [secrets] Values that must never appear in any line.
   */
  constructor(path, secrets = []) {
    refuseInsideCheckout(path);
    mkdirSync(dirname(resolve(path)), { recursive: true });
    this.path = path;
    this.secrets = secrets.filter((s) => typeof s === 'string' && s.length >= 8);
  }

  /**
   * Register more values that must never be written.
   * @param {...(string | undefined)} values Secrets seen since construction.
   * @returns {void}
   */
  addSecrets(...values) {
    for (const v of values) if (typeof v === 'string' && v.length >= 8) this.secrets.push(v);
  }

  /**
   * Write one observation and sync it to disk before returning.
   * @param {string} label The runbook label the observation answers, such as `C1.exchange`.
   * @param {{ok: boolean, code?: string, message?: string, data?: Record<string, unknown>}} outcome What was seen.
   * @returns {Record<string, unknown>} The record as written.
   * @throws {Error} When the line would carry a JWT or a registered secret; nothing is written then.
   */
  record(label, outcome) {
    const entry = { ts: new Date().toISOString(), label, source: 'node', ...outcome };
    const line = JSON.stringify(entry);
    if (JWT_SHAPE.test(line)) throw new Error(`refused to log ${label}: the record holds a JWT`);
    for (const s of this.secrets) {
      if (line.includes(s)) throw new Error(`refused to log ${label}: the record holds a registered secret`);
    }
    const fd = openSync(this.path, 'a', 0o600);
    try {
      writeSync(fd, `${line}\n`);
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    const shown = outcome.ok ? 'ok' : `${outcome.code}: ${outcome.message}`;
    process.stdout.write(`[${label}] ${shown}\n`);
    return entry;
  }
}

/**
 * The secrets directory, created private, and refused inside a checkout.
 * @returns {string} Its path.
 */
export function secretsDir() {
  const dir = requireEnv('PHASE0_SECRETS');
  refuseInsideCheckout(dir);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

/**
 * Read a token file the other scripts wrote.
 * @param {string} name The file name inside the secrets directory.
 * @returns {Record<string, string>} Its contents.
 */
export function readSecret(name) {
  return JSON.parse(readFileSync(join(secretsDir(), name), 'utf8'));
}

/**
 * Write a token file readable only by its owner.
 * @param {string} name The file name inside the secrets directory.
 * @param {Record<string, unknown>} body What to keep.
 * @returns {void}
 */
export function writeSecret(name, body) {
  const fd = openSync(join(secretsDir(), name), 'w', 0o600);
  try {
    writeSync(fd, JSON.stringify(body));
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

/**
 * Reduce an SDK or fetch error to the fields the verdicts read: the service's own error code, or a
 * `Local:` code when the failure never reached AWS, so a verdict can tell a refusal from a broken run.
 * SSO-OIDC puts its reason in `error_description` and leaves `message` as `UnknownError`, so the
 * description is read first.
 * @param {unknown} err What was thrown.
 * @returns {{ok: false, code: string, message: string, data: Record<string, unknown>}} The outcome.
 */
export function errorOutcome(err) {
  const e = /** @type {{name?: string, message?: string, $metadata?: {httpStatusCode?: number}, error?: string, error_description?: string}} */ (err ?? {});
  const status = e.$metadata?.httpStatusCode;
  if (status !== undefined) {
    const message = e.error_description || (e.message && e.message !== 'UnknownError' ? e.message : '') || e.error || '';
    return { ok: false, code: e.name ?? 'Unknown', message, data: { httpStatus: status, oauthError: e.error ?? null } };
  }
  return { ok: false, code: `Local:${e.name ?? 'Error'}`, message: e.message ?? String(err), data: {} };
}
