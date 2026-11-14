import 'server-only';
import type {ApiErrorCode} from '../../types/apiContract.generated';

/**
 * The refusal codes the server mints. A subset of the API contract's codes, so the browser maps each
 * to the wording it already shows and the compiler refuses one the contract does not declare.
 */
export type RefusalCode = Extract<
  ApiErrorCode,
  'SessionExpired' | 'AccessDenied' | 'NotFound' | 'PayloadTooLarge' | 'ApiUnavailable'
>;

const STATUS: Record<RefusalCode, number> = {
  SessionExpired: 401,
  AccessDenied: 403,
  NotFound: 404,
  PayloadTooLarge: 413,
  ApiUnavailable: 503
};

/**
 * A refusal in the API's own failure envelope, so a browser cannot tell the server's from the API's.
 *
 * The body is written with the separators Python's `json.dumps` uses, which is how the API renders
 * it, and a 401 carries the same challenge header. The request id is the caller's own when it sent
 * one, so a reported failure is findable either side.
 *
 * @param code - The contract code.
 * @param requestId - The id to echo.
 * @returns The response.
 */
export function refusal(code: RefusalCode, requestId: string = crypto.randomUUID()): Response {
  const body = `{"error": {"code": ${JSON.stringify(code)}, "requestId": ${JSON.stringify(requestId)}}}`;
  const headers = new Headers({'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store'});
  if (code === 'SessionExpired') headers.set('www-authenticate', 'Bearer');
  return new Response(body, {status: STATUS[code], headers});
}
