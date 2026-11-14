import {login, route} from '../../../server/session/handlers';

/** Rendered per request, never at build time. */
export const dynamic = 'force-dynamic';

/** `GET /auth/login`: start a sign-in through the provider. */
export const GET = route(login);
