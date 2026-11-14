/**
 * Whether the document may go without the browser asking first, as a switch the auth provider
 * flips and the shell's guard reads.
 *
 * Signing out is deliberate and asks nothing, as it always has. It cannot be left to the shell
 * unmounting: measured, Amplify's sign-out moves the document to the provider's logout page in the
 * same task that announces the signed-out status, before React unmounts the shell, so the guard
 * would ask, and "Stay" would keep nothing because the shell unmounts anyway. So the sign-out
 * disarms the guard synchronously, before it starts the provider's sign-out.
 *
 * A module flag rather than context, because the auth provider sits above the shell and must reach
 * it in the same task, without a render in between.
 */
let disarmed = false;

/** Let the document go without asking, ahead of a deliberate sign-out. */
export function disarmLeaveGuard(): void {
  disarmed = true;
}

/** Ask again before the document goes: a fresh shell, or a sign-out that failed. */
export function armLeaveGuard(): void {
  disarmed = false;
}

/** Whether a sign-out has disarmed the guard. */
export function isLeaveGuardDisarmed(): boolean {
  return disarmed;
}
