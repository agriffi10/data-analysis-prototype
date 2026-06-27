import { describe, it, expect } from 'vitest';
import { renderHook, render, act } from '@testing-library/react';
import { type ReactNode } from 'react';
import { SelectionProvider } from './SelectionProvider';
import {
  selectionReducer,
  initialSelectionState,
  useSelection,
  type SelectionState,
  type SelectableItem,
  type SelectionContextValue,
} from './selectionContext';

const fileA: SelectableItem = { type: 'file', key: 'alice/a.txt' };
const fileB: SelectableItem = { type: 'file', key: 'alice/b.txt' };
const folder: SelectableItem = { type: 'folder', prefix: 'alice/docs/' };

describe('selectionReducer', () => {
  it('toggle adds an unselected item', () => {
    const next = selectionReducer(initialSelectionState, {
      type: 'toggle',
      item: fileA,
    });
    expect(next.items.size).toBe(1);
    expect(next.items.get('alice/a.txt')).toEqual(fileA);
  });

  it('toggle removes an already-selected item', () => {
    const withA = selectionReducer(initialSelectionState, {
      type: 'toggle',
      item: fileA,
    });
    const without = selectionReducer(withA, { type: 'toggle', item: fileA });
    expect(without.items.size).toBe(0);
  });

  it('toggles files and folders by their distinct ids (key vs prefix)', () => {
    let state: SelectionState = initialSelectionState;
    state = selectionReducer(state, { type: 'toggle', item: fileA });
    state = selectionReducer(state, { type: 'toggle', item: folder });
    expect(state.items.size).toBe(2);
    expect(state.items.has('alice/a.txt')).toBe(true);
    expect(state.items.has('alice/docs/')).toBe(true);
  });

  it('selectAll replaces the selection with exactly the given items', () => {
    const withA = selectionReducer(initialSelectionState, {
      type: 'toggle',
      item: fileA,
    });
    const all = selectionReducer(withA, {
      type: 'selectAll',
      items: [fileB, folder],
    });
    expect(all.items.size).toBe(2);
    expect(all.items.has('alice/a.txt')).toBe(false); // replaced, not merged
    expect(all.items.has('alice/b.txt')).toBe(true);
    expect(all.items.has('alice/docs/')).toBe(true);
  });

  it('clear empties the selection', () => {
    const withItems = selectionReducer(initialSelectionState, {
      type: 'selectAll',
      items: [fileA, fileB],
    });
    const cleared = selectionReducer(withItems, { type: 'clear' });
    expect(cleared.items.size).toBe(0);
  });

  it('clear preserves referential identity when already empty', () => {
    const cleared = selectionReducer(initialSelectionState, { type: 'clear' });
    expect(cleared).toBe(initialSelectionState);
  });

  it('does not mutate the previous state (returns a fresh Map)', () => {
    const next = selectionReducer(initialSelectionState, {
      type: 'toggle',
      item: fileA,
    });
    expect(initialSelectionState.items.size).toBe(0);
    expect(next.items).not.toBe(initialSelectionState.items);
  });
});

describe('SelectionProvider', () => {
  function renderSelection(prefix: string) {
    return renderHook(() => useSelection(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <SelectionProvider prefix={prefix}>{children}</SelectionProvider>
      ),
    });
  }

  it('exposes selection actions and derived count/isSelected', () => {
    const { result } = renderSelection('alice/');

    act(() => result.current.toggle(fileA));
    expect(result.current.count).toBe(1);
    expect(result.current.isSelected('alice/a.txt')).toBe(true);
    expect(result.current.isSelected('alice/b.txt')).toBe(false);
  });

  it('clears the selection when the prefix changes (navigate-clears)', () => {
    // renderHook's `wrapper` only receives `children`, so we drive the prefix
    // prop through a real render tree and capture the latest context value.
    let latest!: SelectionContextValue;
    function Capture() {
      latest = useSelection();
      return null;
    }
    const harness = (prefix: string) => (
      <SelectionProvider prefix={prefix}>
        <Capture />
      </SelectionProvider>
    );

    const { rerender } = render(harness('alice/'));

    act(() => latest.toggle(fileA));
    expect(latest.count).toBe(1);

    // Navigating into a different folder must drop the prior selection.
    rerender(harness('alice/docs/'));
    expect(latest.count).toBe(0);
  });

  it('throws when useSelection is used outside a provider', () => {
    expect(() => renderHook(() => useSelection())).toThrow(/must be used within a SelectionProvider/);
  });
});
