import {toUserMessage} from '../lib/errorMessages';

/**
 * What renders instead of the app when the runtime configuration cannot be loaded.
 *
 * Not a route and not inside any provider: it is mounted directly by the bootstrap, on
 * a path where `AuthProvider`, the query client and the router have deliberately never
 * been evaluated. So it takes no context, no router link and no design token that a
 * provider supplies.
 *
 * It names no key, no value and no URL. The operator's diagnostic is the single console
 * line the bootstrap writes; this is the one sentence a user gets.
 *
 * @returns The boot-failure screen.
 */
export function BootFailure() {
  const {title, message} = toUserMessage({code: 'RuntimeConfigUnavailable'});

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg p-6">
      <div
        role="alert"
        className="max-w-md text-center">
        <h1 className="text-xl font-semibold text-text">{title}</h1>
        <p className="mt-2 text-sm text-text-2">{message}</p>
      </div>
    </main>
  );
}
