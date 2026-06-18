import { describe, it, expect } from 'vitest';
import {
  formatBytes,
  formatDurationMs,
  formatRelativeTime,
} from './query.format';

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

describe('formatRelativeTime', () => {
  const now = new Date('2026-06-18T12:00:00.000Z').getTime();
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it('formats coarse relative times against a pinned now', () => {
    expect(formatRelativeTime(ago(2_000), now)).toBe('just now');
    expect(formatRelativeTime(ago(120_000), now)).toBe('2 min ago');
    expect(formatRelativeTime(ago(2 * 3_600_000), now)).toBe('2 hr ago');
    expect(formatRelativeTime(ago(26 * 3_600_000), now)).toBe('Yesterday');
  });

  it('returns empty string for an invalid date', () => {
    expect(formatRelativeTime('not-a-date', now)).toBe('');
  });
});
