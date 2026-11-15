import {describe, expect, it} from 'vitest';
import {TIMEOUT_MS} from '../../lib/apiClient';
import {FORWARD_TIMEOUT_MS} from './forward';
import {TOKEN_ENDPOINT_TIMEOUT_MS} from './oidc';
import {STORE_CALL_TIMEOUT_MS} from './store';

describe("the browser's timeout", () => {
  it("outlasts the /api/ route's worst path, so the server always gives up first", () => {
    // Before it forwards, the route may read the session, lose a refresh's compare-and-set write and
    // read it again, and call the token endpoint once; then it waits for the API. A browser that gave
    // up sooner would report as timed out a write the server then completed.
    const worstPath = 3 * STORE_CALL_TIMEOUT_MS + TOKEN_ENDPOINT_TIMEOUT_MS + FORWARD_TIMEOUT_MS;

    expect(TIMEOUT_MS).toBeGreaterThan(worstPath);
  });
});
