import {describe, it, expect} from 'vitest';
import {locationLabel} from './dataQuality.format';

describe('locationLabel', () => {
  it('names a folder by its own segment and a file by its basename', () => {
    expect(locationLabel('alice/data/sales/')).toBe('sales');
    expect(locationLabel('alice/data/sales.csv')).toBe('sales.csv');
    expect(locationLabel('sales.csv')).toBe('sales.csv');
  });

  it('never returns a blank label', () => {
    // A space root, or a degenerate key — the caller puts this in a sentence.
    expect(locationLabel('/')).toBe('/');
    expect(locationLabel('')).toBe('');
  });
});
