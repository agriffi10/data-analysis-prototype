import {describe, it, expect} from 'vitest';
import {
  emptyDraftKey,
  parseValues,
  validateDraftKey,
  buildPartitionKey,
  buildPartitionKeys,
  type DraftPartitionKey
} from './partitionKeys';

// Build a draft from partial overrides on a blank row (with a stable id).
function draft(over: Partial<DraftPartitionKey>): DraftPartitionKey {
  return {...emptyDraftKey(), ...over};
}

describe('emptyDraftKey', () => {
  it('defaults to a string key with a date format and unique id', () => {
    const a = emptyDraftKey();
    const b = emptyDraftKey();
    expect(a.type).toBe('string');
    expect(a.format).toBe('yyyy-MM-dd');
    expect(a.id).not.toBe(b.id);
  });
});

describe('parseValues', () => {
  it('splits, trims, and drops empties', () => {
    expect(parseValues(' us, eu , , apac ')).toEqual(['us', 'eu', 'apac']);
    expect(parseValues('')).toEqual([]);
  });
});

describe('validateDraftKey — name', () => {
  it('requires a name', () => {
    expect(validateDraftKey(draft({name: '', type: 'string', values: 'a'}), []).name).toBeTruthy();
  });

  it('enforces the catalog-safe rule', () => {
    expect(validateDraftKey(draft({name: 'Year', type: 'string', values: 'a'}), []).name).toBeTruthy();
    expect(validateDraftKey(draft({name: '1year', type: 'string', values: 'a'}), []).name).toBeTruthy();
  });

  it('flags a duplicate name against the set', () => {
    const a = draft({name: 'year', type: 'string', values: 'x'});
    const b = draft({name: 'year', type: 'string', values: 'y'});
    expect(validateDraftKey(b, [a, b]).name).toMatch(/duplicate/i);
  });
});

describe('validateDraftKey — integer', () => {
  it('requires whole-number min and max', () => {
    const e = validateDraftKey(draft({name: 'y', type: 'integer', min: 'x', max: '1.5'}), []);
    expect(e.min).toBeTruthy();
    expect(e.max).toBeTruthy();
  });

  it('requires min < max', () => {
    const e = validateDraftKey(draft({name: 'y', type: 'integer', min: '5', max: '5'}), []);
    expect(e.max).toMatch(/greater/i);
  });

  it('accepts a valid range and blank digits', () => {
    expect(validateDraftKey(draft({name: 'year', type: 'integer', min: '2020', max: '2026'}), [])).toEqual({});
  });

  it('rejects non-positive / non-integer digits', () => {
    expect(
      validateDraftKey(draft({name: 'y', type: 'integer', min: '0', max: '9', digits: '0'}), []).digits
    ).toBeTruthy();
    expect(
      validateDraftKey(draft({name: 'y', type: 'integer', min: '0', max: '9', digits: 'x'}), []).digits
    ).toBeTruthy();
  });
});

describe('validateDraftKey — date', () => {
  it('requires start, end, and format', () => {
    const e = validateDraftKey(draft({name: 'd', type: 'date', start: '', end: '', format: ''}), []);
    expect(e.start).toBeTruthy();
    expect(e.end).toBeTruthy();
    expect(e.format).toBeTruthy();
  });

  it('accepts a complete date config', () => {
    expect(
      validateDraftKey(draft({name: 'day', type: 'date', start: '2020-01-01', end: 'NOW', format: 'yyyy-MM-dd'}), [])
    ).toEqual({});
  });
});

describe('validateDraftKey — string', () => {
  it('requires at least one value', () => {
    expect(validateDraftKey(draft({name: 's', type: 'string', values: '  '}), []).values).toBeTruthy();
  });
});

describe('buildPartitionKey', () => {
  it('builds an integer key with optional digits', () => {
    expect(
      buildPartitionKey(draft({name: 'year', type: 'integer', min: '2020', max: '2026', digits: '4'}), [])
    ).toEqual({
      name: 'year',
      type: 'integer',
      range: [2020, 2026],
      digits: 4
    });
    expect(buildPartitionKey(draft({name: 'year', type: 'integer', min: '2020', max: '2026'}), [])).toEqual({
      name: 'year',
      type: 'integer',
      range: [2020, 2026]
    });
  });

  it('builds a date key', () => {
    expect(
      buildPartitionKey(draft({name: 'day', type: 'date', start: '2020-01-01', end: 'NOW', format: 'yyyy-MM-dd'}), [])
    ).toEqual({name: 'day', type: 'date', range: ['2020-01-01', 'NOW'], format: 'yyyy-MM-dd'});
  });

  it('builds a string enum key', () => {
    expect(buildPartitionKey(draft({name: 'region', type: 'string', values: 'us, eu'}), [])).toEqual({
      name: 'region',
      type: 'string',
      values: ['us', 'eu']
    });
  });

  it('returns null for an invalid draft', () => {
    expect(buildPartitionKey(draft({name: '', type: 'string', values: 'a'}), [])).toBeNull();
  });
});

describe('buildPartitionKeys', () => {
  it('treats an empty list as a valid flat table', () => {
    expect(buildPartitionKeys([])).toEqual({valid: true, keys: [], errors: []});
  });

  it('builds all keys in order when every row is valid', () => {
    const rows = [
      draft({name: 'year', type: 'integer', min: '2020', max: '2026'}),
      draft({name: 'region', type: 'string', values: 'us,eu'})
    ];
    const result = buildPartitionKeys(rows);
    expect(result.valid).toBe(true);
    expect(result.keys.map((k) => k.name)).toEqual(['year', 'region']);
  });

  it('is invalid and sends no keys when any row is invalid', () => {
    const rows = [draft({name: 'year', type: 'integer', min: '2020', max: '2026'}), draft({name: '', type: 'string'})];
    const result = buildPartitionKeys(rows);
    expect(result.valid).toBe(false);
    expect(result.keys).toEqual([]);
    expect(result.errors[1].name).toBeTruthy();
  });
});
