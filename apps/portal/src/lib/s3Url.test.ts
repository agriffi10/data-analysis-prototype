import {describe, it, expect} from 'vitest';
import {parseS3Url} from './s3Url';

describe('parseS3Url', () => {
  it('splits an s3:// URL into bucket and key', () => {
    expect(parseS3Url('s3://user-bucket/alice/athenaresults/q-1.csv')).toEqual({
      bucket: 'user-bucket',
      key: 'alice/athenaresults/q-1.csv'
    });
  });

  it('keeps a trailing slash in the key — normalising is the caller`s job', () => {
    // `parseTableLocation` adds one; the Save-results flow must not have one added.
    expect(parseS3Url('s3://shared-space/salesteam/2026/q1/')).toEqual({
      bucket: 'shared-space',
      key: 'salesteam/2026/q1/'
    });
  });

  it('trims surrounding whitespace — a catalog LOCATION can carry it', () => {
    expect(parseS3Url('  s3://user-space/alice/sales/  ')).toEqual({
      bucket: 'user-space',
      key: 'alice/sales/'
    });
  });

  it.each([
    ['not-an-s3-url'],
    ['https://user-bucket.s3.amazonaws.com/alice/f.csv'],
    ['s3://bucket-only'],
    ['s3://bucket-only/'],
    ['s3://'],
    ['']
  ])('returns null for %s', (value) => {
    expect(parseS3Url(value)).toBeNull();
  });

  it('returns null for undefined rather than throwing', () => {
    expect(parseS3Url(undefined)).toBeNull();
  });
});
