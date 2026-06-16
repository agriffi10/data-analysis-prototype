import { useEffect, useMemo, useReducer, type ReactNode } from 'react';
import {
  SelectionContext,
  selectionReducer,
  initialSelectionState,
  type SelectionContextValue,
} from './selectionContext';

// SPEC-018 FR-001: wraps a view in selection state. The `prefix` prop is the
// folder currently shown; whenever it changes the selection clears (navigate-
// clears), so a selection never carries across folders. A completed delete clears
// via clear(). The reducer itself lives in selectionContext.ts (pure + testable).
export function SelectionProvider({
  prefix,
  children,
}: {
  prefix?: string;
  children: ReactNode;
}) {
  const [state, dispatch] = useReducer(selectionReducer, initialSelectionState);

  useEffect(() => {
    dispatch({ type: 'clear' });
  }, [prefix]);

  const value = useMemo<SelectionContextValue>(
    () => ({
      selected: state.items,
      count: state.items.size,
      isSelected: (id) => state.items.has(id),
      toggle: (item) => dispatch({ type: 'toggle', item }),
      selectAll: (items) => dispatch({ type: 'selectAll', items }),
      clear: () => dispatch({ type: 'clear' }),
    }),
    [state],
  );

  return (
    <SelectionContext.Provider value={value}>
      {children}
    </SelectionContext.Provider>
  );
}
