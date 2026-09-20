import {describe, expect, it} from 'vitest';
import {exportColumnIndexes} from './exportColumns';

// SPEC-239 FR-005. A pure resolver, so it is tested directly rather than through the region —
// the region's own behaviour (which list it passes, and the refusal) is in `copyExport.test.tsx`.

describe('exportColumnIndexes', () => {
  it('keeps the visible columns, in the order the grid draws them', () => {
    // AC1. Hiding one, and reordering without hiding, both produce a list.
    expect(exportColumnIndexes(['a', 'b', 'c'], ['a', 'c'])).toEqual([0, 2]);
    expect(exportColumnIndexes(['a', 'b', 'c'], ['c', 'a', 'b'])).toEqual([2, 0, 1]);
  });

  it('answers null when the grid shows the whole result in its own order', () => {
    // AC1, and the reason CSV stays an instant copy: there is nothing a conversion could
    // produce that the object Athena already wrote does not have.
    expect(exportColumnIndexes(['a', 'b', 'c'], ['a', 'b', 'c'])).toBeNull();
    expect(exportColumnIndexes(['a'], ['a'])).toBeNull();
  });

  it('leaves out a visible column the result does not have', () => {
    // AC1. The percentage column is computed in the browser and is in no result. With it
    // dropped the remaining list is the whole result in order, so this is a copy after all.
    expect(exportColumnIndexes(['a'], ['a', 'pct_of_count_all'])).toBeNull();
    expect(exportColumnIndexes(['a', 'b'], ['b', 'pct_of_count_all'])).toEqual([1]);
  });

  it('answers an EMPTY list when no visible column is in the result, and null when there is no result yet', () => {
    // The two cases a caller must not confuse. Every real column hidden in a grouped
    // exploration is a save that cannot be made; a result that has not landed is a grid with
    // nothing hidden, and showing a refusal there would refuse a save that is about to be fine.
    expect(exportColumnIndexes(['a', 'b'], ['pct_of_count_all'])).toEqual([]);
    expect(exportColumnIndexes([], [])).toBeNull();
    expect(exportColumnIndexes([], ['pct_of_count_all'])).toBeNull();
  });
});
