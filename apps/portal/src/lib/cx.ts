type CxArg = string | false | null | undefined;

/**
 * Joins truthy class names with spaces — a dependency-free stand-in for clsx.
 *
 * @example
 * cx('btn', isActive && 'btn-active', className)
 */
export function cx(...args: CxArg[]): string {
  return args.filter(Boolean).join(' ');
}
