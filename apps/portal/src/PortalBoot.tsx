import {useEffect, useState, type ComponentType} from 'react';
import {configureAmplify} from './lib/amplify';
import {loadRuntimeConfig} from './lib/runtimeConfig';
import {BootFailure} from './components/BootFailure';

// THIS IMPORT LIST IS DELIBERATELY TINY, AND A SWEEP FAILS IF IT GROWS. Static imports are
// evaluated before the boot below runs, so anything reaching the application graph from here would
// evaluate it before the configuration document is fetched, and in a production build any
// module-scope read would throw before the failure screen could render. `AppRoot` is therefore
// reached by `await import`.

/**
 * The one boot in flight, shared by every mount.
 *
 * React's development build runs an effect twice on mount; a second load would fetch the document
 * and configure Amplify again. Keyed to the module, so a remount in the same page reuses the result
 * instead of booting twice.
 */
let booting: Promise<ComponentType> | undefined;

/**
 * Load the configuration, configure Amplify, then import the app: in that order, once.
 *
 * Never rejects: every failure resolves to the boot-failure screen, after one console line naming
 * the reason and, for missing keys, their NAMES and never a value. An operator staring at a failed
 * task has no other diagnostic, and the deployed app must not print its own configuration.
 *
 * @returns The component to render: the app, or the boot-failure screen.
 */
async function boot(): Promise<ComponentType> {
  const loaded = await loadRuntimeConfig();
  if (!loaded.ok) {
    const detail = loaded.reason === 'missing-required' ? `: ${loaded.missing.join(', ')}` : '';
    console.error(`[config] the portal could not start (${loaded.reason})${detail}`);
    return BootFailure;
  }
  try {
    // Before the first render, not after: a sign-in that begins against an unconfigured Amplify
    // fails in a way a warm session never reproduces.
    configureAmplify();
    const {AppRoot} = await import('./AppRoot');
    return AppRoot;
  } catch (error) {
    // A chunk request can be rejected outright when a deploy replaces the hashed assets mid-boot;
    // the alternative is a blank page and an unhandled rejection.
    console.error('[config] the portal could not start (bootstrap)', error);
    return BootFailure;
  }
}

/**
 * The whole existing app, behind the configuration it needs.
 *
 * Rendered by the catch-all route in the browser only. Nothing renders until the boot settles,
 * which is the old `main.tsx`'s behaviour, now inside the page Next renders around it.
 *
 * @returns The app or the boot-failure screen once the boot settles, and nothing before.
 */
export function PortalBoot() {
  const [Root, setRoot] = useState<ComponentType | null>(null);

  useEffect(() => {
    let current = true;
    booting ??= boot();
    void booting.then((component) => {
      if (current) setRoot(() => component);
    });
    return () => {
      current = false;
    };
  }, []);

  return Root ? <Root /> : null;
}
