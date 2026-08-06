import {useMemo, type ReactNode} from 'react';
import {EscapeDepthContext, useEscapeDepth} from '../hooks/escapeLayerContext';

/**
 * Marks its children as one Escape layer deeper, so a dialog opened from inside a
 * drawer outranks it for the Escape key. Rendered by `Modal` and `Drawer` — the only
 * two components that own an Escape-dismissible surface — around their children.
 */
export function EscapeLayer({children}: {children: ReactNode}) {
  const depth = useEscapeDepth();
  const next = useMemo(() => depth + 1, [depth]);
  return <EscapeDepthContext.Provider value={next}>{children}</EscapeDepthContext.Provider>;
}
