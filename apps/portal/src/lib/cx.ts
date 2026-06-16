// Tiny class-name helper used by the shared UI primitives (SPEC-028). Filters
// falsy values and joins the rest with spaces — a local alternative to clsx so
// the stack stays dependency-free.
type CxArg = string | false | null | undefined;

export function cx(...args: CxArg[]): string {
  return args.filter(Boolean).join(' ');
}
