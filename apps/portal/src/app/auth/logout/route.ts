import {logout, route} from '../../../server/session/handlers';

/** Rendered per request, never at build time. */
export const dynamic = 'force-dynamic';

/** `POST /auth/logout`: end the session and answer the provider's logout URL. */
export const POST = route(logout);
