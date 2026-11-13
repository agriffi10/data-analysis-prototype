/** Answered per request, so the probe reaches a running server rather than a build artifact. */
export const dynamic = 'force-dynamic';

/**
 * The load balancer's health probe.
 *
 * Its body and type are what a check can tell apart from the catch-all, which answers any unknown
 * path with the app shell under a 200; a probe matching only the status would read a server that
 * lost this route as healthy.
 *
 * @returns `ok` as plain text.
 */
export function GET(): Response {
  return new Response('ok', {headers: {'Content-Type': 'text/plain', 'Cache-Control': 'no-store'}});
}
