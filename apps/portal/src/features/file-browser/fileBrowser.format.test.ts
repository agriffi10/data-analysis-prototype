import { describe, it, expect } from 'vitest';
import { formatSize } from './fileBrowser.format';

describe('formatSize', () => {
  it('formats across the byte boundaries', () => {
    expect(formatSize(0)).toBe('0 B');
    expect(formatSize(512)).toBe('512 B');
    expect(formatSize(1024)).toBe('1.0 KB');
    expect(formatSize(1_572_864)).toBe('1.5 MB');
    expect(formatSize(1_610_612_736)).toBe('1.5 GB');
  });
});
