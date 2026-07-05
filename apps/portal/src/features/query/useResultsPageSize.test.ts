import {describe, it, expect, beforeEach} from 'vitest';
import {renderHook, act} from '@testing-library/react';
import {useResultsPageSize, clampPageSize} from './useResultsPageSize';
import {
  DEFAULT_RESULTS_PAGE_SIZE,
  MAX_RESULTS_PAGE_SIZE,
  MIN_RESULTS_PAGE_SIZE,
  QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX
} from './query.constants';

const USER = 'alice';
const KEY = `${QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX}${USER}`;

beforeEach(() => {
  sessionStorage.clear();
});

describe('clampPageSize', () => {
  it('passes integers in range through unchanged', () => {
    expect(clampPageSize(1)).toBe(1);
    expect(clampPageSize(250)).toBe(250);
    expect(clampPageSize(1000)).toBe(1000);
  });

  it('clamps out-of-range integers to the bounds (FR-003)', () => {
    expect(clampPageSize(0)).toBe(MIN_RESULTS_PAGE_SIZE);
    expect(clampPageSize(-5)).toBe(MIN_RESULTS_PAGE_SIZE);
    expect(clampPageSize(1001)).toBe(MAX_RESULTS_PAGE_SIZE);
    expect(clampPageSize(999999)).toBe(MAX_RESULTS_PAGE_SIZE);
  });

  it('rejects non-integers (FR-003: fractional/NaN never set a page size)', () => {
    expect(clampPageSize(2.5)).toBeNull();
    expect(clampPageSize(Number.NaN)).toBeNull();
    expect(clampPageSize(Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('useResultsPageSize', () => {
  it('defaults to 100 with no stored value (FR-001/FR-005)', () => {
    const {result} = renderHook(() => useResultsPageSize(USER));
    expect(result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
  });

  it('setPageSize applies and persists the value per user (FR-005)', () => {
    const {result} = renderHook(() => useResultsPageSize(USER));
    act(() => result.current.setPageSize(250));
    expect(result.current.pageSize).toBe(250);
    expect(sessionStorage.getItem(KEY)).toBe('250');
  });

  it('clamps below-minimum and above-maximum values (FR-003)', () => {
    const {result} = renderHook(() => useResultsPageSize(USER));
    act(() => result.current.setPageSize(0));
    expect(result.current.pageSize).toBe(MIN_RESULTS_PAGE_SIZE);
    act(() => result.current.setPageSize(5000));
    expect(result.current.pageSize).toBe(MAX_RESULTS_PAGE_SIZE);
  });

  it('ignores non-integer input, keeping the last valid value (FR-003)', () => {
    const {result} = renderHook(() => useResultsPageSize(USER));
    act(() => result.current.setPageSize(50));
    act(() => result.current.setPageSize(12.7));
    act(() => result.current.setPageSize(Number.NaN));
    expect(result.current.pageSize).toBe(50);
    expect(sessionStorage.getItem(KEY)).toBe('50');
  });

  it('restores a stored value on mount (reload survival, FR-005)', () => {
    sessionStorage.setItem(KEY, '400');
    const {result} = renderHook(() => useResultsPageSize(USER));
    expect(result.current.pageSize).toBe(400);
  });

  it('falls back to the default on a malformed or out-of-range stored value (FR-005)', () => {
    sessionStorage.setItem(KEY, 'lots');
    expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
    sessionStorage.setItem(KEY, '99999');
    expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
    sessionStorage.setItem(KEY, '2.5');
    expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
  });

  it('scopes persistence to the username', () => {
    sessionStorage.setItem(`${QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX}bob`, '17');
    const {result} = renderHook(() => useResultsPageSize(USER));
    expect(result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
  });

  it('works without persisting when username is null', () => {
    const {result} = renderHook(() => useResultsPageSize(null));
    act(() => result.current.setPageSize(33));
    expect(result.current.pageSize).toBe(33);
    expect(sessionStorage.length).toBe(0);
  });

  it('still applies (non-persistently) when sessionStorage throws', () => {
    const throwing = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      }
    };
    const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
    Object.defineProperty(globalThis, 'sessionStorage', {value: throwing, configurable: true});
    try {
      const {result} = renderHook(() => useResultsPageSize(USER));
      expect(result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
      act(() => result.current.setPageSize(200));
      expect(result.current.pageSize).toBe(200);
    } finally {
      if (original) Object.defineProperty(globalThis, 'sessionStorage', original);
    }
  });
});
