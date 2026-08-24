import {createRoot} from 'react-dom/client';
import './index.css';
import {configureAmplify} from './lib/amplify';
import {loadRuntimeConfig, warnIfMisconfigured} from './lib/runtimeConfig';
import {BootFailure} from './components/BootFailure';

// THIS IMPORT LIST IS DELIBERATELY TINY, AND A SWEEP FAILS IF IT GROWS. Static imports
// are evaluated before the first statement below runs, so anything reaching the
// application graph from here would evaluate it before the configuration document is
// fetched — and in a production build, any module-scope read would throw before the
// screen below could render. `AppRoot` is therefore reached by `await import`.

// Names any missing required variable in dev, where the alternative is a generic SDK
// error about a bucket called "undefined". Guarded at the call boundary so it drops out
// of the production bundle; the function guards itself too, for any other caller.
if (import.meta.env.DEV) warnIfMisconfigured();

const root = createRoot(document.getElementById('root')!);

void (async () => {
  const loaded = await loadRuntimeConfig();

  if (!loaded.ok) {
    // The KEY NAMES, never a value: an operator staring at a failed task has no other
    // diagnostic, and the deployed app must not print its own configuration to a console.
    const detail = loaded.reason === 'missing-required' ? `: ${loaded.missing.join(', ')}` : '';
    console.error(`[config] the portal could not start (${loaded.reason})${detail}`);
    root.render(<BootFailure />);
    return;
  }

  try {
    // Before the first render, not after: a sign-in that begins against an unconfigured
    // Amplify fails in a way a warm session never reproduces.
    configureAmplify();
    const {AppRoot} = await import('./AppRoot');
    root.render(<AppRoot />);
  } catch (error) {
    // The app has a perfectly good failure screen; the one path that used to skip it was
    // this one. A chunk request can be rejected outright when a deploy replaces the
    // hashed assets mid-boot, and the alternative is a blank page and an unhandled
    // rejection.
    console.error('[config] the portal could not start (bootstrap)', error);
    root.render(<BootFailure />);
  }
})();
