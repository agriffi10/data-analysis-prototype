import {describe, it, expect} from 'vitest';
import {formatPageTitle} from './formatPageTitle';

describe('formatPageTitle', () => {
  it('appends the app name with an em-dash when a page is given', () => {
    expect(formatPageTitle('Files')).toBe('Files — Data Workspace');
    expect(formatPageTitle('Not Found')).toBe('Not Found — Data Workspace');
  });

  it('returns just the app name for empty or omitted page', () => {
    expect(formatPageTitle('')).toBe('Data Workspace');
    expect(formatPageTitle()).toBe('Data Workspace');
  });
});
