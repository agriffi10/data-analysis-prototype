import {describe, it, expect} from 'vitest';
import {formatBytes, normalizeColumnType} from './query.format';

describe('normalizeColumnType', () => {
  it('maps Athena/Presto engine names to their Glue/Hive DDL equivalents', () => {
    expect(normalizeColumnType('varchar')).toBe('string');
    expect(normalizeColumnType('integer')).toBe('int');
    expect(normalizeColumnType('real')).toBe('float');
    expect(normalizeColumnType('varbinary')).toBe('binary');
    expect(normalizeColumnType('VARCHAR')).toBe('string'); // case-insensitive
  });

  it('passes already-matching and complex/parameterized types through unchanged', () => {
    expect(normalizeColumnType('bigint')).toBe('bigint');
    expect(normalizeColumnType('boolean')).toBe('boolean');
    expect(normalizeColumnType('timestamp')).toBe('timestamp');
    expect(normalizeColumnType('decimal(10,2)')).toBe('decimal(10,2)');
    expect(normalizeColumnType('array(integer)')).toBe('array(integer)');
    expect(normalizeColumnType('')).toBe('');
  });
});

describe('formatBytes', () => {
  it('formats byte sizes with sensible units + precision', () => {
    expect(formatBytes(undefined)).toBe('—');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(1_258_291)).toBe('1.2 MB');
    expect(formatBytes(53_687_091)).toBe('51 MB'); // ≥10 drops the decimal
  });
});
