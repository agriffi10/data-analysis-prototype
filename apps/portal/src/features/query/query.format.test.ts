import { describe, it, expect } from 'vitest';
import { formatBytes, formatDurationMs } from './query.format';

describe('formatBytes', () => {
  it('formats byte sizes with sensible units + precision', () => {
    expect(formatBytes(undefined)).toBe('—');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(1_258_291)).toBe('1.2 MB');
    expect(formatBytes(53_687_091)).toBe('51 MB'); // ≥10 drops the decimal
  });
});

describe('formatDurationMs', () => {
  it('formats sub-second as ms and longer as seconds', () => {
    expect(formatDurationMs(undefined)).toBe('—');
    expect(formatDurationMs(800)).toBe('800 ms');
    expect(formatDurationMs(1234)).toBe('1.2s');
  });
});
