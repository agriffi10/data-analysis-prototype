import {Component, type ErrorInfo, type ReactNode} from 'react';
import {Button} from './Button';

type Props = {
  children: ReactNode;
  /** Replaces the default fallback entirely. Omit for the standard reload panel. */
  fallback?: ReactNode;
};

type State = {hasError: boolean};

/**
 * Authored copy, like every other user-facing string. The thrown
 * error's `message` is NEVER rendered: a render throw is as likely to carry AWS
 * or bundler text as anything else, and this is the one surface with no service
 * layer in front of it to map through `toUserMessage`.
 */
const FALLBACK_TITLE = 'This part of the page didn’t load';
const FALLBACK_BODY = 'Reloading usually fixes it. If it keeps happening, contact the Administrator.';

/**
 * Catches a render/lifecycle throw beneath it and offers a reload instead of
 * unmounting the tree.
 *
 * The motivating case is the accepted deploy race documented on
 * `deploy-app.yml`'s "Reconcile deletions" pass: a user with the SPA already open
 * triggers a lazy import after that pass has removed the old chunk, and the import
 * rejects inside a `Suspense` boundary. Suspense has no error path, so
 * with no boundary the whole app unmounted to a white screen. That workflow's own
 * note says "once the shell revalidates, a reload recovers" — which is exactly
 * what the fallback offers, and why reload is the action rather than a retry.
 *
 * A class component on purpose: `getDerivedStateFromError` / `componentDidCatch`
 * have no hook equivalent, and this is the sanctioned exception to the
 * function-components rule (react.md §1).
 *
 * @example
 * <ErrorBoundary>
 *   <Suspense fallback={<LoadingState />}>
 *     <QueryPage />
 *   </Suspense>
 * </ErrorBoundary>
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = {hasError: false};

  static getDerivedStateFromError(): State {
    return {hasError: true};
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Not swallowed silently, and not an ungated console.error either — the same
    // dev-only discipline `errorMessages.logOriginal` uses, so it tree-shakes out
    // of the production bundle and no raw text reaches a production console.
    if (import.meta.env.DEV) {
      console.warn('[ErrorBoundary] caught a render error:', error, info.componentStack);
    }
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;

    return (
      <div
        role="alert"
        className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-24 text-center">
        <p className="text-md font-medium text-text">{FALLBACK_TITLE}</p>
        <p className="max-w-prose text-text-3">{FALLBACK_BODY}</p>
        <Button
          variant="primary"
          onClick={() => window.location.reload()}>
          Reload the page
        </Button>
      </div>
    );
  }
}
