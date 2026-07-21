import {describe, it, expect} from 'vitest';
import {asSentence, formatRatio, isApproximateIssue, locationLabel, sourceFolderPrefix} from './dataQuality.format';

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

describe('sourceFolderPrefix', () => {
  it('reduces a file key to its parent folder and leaves a folder alone', () => {
    // `/files?prefix=` seeds the browser's CURRENT FOLDER, so a file key passed
    // through would ask it to open a folder that does not exist.
    expect(sourceFolderPrefix('alice/data/sales.csv')).toBe('alice/data/');
    // A folder is already the answer — it is returned untouched, not climbed.
    expect(sourceFolderPrefix('alice/data/sales/')).toBe('alice/data/sales/');
    expect(sourceFolderPrefix('top.csv')).toBe('');
  });
});

describe('formatRatio', () => {
  it('distinguishes no blanks from a ratio that merely rounds to none', () => {
    // A handful of blanks in a million rows is not the same as none, and "0.0%"
    // would claim it is.
    expect(formatRatio(0)).toBe('0%');
    expect(formatRatio(0.0000008)).toBe('<0.1%');
    expect(formatRatio(0.0432)).toBe('4.3%');
    expect(formatRatio(0.61)).toBe('61.0%');
  });
});

describe('asSentence', () => {
  it('makes a lower-case Lambda fragment read as a standalone sentence', () => {
    // dqcommon writes reasons as fragments that complete "Couldn't check data quality:
    // {reason}". This view shows them alone after a bold lead, where the raw fragment
    // reads as a typo — "Not applicable. not a line-delimited text format."
    expect(asSentence('not a line-delimited text format.')).toBe('Not a line-delimited text format.');
    expect(asSentence('binary format — encoding is defined by the file format')).toBe(
      'Binary format — encoding is defined by the file format.'
    );
  });

  it('leaves an already-well-formed reason alone', () => {
    const parquet = 'Parquet enforces types in the file format, so this check cannot find anything.';
    expect(asSentence(parquet)).toBe(parquet);
  });

  it('returns empty for empty input rather than a bare full stop', () => {
    expect(asSentence('')).toBe('');
    expect(asSentence('   ')).toBe('');
  });
});

describe('isApproximateIssue', () => {
  // THE WORDINGS BELOW ARE COPIED FROM `dqcommon/report.py::top_issues`, which authors
  // every top-issue line. The classifier reads those strings, so if that module's
  // wording drifts an approximate finding would be labelled `Exact` — a claim the data
  // does not support. These four cases are its four generators; this test is what makes
  // that drift loud instead of silent.
  it('flags the two approximate generators — ragged rows and encoding', () => {
    expect(isApproximateIssue('37 rows have the wrong number of fields (approximate)')).toBe(true);
    expect(
      isApproximateIssue(
        '4 invalid text encodings found, in the part examined — this data may have been exported in the wrong character set'
      )
    ).toBe(true);
    // Encoding is approximate even when the scan was complete (no ", in the part
    // examined" clause) — the whole check lives in the report's `approximate` block.
    expect(
      isApproximateIssue('4 invalid text encodings found — this data may have been exported in the wrong character set')
    ).toBe(true);
  });

  it('leaves the two exact generators — cross-file disagreements and column types', () => {
    expect(isApproximateIssue('mar.csv is missing the column `region` that the other 2 files have')).toBe(false);
    expect(isApproximateIssue('`amount` has 412 values that aren’t numbers in an otherwise numeric column')).toBe(
      false
    );
    expect(isApproximateIssue('12 duplicate rows')).toBe(false);
  });
});
