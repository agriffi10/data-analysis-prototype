import {describe, it, expect} from 'vitest';
import {formatSize} from './fileBrowser.format';

describe('formatSize — the SPEC-155 FR-007 ceiling', () => {
  it('formats across the byte boundaries', () => {
    expect(formatSize(0)).toBe('0 B');
    expect(formatSize(512)).toBe('512 B');
    expect(formatSize(1024)).toBe('1.0 KB');
    expect(formatSize(1_572_864)).toBe('1.5 MB');
    expect(formatSize(1_610_612_736)).toBe('1.5 GB');
  });
});

describe('formatSize reaches TB (SPEC-155 FR-007)', () => {
  it('renders a multi-terabyte object as TB, not thousands of GB', () => {
    // It used to stop at GB, so this read "3072.0 GB" here and "3.0 TB" in the query
    // status bar. S3 allows objects up to 5 TB, so the ceiling was reachable.
    expect(formatSize(3 * 1_099_511_627_776)).toBe('3.0 TB');
    expect(formatSize(1_099_511_627_776)).toBe('1.0 TB');
  });

  it('still shows GB just below the boundary', () => {
    expect(formatSize(1_099_511_627_775)).toBe('1024.0 GB');
  });
});
