import {createContext, useContext} from 'react';

/**
 * A multi-select entry: a file (identified by its S3 key) or a folder
 * (identified by its S3 prefix). Bulk actions treat the two differently
 * (folders are recursive), so the distinction lives in the selection itself.
 */
export type SelectableItem = {type: 'file'; key: string} | {type: 'folder'; prefix: string};

/** The stable id under which an item is tracked: its key (file) or prefix (folder). */
export function itemId(item: SelectableItem): string {
  return item.type === 'file' ? item.key : item.prefix;
}

export type SelectionContextValue = {
  /** Selected items keyed by id (SelectableItem.key | .prefix). */
  selected: Map<string, SelectableItem>;
  count: number;
  isSelected: (id: string) => boolean;
  toggle: (item: SelectableItem) => void;
  /** Replace the selection with exactly these items (header "select all"). */
  selectAll: (items: SelectableItem[]) => void;
  clear: () => void;
};

export const SelectionContext = createContext<SelectionContextValue | null>(null);

// ── Reducer ───────────────────────────────────────────────────────────────────
// Kept here (a non-component module) rather than in SelectionProvider.tsx so the
// pure reducer is unit-testable and the provider file exports only its component
// (react-refresh requires component files to export components only). Items are
// tracked in a Map keyed by id for O(1) toggle/lookup; every action returns a
// fresh Map and never mutates in place.
export type SelectionState = {
  items: Map<string, SelectableItem>;
};

export type SelectionAction =
  | {type: 'toggle'; item: SelectableItem}
  | {type: 'selectAll'; items: SelectableItem[]}
  | {type: 'clear'};

export const initialSelectionState: SelectionState = {items: new Map()};

/** Pure selection reducer: toggle / selectAll / clear over the id-keyed Map. */
export function selectionReducer(state: SelectionState, action: SelectionAction): SelectionState {
  switch (action.type) {
    case 'toggle': {
      const next = new Map(state.items);
      const id = itemId(action.item);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.set(id, action.item);
      }
      return {items: next};
    }
    case 'selectAll': {
      // Replace the selection with exactly the given (loaded) items. The header
      // checkbox decides between this and 'clear' based on current state.
      const next = new Map<string, SelectableItem>();
      for (const item of action.items) {
        next.set(itemId(item), item);
      }
      return {items: next};
    }
    case 'clear':
      // Preserve referential identity when already empty so navigate-clears on an
      // empty selection doesn't churn consumers.
      return state.items.size === 0 ? state : initialSelectionState;
    default:
      return state;
  }
}

/**
 * Consumes the selection store. Throws outside a SelectionProvider so a missing
 * provider is a loud development error, not a silent no-op.
 */
export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (ctx === null) {
    throw new Error('useSelection must be used within a SelectionProvider');
  }
  return ctx;
}
