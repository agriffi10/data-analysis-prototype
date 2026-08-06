import {createContext, useContext} from 'react';

/**
 * How deeply nested the surrounding Escape-dismissible layer is. `0` is the page.
 *
 * DEPTH COMES FROM THE TREE, NOT FROM TIME. The obvious implementation — a stack that
 * assumes the last handler registered is the innermost — is wrong in React twice over:
 * child effects run BEFORE their parent's, so a nested dialog registers first, and any
 * re-render that changes the handler's identity re-registers that layer at the top.
 * Both were measured; both put the outer layer in front of the inner one.
 *
 * Split from `EscapeLayer.tsx` so that component file only exports a component
 * (react-refresh/only-export-components), mirroring `toastContext.ts`.
 */
export const EscapeDepthContext = createContext(0);

/** The depth of the layer calling this. Layers register with it; the deepest wins. */
export function useEscapeDepth(): number {
  return useContext(EscapeDepthContext);
}
