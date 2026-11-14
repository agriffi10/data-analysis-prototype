import {callback, route} from '../../../server/session/handlers';

/** Rendered per request, never at build time. */
export const dynamic = 'force-dynamic';

/** `GET /auth/callback`: the provider returns here with a code. */
export const GET = route(callback);
