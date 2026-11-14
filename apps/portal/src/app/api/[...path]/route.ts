import {api, route} from '../../../server/session/handlers';

/** Rendered per request, never at build time. */
export const dynamic = 'force-dynamic';

/** The API's same-origin pass-through, one handler for every method it forwards. */
const handler = route(api);

export {handler as GET, handler as HEAD, handler as POST, handler as PUT, handler as PATCH, handler as DELETE};
