/**
 * Centered "Loading…" indicator used by the route Suspense fallback and the
 * auth gate while state resolves. Always a `role="status"` live region so the
 * state is announced to assistive tech.
 *
 * @example
 * <Suspense fallback={<LoadingState label="Loading files…" />}>
 */
export function LoadingState({label = 'Loading…'}: {label?: string}) {
  return (
    <div
      role="status"
      className="flex flex-1 items-center justify-center py-24 text-text-3">
      {label}
    </div>
  );
}
