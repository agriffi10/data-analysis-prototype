/**
 * The archive id's shape, checked before enqueue.
 *
 * The SERVER validates it again — `arcommon.paths.validated_archive_id`, before the value is
 * concatenated into any key — and that is the boundary. This copy exists so a typo costs the
 * user a sentence now rather than a notification hours later, which on this plane is the whole
 * difference: a restore that fails at the front door still spent none of the 3-5 hours.
 */
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Is this a well-formed archive id? Held to the SAME pattern the control plane uses, rather than
 * a laxer "looks like a uuid" — a second, looser rule in the browser would report a value as
 * valid that the plane then refuses, which is the failure this check exists to prevent.
 */
export function isArchiveId(value: string): boolean {
  return UUID_V4.test(value.trim());
}
