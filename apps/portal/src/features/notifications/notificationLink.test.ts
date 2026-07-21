import {describe, it, expect} from 'vitest';
import {isSafeInAppPath} from './notificationLink';

describe('isSafeInAppPath', () => {
  it('accepts an in-app absolute path', () => {
    expect(isSafeInAppPath('/data-quality/alice/req-1')).toBe(true);
    expect(isSafeInAppPath('/files?space=personal&prefix=alice%2Fsales%2F')).toBe(true);
    expect(isSafeInAppPath('/')).toBe(true);
  });

  it('rejects anything that could resolve off this origin', () => {
    // A notification's link is written by a Lambda and read back from S3, then turned
    // into an anchor. Every case below would be an open redirect wearing the app's own
    // chrome, and the last two are the ones a naive `startsWith('//')` check misses.
    expect(isSafeInAppPath('https://evil.test/phish')).toBe(false);
    expect(isSafeInAppPath('http://evil.test')).toBe(false);
    expect(isSafeInAppPath('javascript:alert(1)')).toBe(false);
    expect(isSafeInAppPath('data:text/html,<script>')).toBe(false);
    expect(isSafeInAppPath('//evil.test/phish')).toBe(false); // protocol-relative
    expect(isSafeInAppPath('/\\evil.test/phish')).toBe(false); // backslash authority
    expect(isSafeInAppPath('/\\\\evil.test')).toBe(false);
  });

  it('rejects a relative path, which resolves against whatever route the user is on', () => {
    expect(isSafeInAppPath('data-quality/alice/req-1')).toBe(false);
    expect(isSafeInAppPath('./somewhere')).toBe(false);
    expect(isSafeInAppPath('../somewhere')).toBe(false);
  });

  it('rejects absent and non-string values', () => {
    expect(isSafeInAppPath(undefined)).toBe(false);
    expect(isSafeInAppPath(null)).toBe(false);
    expect(isSafeInAppPath('')).toBe(false);
    expect(isSafeInAppPath(42)).toBe(false);
    expect(isSafeInAppPath({toString: () => '/safe'})).toBe(false);
  });
});
