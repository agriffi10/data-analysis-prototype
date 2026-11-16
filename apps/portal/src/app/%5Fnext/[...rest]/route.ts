/** Answered per request; nothing here is built ahead of one. */
export const dynamic = 'force-dynamic';

/**
 * An honest 404 for a `/_next/` path that matched no built file.
 *
 * Next answers a missing file under `/_next/static/` with a plain 404 itself; without this handler
 * any other `/_next/` path would get the not-found page's HTML, which a module script then fails to
 * parse with no way to tell "removed" from "never existed". Next serves every file that does exist
 * before routing reaches here.
 *
 * @returns A plain-text 404.
 */
function notFound(): Response {
  return new Response('not found\n', {
    status: 404,
    headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}
  });
}

export const GET = notFound;
export const HEAD = notFound;
