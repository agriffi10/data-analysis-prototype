import {useCallback, useEffect, useMemo, useReducer, type ReactNode} from 'react';
import {
  SelectionContext,
  selectionReducer,
  initialSelectionState,
  type SelectionContextValue
} from './selectionContext';

// SPEC-018 FR-001: wraps a view in selection state. The `prefix` prop is the
// folder currently shown; whenever it changes the selection clears (navigate-
// clears), so a selection never carries across folders. A completed delete clears
// via clear(). The reducer itself lives in selectionContext.ts (pure + testable).
export function SelectionProvider({prefix, children}: {prefix?: string; children: ReactNode}) {
  const [state, dispatch] = useReducer(selectionReducer, initialSelectionState);

  useEffect(() => {
    dispatch({type: 'clear'});
  }, [prefix]);

  // dispatch is stable, so the mutators are stable too — a consumer that only uses
  // one of them (e.g. a memoized checkbox reading `toggle`) doesn't churn when the
  // selection changes. The context value's identity still updates when the selection
  // changes (selected/count/isSelected depend on it), which is exactly when it should.
  const toggle = useCallback(
    (item: Parameters<SelectionContextValue['toggle']>[0]) => dispatch({type: 'toggle', item}),
    []
  );
  const selectAll = useCallback(
    (items: Parameters<SelectionContextValue['selectAll']>[0]) => dispatch({type: 'selectAll', items}),
    []
  );
  const clear = useCallback(() => dispatch({type: 'clear'}), []);

  const value = useMemo<SelectionContextValue>(
    () => ({
      selected: state.items,
      count: state.items.size,
      isSelected: (id) => state.items.has(id),
      toggle,
      selectAll,
      clear
    }),
    [state, toggle, selectAll, clear]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}
