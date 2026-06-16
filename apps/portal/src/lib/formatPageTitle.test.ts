import { describe, it, expect } from 'vitest';
import { formatPageTitle } from './formatPageTitle';

describe('formatPageTitle', () => {
  it('appends the app name with an em-dash when a page is given', () => {
    expect(formatPageTitle('Files')).toBe('Files — S3 File Portal');
    expect(formatPageTitle('Not Found')).toBe('Not Found — S3 File Portal');
  });

  it('returns just the app name for empty or omitted page', () => {
    expect(formatPageTitle('')).toBe('S3 File Portal');
    expect(formatPageTitle()).toBe('S3 File Portal');
  });
});
