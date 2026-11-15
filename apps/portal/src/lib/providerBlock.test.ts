import {describe, it, expect} from 'vitest';
import {OPTIONAL_CONFIG, REQUIRED_CONFIG} from '../types/runtimeConfig.types';

/**
 * The API's token verifier is configured server-side, and the browser's document must
 * carry none of it.
 *
 * The browser verifies nothing — it sends an ID token it already holds. The moment the
 * SPA needs an issuer, an audience or a JWKS URI, the design has gone wrong. The converse
 * holds too: a verifier configured by reading the browser's document has a
 * client-supplied trust anchor.
 *
 * THE EXCLUSION CUTS ONE WAY ONLY, and that is the whole subtlety. The four Cognito
 * values in the document are Amplify's, they are legitimately browser-side, and a rule
 * written to forbid "anything that smells of identity" deletes them and breaks sign-in.
 */

/** Field names that belong to the API's verifier and must never appear in the document. */
const FORBIDDEN_EXACT = [
  'issuer',
  'oidcIssuer',
  'audience',
  'oidcAudience',
  'jwksUri',
  'discoveryUrl',
  'authorizeUrl',
  'tokenUrl',
  'clientSecret',
  'usernameClaim',
  'identityCenterApplicationArn',
  'trustedTokenIssuerArn'
];

/**
 * Substrings that make a key a trust anchor whatever it is called.
 *
 * DELIBERATELY NOT `client`, `clientId`, `domain` or `redirect`. Each would flag a value
 * Amplify legitimately reads, and the visible result would not be a failing test — it
 * would be a Hosted UI round trip that never completes.
 */
const FORBIDDEN_SUBSTRINGS = ['oidc', 'issuer', 'audience', 'jwks', 'secret'];

/** Whether a key names something the API's verifier owns. */
function isProviderBlockField(key: string): boolean {
  const lower = key.toLowerCase();
  return (
    FORBIDDEN_EXACT.some((name) => name.toLowerCase() === lower) ||
    FORBIDDEN_SUBSTRINGS.some((fragment) => lower.includes(fragment))
  );
}

describe('the provider block never crosses into the browser', () => {
  it('flags nothing in the document', () => {
    const flagged = [...REQUIRED_CONFIG, ...OPTIONAL_CONFIG].filter(isProviderBlockField);

    expect(flagged).toEqual([]);
  });

  it('flags every name on the exact list', () => {
    // GUARDS THE GUARD, and it has to be DERIVED from the list rather than a hand-picked
    // sample: five of these — `discoveryUrl`, `authorizeUrl`, `tokenUrl`, `usernameClaim`,
    // `identityCenterApplicationArn` — match no substring rule, so they are reachable only
    // through the exact clause. Measured: with a sample, deleting that clause outright left
    // every case in this file green.
    expect(FORBIDDEN_EXACT.filter(isProviderBlockField)).toEqual(FORBIDDEN_EXACT);
  });

  it('flags a synthetic key that is on neither list but IS a trust anchor', () => {
    // The substring half, and the case that keeps the checker honest about names nobody
    // enumerated: `apiAudience` appears in neither list. A checker that flags nothing
    // passes the "document is clean" case forever, and this repo's review history records
    // exactly that defect shape more than once.
    const synthetic = ['apiAudience', 'myOidcThing', 'signingJwks', 'sharedSecret'];

    expect(synthetic.filter(isProviderBlockField)).toEqual(synthetic);
  });
});
