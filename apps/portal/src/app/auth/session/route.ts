import {session, route} from '../../../server/session/handlers';

/** Rendered per request, never at build time. */
export const dynamic = 'force-dynamic';

/** `GET /auth/session`: the signed-in user, or 401. */
export const GET = route(session);
