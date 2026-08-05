import {describe, expect, it} from 'vitest';
import {parseTableLocation} from './tableRefresh.location';

describe('parseTableLocation', () => {
  it('splits an s3 location into bucket and prefix', () => {
    expect(parseTableLocation('s3://user-space/alice/sales/')).toEqual({bucket: 'user-space', prefix: 'alice/sales/'});
  });

  it('normalises a missing trailing slash', () => {
    expect(parseTableLocation('s3://user-space/alice/sales')).toEqual({bucket: 'user-space', prefix: 'alice/sales/'});
  });

  it('keeps a shared-space location intact (the rail shows shared tables too)', () => {
    expect(parseTableLocation('s3://shared-space/salesteam/2026/q1/')).toEqual({
      bucket: 'shared-space',
      prefix: 'salesteam/2026/q1/'
    });
  });

  it('trims surrounding whitespace', () => {
    expect(parseTableLocation('  s3://user-space/alice/sales/  ')).toEqual({
      bucket: 'user-space',
      prefix: 'alice/sales/'
    });
  });

  it.each([
    ['undefined', undefined],
    ['empty', ''],
    ['a bucket with no key', 's3://user-space'],
    ['a bucket with an empty key', 's3://user-space/'],
    ['another scheme', 'https://user-space.s3.amazonaws.com/alice/'],
    ['a bare path', '/alice/sales/']
  ])('returns null for %s', (_label, value) => {
    expect(parseTableLocation(value)).toBeNull();
  });
});
