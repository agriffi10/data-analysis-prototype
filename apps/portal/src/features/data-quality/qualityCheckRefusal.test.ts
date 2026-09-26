import {describe, expect, it} from 'vitest';
import {QUALITY_CHECK_RESERVED_REFUSAL, qualityCheckRefusal} from './qualityCheckRefusal';

describe('qualityCheckRefusal', () => {
  it('refuses what sits under a folder the plane reserves, at the space root, by name', () => {
    expect(qualityCheckRefusal('alice/shared_tables/sales/', 'alice/')).toBe(QUALITY_CHECK_RESERVED_REFUSAL);
    expect(qualityCheckRefusal('team/system_settings/athenaresults/q1.csv', 'team/')).toBe(
      QUALITY_CHECK_RESERVED_REFUSAL
    );
  });

  it('admits a user folder that merely shares a reserved name deeper down', () => {
    // The plane's rule is a FIRST-SEGMENT test, so a nested folder of the same name is the user's own.
    expect(qualityCheckRefusal('alice/projects/shared_tables/', 'alice/')).toBeUndefined();
    expect(qualityCheckRefusal('alice/sales.csv', 'alice/')).toBeUndefined();
  });
});
