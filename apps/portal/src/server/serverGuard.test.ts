import http, {type IncomingMessage, type ServerResponse} from 'node:http';
import type {Duplex} from 'node:stream';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {LOCKDOWN_POLICY, SECURITY_HEADERS} from '../lib/securityHeaders';
import * as guard from '../../server-guard.cjs';

/** `http.createServer` as it stood before anything here installed the guard. */
const ORIGINAL_CREATE_SERVER = http.createServer;

afterEach(() => {
  http.createServer = ORIGINAL_CREATE_SERVER;
  vi.restoreAllMocks();
});

/** A response that records what was written to it. */
function recordingResponse() {
  const written: {status?: number; headers?: Record<string, string | number>; body?: string} = {};
  const res = {
    writeHead: (status: number, headers: Record<string, string | number>) => Object.assign(written, {status, headers}),
    end: (body: string) => Object.assign(written, {body})
  } as unknown as ServerResponse;
  return {res, written};
}

const request = (method: string, url: string) => ({method, url}) as IncomingMessage;

describe('the guard’s check', () => {
  it.each([
    '/',
    '/files',
    '/data-quality/a%40b/r1',
    '/files/a%2Fb',
    '/%2e',
    '/query?x=%E0',
    '/files#%E0',
    '/files?x=%zz#%E0'
  ])('passes %s to Next', (target) => {
    expect(guard.refusal(target)).toBeNull();
  });

  it.each([
    '/%ZZ',
    '/%zz',
    '/files%',
    '/%E0',
    '/nope/%E0%A4',
    '/_next/%E0',
    '/_next/static/%E0',
    '/data-quality/%E0/r1'
  ])('refuses %s as a malformed escape', (target) => {
    expect(guard.refusal(target)).toBe('malformed-escape');
  });

  // Next redirects such a target to the URL it names, in the client's scheme and host.
  it.each(['http://elsewhere.test/files', 'javascript://elsewhere.test/%0aalert(1)', '*', 'files', '', undefined])(
    'refuses %j as a target that is not a path',
    (target) => {
      expect(guard.refusal(target)).toBe('not-a-path');
    }
  );
});

describe('the guard’s refusal', () => {
  it('carries the security headers as securityHeaders.ts states them, and the lockdown policy', () => {
    const {res, written} = recordingResponse();
    vi.spyOn(console, 'error').mockImplementation(() => {});

    guard.refuse(request('POST', '/data-quality/%E0/r1'), res, 'malformed-escape');

    expect(guard.SECURITY_HEADERS).toEqual(SECURITY_HEADERS);
    expect(guard.LOCKDOWN_POLICY).toBe(LOCKDOWN_POLICY);
    expect(written.status).toBe(400);
    expect(written.headers).toMatchObject({
      ...SECURITY_HEADERS,
      'Content-Security-Policy': LOCKDOWN_POLICY,
      'Content-Type': 'text/plain; charset=utf-8',
      Connection: 'close'
    });
    expect(written.body).toBe('Bad request\n');
  });

  // The target is the caller's text, so the line names the method and nothing of the path.
  it('logs one line naming the method and no part of the path', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});

    guard.refuse(request('POST', '/secret-name/%E0'), recordingResponse().res, 'malformed-escape');

    expect(error.mock.calls).toEqual([['request: refused a path with a malformed percent-escape (POST)']]);
    expect(String(error.mock.calls[0][0])).not.toMatch(/secret-name|%E0/);
  });
});

describe('the guard in front of a server', () => {
  it('starts no server and replaces nothing when imported', () => {
    expect(http.createServer).toBe(ORIGINAL_CREATE_SERVER);
  });

  it('answers a refused request and every upgrade itself, and passes the rest to the listener', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const listener = vi.fn();
    guard.install();
    const server = http.createServer(listener);

    const refused = recordingResponse();
    server.emit('request', request('GET', '/%E0'), refused.res);
    const passed = recordingResponse();
    server.emit('request', request('GET', '/files'), passed.res);
    const socket = {on: vi.fn(), end: vi.fn()};
    server.emit('upgrade', request('GET', '/files/'), socket as unknown as Duplex, Buffer.alloc(0));

    expect(refused.written.status).toBe(400);
    expect(listener.mock.calls.map(([req]) => (req as IncomingMessage).url)).toEqual(['/files']);
    expect(String(socket.end.mock.calls[0][0])).toMatch(/^HTTP\/1\.1 400 Bad Request\r\n[\s\S]*Connection: close\r\n/);
    expect(String(socket.end.mock.calls[0][0])).toContain(`Content-Security-Policy: ${LOCKDOWN_POLICY}\r\n`);
    server.close();
  });
});
