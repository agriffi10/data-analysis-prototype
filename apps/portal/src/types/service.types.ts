// Cross-cutting result shape for service-layer functions. Services never throw —
// they return this discriminated union and callers branch on `success`.
export type ServiceResult<T> = {success: true; data: T} | {success: false; error: {message: string; code?: string}};
