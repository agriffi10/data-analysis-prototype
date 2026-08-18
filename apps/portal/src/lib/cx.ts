type CxArg = string | false | null | undefined;

/**
 * Joins truthy class names with spaces — a dependency-free stand-in for clsx.
 *
 * RETURNS `undefined`, NOT `''`, WHEN NOTHING IS TRUTHY. The empty
 * string is a value `??` does not fall back on, so a component applying its default as
 * `className ?? 'max-w-md'` silently lost that default whenever a caller passed it a
 * `cx()` of all-falsy arguments — which is how nine dialogs came to render at full
 * viewport width. Absent is what the caller means, so absent is what this returns; a
 * `className` prop takes `undefined` everywhere, and the two call sites that want a
 * string for `aria-describedby` already coerce with `|| undefined`.
 *
 * @example
 * cx('btn', isActive && 'btn-active', className)
 */
export function cx(...args: CxArg[]): string | undefined {
  const joined = args.filter(Boolean).join(' ');
  return joined || undefined;
}
