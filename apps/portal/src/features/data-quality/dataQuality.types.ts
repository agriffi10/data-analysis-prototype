/** Which space a quality check targets (SPEC-109 FR-001). */
export type DataQualitySpaceKind = 'personal' | 'shared';

export type DataQualitySpace = {
  kind: DataQualitySpaceKind;
  bucket: string;
  /** The space root prefix: `{username}/` or `{spaceName}/`. */
  prefix: string;
};

export type DataQualityRequest = {
  /** UUIDv4, browser-minted. Keys the manifest, the intermediate results, and the report. */
  requestId: string;
  space: DataQualitySpace;
  /** The file or folder key to check, relative to the bucket. */
  location: string;
};

/**
 * The wire envelope. `idToken` is attached at send time and never stored.
 *
 * There is deliberately NO actor/username field: the actor is derived server-side from
 * the verified token claim, so a body cannot assert an identity (SPEC-109 FR-001).
 */
export type DataQualityMessage = DataQualityRequest & {idToken: string};
