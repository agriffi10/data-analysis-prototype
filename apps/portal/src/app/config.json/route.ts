import {renderRuntimeDocument} from '../../server/runtimeDocument';

/** Rendered per request from the server's environment, never at build time. */
export const dynamic = 'force-dynamic';

/**
 * The runtime configuration document the browser loads before it renders anything.
 *
 * `no-store`, because a document answered from a cache populated in another environment renders a
 * working portal pointed at the wrong account, and nothing on screen distinguishes it.
 *
 * @returns The document as JSON.
 */
export function GET(): Response {
  return Response.json(renderRuntimeDocument(), {headers: {'Cache-Control': 'no-store'}});
}
