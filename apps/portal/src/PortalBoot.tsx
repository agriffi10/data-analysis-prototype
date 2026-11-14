import {useEffect, useState, type ComponentType, type ReactNode} from 'react';
import {configureAmplify} from './lib/amplify';
import {loadRuntimeConfig} from './lib/runtimeConfig';
import {BootFailure} from './components/BootFailure';

// THIS IMPORT LIST IS DELIBERATELY TINY, AND A SWEEP FAILS IF IT GROWS. Static imports are
// evaluated before the boot below runs, so anything reaching the application graph from here would
// evaluate it before the configuration document is fetched, and in a production build any
// module-scope read would throw before the failure screen could render. `AppFrame` is therefore
// reached by `await import`.

/** What the boot settles to: the frame the page renders in, or the screen saying the portal could not start. */
type Booted = {kind: 'frame'; Frame: ComponentType<{children: ReactNode}>} | {kind: 'failure'};

/**
 * The one boot in flight, shared by every mount.
 *
 * React's development build runs an effect twice on mount; a second load would fetch the document
 * and configure Amplify again. Keyed to the module, so a remount in the same page reuses the result
 * instead of booting twice.
 */
let booting: Promise<Booted> | undefined;

/**
 * Load the configuration, configure Amplify, then import the frame: in that order, once.
 *
 * Never rejects: every failure resolves to the boot-failure screen, after one console line naming
 * the reason and, for missing keys, their NAMES and never a value. An operator staring at a failed
 * task has no other diagnostic, and the deployed app must not print its own configuration.
 *
 * @returns The frame, or the failure.
 */
async function boot(): Promise<Booted> {
  const loaded = await loadRuntimeConfig();
  if (!loaded.ok) {
    const detail = loaded.reason === 'missing-required' ? `: ${loaded.missing.join(', ')}` : '';
    console.error(`[config] the portal could not start (${loaded.reason})${detail}`);
    return {kind: 'failure'};
  }
  try {
    // Before the first render, not after: a sign-in that begins against an unconfigured Amplify
    // fails in a way a warm session never reproduces.
    configureAmplify();
    const {AppFrame} = await import('./AppFrame');
    return {kind: 'frame', Frame: AppFrame};
  } catch (error) {
    // A chunk request can be rejected outright when a deploy replaces the hashed assets mid-boot;
    // the alternative is a blank page and an unhandled rejection.
    console.error('[config] the portal could not start (bootstrap)', error);
    return {kind: 'failure'};
  }
}

/**
 * Every page, behind the configuration it needs.
 *
 * Rendered by the root layout in the browser only, around whatever page Next selected. Nothing of
 * the app renders until the boot settles, and the page never renders before the frame: a page's
 * view reads configuration, and the frame is what the boot waited for.
 *
 * @param props.children - The page.
 * @returns The page inside the frame, or the boot-failure screen, once the boot settles; nothing before.
 */
export function PortalBoot({children}: {children: ReactNode}) {
  const [booted, setBooted] = useState<Booted | null>(null);

  useEffect(() => {
    let current = true;
    booting ??= boot();
    void booting.then((result) => {
      if (current) setBooted(result);
    });
    return () => {
      current = false;
    };
  }, []);

  if (!booted) return null;
  if (booted.kind === 'failure') return <BootFailure />;
  const {Frame} = booted;
  return <Frame>{children}</Frame>;
}
