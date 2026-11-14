import {refresh, route} from '../../../server/session/handlers';

/** Rendered per request, never at build time. */
export const dynamic = 'force-dynamic';

/** `POST /auth/refresh`: refresh the session's token now. */
export const POST = route(refresh);
