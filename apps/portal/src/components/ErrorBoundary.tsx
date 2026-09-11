import {Component, type ErrorInfo, type ReactNode} from 'react';
import {Button} from './Button';

type Props = {
  children: ReactNode;
  /** Replaces the default fallback entirely. Omit for the standard reload panel. */
  fallback?: ReactNode;
  /**
   * An extra line in the standard panel, above its reload button — for what a reload would cost
   * here. It renders inside the boundary, so it can read the providers the boundary sits in, and
   * outside the panel's alert, so a line that changes while it is up is not announced again.
   */
  notice?: ReactNode;
  /**
   * Clears a caught error when this value changes, and renders the children again.
   *
   * A reset rather than a React `key`: a key remounts everything beneath the boundary on every
   * change, and a boundary above the signed-in shell would take the session's uploads and
   * in-flight operations down with it. The layouts pass the path and query string, so going to any
   * other address resets it. Not the location's own `key`: that changes on a navigation to the SAME
   * address too, and a page that re-navigates to its own URL on mount while a child throws would
   * reset into the throw for as long as it kept mounting.
   */
  resetKey?: unknown;
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
 * The motivating case is the accepted deploy race. It first appeared against a
 * reconciling S3 sync, and it survived that delivery path's retirement: a rolling
 * container replacement serves two image versions at once, so a user with the SPA
 * already open triggers a lazy import, the request lands on a task built from a
 * different commit, and the import rejects inside a `Suspense` boundary. Suspense
 * has no error path, so with no boundary the whole app unmounted to a white screen.
 * The window closes on its own once the rollover finishes, which is why the fallback
 * offers a reload rather than a retry.
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

  componentDidUpdate(prevProps: Props, prevState: State): void {
    // Both halves stop a reset from rendering a broken child straight back into a throw.
    // `prevState.hasError` skips the update that caught the error, when the change of key is
    // itself what rendered the broken child. The key comparison ends it when a reset renders
    // ANOTHER broken child: that reset's render never commits, so the catch that follows still
    // finds the error in `prevState`, and only an unchanged key keeps it from resetting forever.
    if (prevState.hasError && this.state.hasError && !Object.is(prevProps.resetKey, this.props.resetKey)) {
      this.setState({hasError: false});
    }
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;

    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-24 text-center">
        <div
          role="alert"
          className="flex flex-col items-center gap-3">
          <p className="text-md font-medium text-text">{FALLBACK_TITLE}</p>
          <p className="max-w-prose text-text-3">{FALLBACK_BODY}</p>
        </div>
        {this.props.notice}
        <Button
          variant="primary"
          onClick={() => window.location.reload()}>
          Reload the page
        </Button>
      </div>
    );
  }
}
