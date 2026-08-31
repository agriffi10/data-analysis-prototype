/**
 * The runtime configuration document's shape, and the classification that decides
 * what boots.
 *
 * Every value is a string. The ECS task environment that renders this document is
 * strings, and a JSON number would introduce a second parse path with its own failure
 * mode for the one numeric-looking key (`maxUploadBytes`, already parsed at its call
 * site). `version` is the sole exception.
 */

/**
 * Variables the portal cannot work at all without: the API's origin, the region every
 * SDK client needs, the three Cognito values that make sign-in possible, the app's own
 * URL, the bucket every read and write targets, and the workgroup every query runs in.
 *
 * `apiBaseUrl` joined the day the first feature was ported. Its degraded path is not
 * partial — a portal that cannot reach the API cannot suggest a username, and every
 * later port widens that — so it belongs with the values whose absence stops the app
 * rather than one feature.
 *
 * The queue URLs are gone from this document entirely — the browser no longer writes a queue,
 * so the URLs are the API function's configuration and an unset one is an operator fault it
 * reports rather than a feature that quietly disables itself. Not here either is
 * the shared-space bucket (a user may belong to no shared space). The test for
 * membership is whether SOMETHING catches its absence and says so — not whether the
 * app is useful without it.
 */
export const REQUIRED_CONFIG = [
  'apiBaseUrl',
  'appUrl',
  'awsRegion',
  'userSpaceBucket',
  'cognitoUserPoolId',
  'cognitoUserPoolClientId',
  'cognitoDomain'
] as const;

/** Set in a working deployment, but each with its own degraded path when absent. */
export const OPTIONAL_CONFIG = [
  // Which block of the feature-flag document this deployment resolves. Optional because
  // its degraded path is total: an unset value resolves to the document's own `defaults`
  // and still reports 'ready'. A deployment that ships it unset silently ignores every
  // per-environment override, which is why the flags feature owes a live check.
  'environment',
  'maxUploadBytes',
  'sharedSpaceBucket'
] as const;

export type RequiredConfigKey = (typeof REQUIRED_CONFIG)[number];
export type OptionalConfigKey = (typeof OPTIONAL_CONFIG)[number];
export type RuntimeConfigKey = RequiredConfigKey | OptionalConfigKey;

/** The served document. Every value is a string; `version` is the sole number. */
export type RuntimeConfigDocument = {
  version: number;
} & Partial<Record<RuntimeConfigKey, string>>;

/**
 * Why a load failed, as a machine reason.
 *
 * Deliberately NOT a `ServiceResult`: that shape carries a user-facing `message`, and
 * the boot failure's wording must come from `toUserMessage` at the render site, so the
 * loader is the wrong place to author a sentence.
 */
export type RuntimeConfigLoadFailure =
  | {reason: 'unreachable'}
  | {reason: 'unparseable'}
  | {reason: 'unsupported-version'; found: unknown}
  | {reason: 'missing-required'; missing: RequiredConfigKey[]};

export type RuntimeConfigLoad = {ok: true} | ({ok: false} & RuntimeConfigLoadFailure);
