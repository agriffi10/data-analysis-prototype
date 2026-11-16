'use strict';

/**
 * The image's entry point: a guard ahead of Next's standalone server for the requests Next answers
 * with a bare 500, or answers off-site, before any of its own handling runs.
 *
 * A path whose percent-escape does not decode (`/%ZZ`, `/files%`, `/%E0`) makes Next's router throw,
 * and an App Router build has no pages `_error` to render the 400 Next means, so every page, route
 * handler and the not-found page answered 500 with no security headers and logged nothing. A request
 * target that is not a path (`http://elsewhere/files`, `javascript://…`, `*`) is redirected by Next to
 * the URL it names, in the client's own scheme. Both are answered here instead: 400, every security
 * header, the lockdown policy, a plain body, and one log line naming the method, never the target,
 * which is the caller's text. Nothing reads a body, so a request carrying one is answered at once.
 *
 * Every WebSocket upgrade is refused too. The portal serves none, and Next leaves an upgrade to a path
 * it would redirect (`/files/`) open with no answer at all, a socket held until the client gives up.
 *
 * Run as the entry point, it replaces `http.createServer` so the server Next's standalone build
 * creates answers through it, then starts that server; imported, it only exports its parts. It is
 * plain JavaScript outside the build, and the image carries no `src/`, so it keeps its own copy of
 * the headers, which `src/server/serverGuard.test.ts` holds equal to `src/lib/securityHeaders.ts`.
 */

const http = require('node:http');

/** The response headers every portal response carries, as `src/lib/securityHeaders.ts` states them. */
const SECURITY_HEADERS = Object.freeze({
  'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
  'X-Frame-Options': 'DENY',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy':
    'accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()',
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Resource-Policy': 'same-origin'
});

/** The policy for a response that runs nothing, as `src/lib/securityHeaders.ts` states it. */
const LOCKDOWN_POLICY = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

/** What each refusal is, as its log line says it. */
const REASONS = Object.freeze({
  'malformed-escape': 'a path with a malformed percent-escape',
  'not-a-path': 'a request target that is not a path',
  upgrade: 'a WebSocket upgrade'
});

const BODY = 'Bad request\n';

/**
 * Why a request target is refused, or null when it passes to Next.
 *
 * The path is the target up to its first `?` or `#`, so an escape in the query, which no router
 * decodes, passes; each `/`-separated segment must decode as UTF-8.
 *
 * @param {string | undefined} target - The request target as the request line carries it.
 * @returns {'malformed-escape' | 'not-a-path' | null} The reason, or null.
 */
function refusal(target) {
  if (typeof target !== 'string' || !target.startsWith('/')) return 'not-a-path';
  const end = target.search(/[?#]/);
  const path = end < 0 ? target : target.slice(0, end);
  for (const segment of path.split('/')) {
    try {
      decodeURIComponent(segment);
    } catch {
      return 'malformed-escape';
    }
  }
  return null;
}

/**
 * The refusal's headers: every security header, the lockdown policy, and a closed connection.
 *
 * @returns {Record<string, string | number>} The headers.
 */
function refusalHeaders() {
  return {
    ...SECURITY_HEADERS,
    'Content-Security-Policy': LOCKDOWN_POLICY,
    'Content-Type': 'text/plain; charset=utf-8',
    'Content-Length': Buffer.byteLength(BODY),
    'Cache-Control': 'no-store',
    Connection: 'close'
  };
}

/**
 * Writes the log line for a refusal: the reason and the method, never the target.
 *
 * @param {keyof typeof REASONS} reason - Why the request was refused.
 * @param {string | undefined} method - The request's method, which the HTTP parser has validated.
 * @returns {void}
 */
function log(reason, method) {
  console.error(`request: refused ${REASONS[reason]} (${method ?? 'unknown'})`);
}

/**
 * Answers a refused request: 400 with the refusal's headers and a plain body.
 *
 * @param {import('node:http').IncomingMessage} req - The request, whose body is never read.
 * @param {import('node:http').ServerResponse} res - Its response.
 * @param {keyof typeof REASONS} reason - Why it is refused.
 * @returns {void}
 */
function refuse(req, res, reason) {
  res.writeHead(400, refusalHeaders());
  res.end(BODY);
  log(reason, req.method);
}

/**
 * Answers a WebSocket upgrade on its raw socket: the same 400, then the socket is ended.
 *
 * @param {import('node:http').IncomingMessage} req - The upgrade request.
 * @param {import('node:stream').Duplex} socket - Its socket, which no one else has written to.
 * @returns {void}
 */
function refuseUpgrade(req, socket) {
  socket.on('error', () => socket.destroy());
  const head = Object.entries(refusalHeaders())
    .map(([name, value]) => `${name}: ${value}\r\n`)
    .join('');
  socket.end(`HTTP/1.1 400 Bad Request\r\n${head}\r\n${BODY}`);
  log('upgrade', req.method);
}

/**
 * Puts the guard in front of every server `http.createServer` makes from here on: a request it
 * refuses is answered before any listener sees it, and an upgrade never reaches one.
 *
 * @returns {void}
 */
function install() {
  const createServer = http.createServer;
  http.createServer = function guardedCreateServer(...args) {
    const server = createServer.apply(this, args);
    const emit = server.emit;
    server.emit = function guardedEmit(event, ...rest) {
      if (event === 'upgrade') {
        refuseUpgrade(rest[0], rest[1]);
        return true;
      }
      if (event === 'request') {
        const reason = refusal(rest[0].url);
        if (reason) {
          refuse(rest[0], rest[1], reason);
          return true;
        }
      }
      return emit.call(this, event, ...rest);
    };
    return server;
  };
}

module.exports = {SECURITY_HEADERS, LOCKDOWN_POLICY, install, refusal, refuse, refuseUpgrade};

if (require.main === module) {
  install();
  require('./server.js');
}
