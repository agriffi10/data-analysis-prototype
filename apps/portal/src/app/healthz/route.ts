/** Answered per request, so the probe reaches a running server rather than a build artifact. */
export const dynamic = 'force-dynamic';

/**
 * The load balancer's health probe.
 *
 * Its body and type are what a check can tell apart from any page; a probe matching only the status
 * would read a server answering it with some other 200 as healthy.
 *
 * @returns `ok` as plain text.
 */
export function GET(): Response {
  return new Response('ok', {headers: {'Content-Type': 'text/plain', 'Cache-Control': 'no-store'}});
}
