import {describe, expect, it} from 'vitest';

import {isSafeInAppPath} from './notificationLink';

/**
 * The browser's half of a two-language assertion.
 *
 * `rccommon/links.py` mints the link a results-conversion notification carries, and the Python
 * suite asserts the exact string it produces. That proves the producer is consistent with
 * itself; it cannot prove the link resolves, because a Python test asserting on `URLSearchParams`
 * would be asserting my model of the parser rather than the parser.
 *
 * So the same golden string is written out on both sides — deliberately duplicated rather than
 * shared through a fixture file, since a shared file both halves read would go stale together —
 * and this half runs it through the parser the SPA actually uses. The Python copy lives beside
 * `GOLDEN_LINK` in `lambdas/results-conversion-common/test_plane_results_conversion.py`; change
 * one and this fails.
 */
const GOLDEN_LINK = '/files?space=finance&prefix=finance/a%20b%26c%3Fd%23e/';

describe('a results-conversion notification link', () => {
  it('is a path the notification row will render rather than degrade to plain text', () => {
    expect(isSafeInAppPath(GOLDEN_LINK)).toBe(true);
  });

  it('round-trips through the browser parser to the folder the file landed in', () => {
    const [path, query] = GOLDEN_LINK.split('?');
    const params = new URLSearchParams(query);

    expect(path).toBe('/files');
    expect(params.get('space')).toBe('finance');
    // The `&`, `?`, `#` and the space survive as data. Unencoded, the `&` would end the prefix
    // parameter and the `?`/`#` would truncate the link into one resolving somewhere else.
    expect(params.get('prefix')).toBe('finance/a b&c?d#e/');
    expect([...params.keys()]).toEqual(['space', 'prefix']);
  });

  it('would truncate if the producer stopped encoding, which is what the encoding is for', () => {
    const unencoded = '/files?space=finance&prefix=finance/a b&c?d#e/';
    const params = new URLSearchParams(unencoded.split('?')[1]);

    expect(params.get('prefix')).not.toBe('finance/a b&c?d#e/');
    expect(params.get('prefix')).toBe('finance/a b');
  });
});
