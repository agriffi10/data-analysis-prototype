import {describe, it, expect} from 'vitest';
import {formatAbsoluteDate, formatCount, formatDurationMs, formatRelativeTime} from './format';

const NOW = Date.parse('2026-03-10T12:00:00Z');
const ago = (ms: number) => new Date(NOW - ms).toISOString();

describe('formatCount', () => {
  it('adds thousands separators', () => {
    expect(formatCount(1384)).toBe('1,384');
    expect(formatCount(0)).toBe('0');
  });
});

describe('formatDurationMs', () => {
  it('shows milliseconds below a second and seconds above', () => {
    expect(formatDurationMs(800)).toBe('800 ms');
    expect(formatDurationMs(1234)).toBe('1.2s');
  });

  it('renders an em dash for undefined', () => {
    expect(formatDurationMs(undefined)).toBe('—');
  });
});

describe('formatAbsoluteDate', () => {
  it('renders the one short-date shape three call sites had written out', () => {
    expect(formatAbsoluteDate('2026-03-03T09:30:00Z')).toBe('Mar 3, 2026');
  });

  it('accepts a Date as well as an ISO string', () => {
    expect(formatAbsoluteDate(new Date('2026-03-03T09:30:00Z'))).toBe('Mar 3, 2026');
  });

  it('yields an empty string for an unparseable value rather than "Invalid Date"', () => {
    expect(formatAbsoluteDate('not a date')).toBe('');
    expect(formatAbsoluteDate(new Date('nope'))).toBe('');
  });
});

describe('formatRelativeTime', () => {
  it.each([
    [2_000, 'just now'],
    [30_000, '30 sec ago'],
    [10 * 60_000, '10 min ago'],
    [5 * 3_600_000, '5 hr ago'],
    [26 * 3_600_000, 'Yesterday'],
    [3 * 86_400_000, '3 days ago']
  ])('renders %d ms ago as %s', (elapsed, expected) => {
    expect(formatRelativeTime(ago(elapsed), NOW)).toBe(expected);
  });

  it('falls back to the shared absolute date beyond a week', () => {
    // The collapse of the third date formatter: this used to be locale-dependent
    // (`toLocaleDateString()` with no options) while its two siblings pinned en-US.
    expect(formatRelativeTime('2026-01-15T09:30:00Z', NOW)).toBe('Jan 15, 2026');
  });

  it('returns an empty string for an unparseable timestamp', () => {
    expect(formatRelativeTime('not a date', NOW)).toBe('');
  });
});
