import type {ErrorParams} from './apiContract.generated';

/**
 * Cross-cutting result shape for service-layer functions. Services never throw —
 * they return this discriminated union and callers branch on `success`.
 */
export type ServiceResult<T> =
  | {success: true; data: T}
  | {
      success: false;
      error: {
        message: string;
        code?: string;
        /**
         * Typed values a service composes its own wording from — the colliding name, the bound
         * that was hit. Never a sentence and never rendered directly: five of
         * `errorMessages.ts`'s `passthrough` codes belong to the object surface and may not
         * travel on the wire, so the values behind them travel here and the service mints the
         * message the app already ships.
         */
        params?: ErrorParams;
      };
    };
