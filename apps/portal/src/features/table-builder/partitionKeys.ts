import {PARTITION_KEY_NAME_RE, PARTITION_KEY_NAME_RULE} from '../../lib/catalogIdentifier';
import type {PartitionKey} from './tableBuild.types';

export type PartitionType = 'integer' | 'date' | 'string';

/**
 * The editable draft behind one partition-key row. Config fields are kept as raw
 * input strings and only parsed into the typed `PartitionKey` wire shape once the
 * row validates.
 */
export type DraftPartitionKey = {
  /** Stable local key for React lists + focus management on add/remove. */
  id: string;
  name: string;
  type: PartitionType;
  // integer
  min: string;
  max: string;
  digits: string;
  // date
  start: string;
  end: string;
  format: string;
  /** Comma-separated enum list (string type). */
  values: string;
};

export type PartitionKeyErrors = {
  name?: string;
  min?: string;
  max?: string;
  digits?: string;
  start?: string;
  end?: string;
  format?: string;
  values?: string;
};

const INT_RE = /^-?\d+$/;

let seq = 0;

/**
 * A blank draft row. Default type = string (the simplest projection to configure)
 * with a sensible default date format so the date path isn't empty-by-default.
 */
export function emptyDraftKey(): DraftPartitionKey {
  seq += 1;
  return {
    id: `pk-${seq}-${crypto.randomUUID()}`,
    name: '',
    type: 'string',
    min: '',
    max: '',
    digits: '',
    start: '',
    end: '',
    format: 'yyyy-MM-dd',
    values: ''
  };
}

/** Split a comma-separated enum list into trimmed, non-empty values. */
export function parseValues(raw: string): string[] {
  return raw
    .split(',')
    .map((v) => v.trim())
    .filter((v) => v.length > 0);
}

/**
 * Validate one draft against the whole set (for the uniqueness check). Returns only
 * the fields in error, so an empty object means the row is valid.
 */
export function validateDraftKey(draft: DraftPartitionKey, all: DraftPartitionKey[]): PartitionKeyErrors {
  const errors: PartitionKeyErrors = {};
  const name = draft.name.trim();

  if (name.length === 0) errors.name = 'Enter a key name.';
  else if (!PARTITION_KEY_NAME_RE.test(name)) errors.name = PARTITION_KEY_NAME_RULE;
  else if (all.some((k) => k.id !== draft.id && k.name.trim() === name)) errors.name = 'Duplicate key name.';

  if (draft.type === 'integer') {
    const minOk = INT_RE.test(draft.min.trim());
    const maxOk = INT_RE.test(draft.max.trim());
    if (!minOk) errors.min = 'Enter a whole number.';
    if (!maxOk) errors.max = 'Enter a whole number.';
    if (minOk && maxOk && Number(draft.min) >= Number(draft.max)) {
      errors.max = 'Max must be greater than min.';
    }
    const digits = draft.digits.trim();
    if (digits !== '' && (!/^\d+$/.test(digits) || Number(digits) < 1)) {
      errors.digits = 'Digits must be a positive whole number.';
    }
  } else if (draft.type === 'date') {
    if (draft.start.trim().length === 0) errors.start = 'Enter a range start.';
    if (draft.end.trim().length === 0) errors.end = 'Enter a range end.';
    if (draft.format.trim().length === 0) errors.format = 'Enter a date format.';
  } else {
    if (parseValues(draft.values).length === 0) errors.values = 'Enter at least one value.';
  }

  return errors;
}

/** Build the typed wire key from a draft; null if the draft is invalid ("not ready"). */
export function buildPartitionKey(draft: DraftPartitionKey, all: DraftPartitionKey[]): PartitionKey | null {
  if (Object.keys(validateDraftKey(draft, all)).length > 0) return null;
  const name = draft.name.trim();
  if (draft.type === 'integer') {
    const digits = draft.digits.trim();
    return {
      name,
      type: 'integer',
      range: [Number(draft.min), Number(draft.max)],
      ...(digits !== '' ? {digits: Number(digits)} : {})
    };
  }
  if (draft.type === 'date') {
    return {name, type: 'date', range: [draft.start.trim(), draft.end.trim()], format: draft.format.trim()};
  }
  return {name, type: 'string', values: parseValues(draft.values)};
}

export type PartitionKeysResult = {
  valid: boolean;
  keys: PartitionKey[];
  /** One per draft, index-aligned. */
  errors: PartitionKeyErrors[];
};

/**
 * Reduce the whole draft list to overall validity, the built wire keys, and
 * index-aligned per-row errors. An empty draft list is valid (a flat table sends no keys).
 */
export function buildPartitionKeys(drafts: DraftPartitionKey[]): PartitionKeysResult {
  const errors = drafts.map((d) => validateDraftKey(d, drafts));
  const valid = errors.every((e) => Object.keys(e).length === 0);
  const keys = valid
    ? drafts.map((d) => buildPartitionKey(d, drafts)).filter((k): k is PartitionKey => k !== null)
    : [];
  return {valid, keys, errors};
}
