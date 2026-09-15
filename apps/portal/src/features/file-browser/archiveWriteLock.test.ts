import {describe, expect, it} from 'vitest';
// Read through Vite's own `?raw` rather than `node:fs`: the app tsconfig carries no node types,
// so `tsc -b` — the only typecheck CI runs — rejects an fs import here.
import portalRolePolicy from '../../../../../infra/modules/data/policies/portal-role-permissions.json.tftpl?raw';
import analyticsPolicy from '../../../../../infra/modules/analytics/policies/portal-role-analytics.json.tftpl?raw';
import sharedSpacePolicy from '../../../../../infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl?raw';
import {isWriteLockedPrefix, writeLockRefusal} from './writeLockedPrefix';
import {
  HIDDEN_BROWSER_FOLDERS,
  isRootFolderNamed,
  PICKER_LOCKED_FOLDERS,
  undeletableRootFolderRefusal
} from './protectedFolders';

/**
 * SPEC-172 FR-004's last acceptance criterion, executable on BOTH sides.
 *
 * The browser must not offer a write the policy refuses, and must not refuse one it permits — with
 * one deliberate exception, the query results folder held below, where the policy permits the
 * write and refuses the delete.
 * That is not a claim about a string — it is a claim about two rules agreeing over keys — so the
 * IAM resource is turned into a matcher here and the app's own predicate is run against the same
 * keys. A test that merely asserted the `.tftpl` contains `archive` would pass with the predicate
 * deleted.
 *
 * The two buckets are denied DIFFERENTLY and that asymmetry is the whole reason this file exists:
 * the personal Deny is anchored at the caller's own root (in that bucket the prefix IS the
 * principal tag), while the shared one puts a wildcard where the space name goes — and an S3
 * resource wildcard matches `/`, so it reaches an `archive` folder at any depth.
 */

/** The Resource string of the named Sid, as text — the shared template renders to JSON, it is not JSON. */
function resourceOf(body: string, sid: string): string {
  const start = body.indexOf(`"Sid": "${sid}"`);
  expect(start, `no ${sid} statement`).toBeGreaterThan(-1);
  const nextSid = body.indexOf('"Sid"', start + 1);
  const statement = body.slice(start, nextSid === -1 ? undefined : nextSid);
  // The slice runs to the next `"Sid"`, which is safe only while every statement carries one. A
  // statement with no Sid of its own, between this one and the next, is what makes it run on — and
  // it brings a second `"Effect"` with it, which a slice LENGTH cannot see.
  expect(
    statement.match(/"Effect"/g)?.length,
    `the ${sid} slice covers more than one statement, so the Resource read below may belong to a neighbour`
  ).toBe(1);
  // A matcher built from an ALLOW's Resource would compare the predicate against a permission
  // rather than a refusal, which is a precondition of this matcher's MEANING and not a restatement
  // of a policy rule.
  expect(/"Effect":\s*"Deny"/.test(statement), `${sid} is not a Deny, so its Resource is a grant`).toBe(true);
  const resource = /"Resource":\s*"([^"]+)"/.exec(statement);
  expect(resource, `${sid} has no single-string Resource`).not.toBeNull();
  return resource![1];
}

/**
 * The IAM resource as a key matcher: everything after the bucket ARN, with `*` matching ANY
 * characters — including `/`, which is the property that makes the shared Deny reach any depth
 * and is exactly what an intuition about globs gets wrong.
 */
function keyMatcher(resource: string, principal: string): (key: string) => boolean {
  // With no bucket ARN to strip, the slice keeps the bucket in the pattern and the matcher answers
  // false for every key — a total disagreement the table would report as the predicate's fault.
  const bucketEnd = resource.indexOf('}/');
  expect(bucketEnd, `no bucket ARN placeholder in ${resource}`).toBeGreaterThan(-1);
  const keyPart = resource
    .slice(bucketEnd + 2)
    // The principal tag, as it survives BOTH stages: `$${aws:PrincipalTag/username}` in the
    // template escapes to `${aws:PrincipalTag/username}` in the rendered policy, and at request
    // time IAM substitutes the caller's own username for it.
    .replace('$${aws:PrincipalTag/username}', principal)
    .replace('${aws:PrincipalTag/username}', principal);
  // No policy variable may survive: one left standing is compared against keys as a literal. Asked
  // of `${` rather than of the tag name above, because the substitution is only the reachable case
  // — a renamed tag key, a default value like `${aws:PrincipalTag/team, 'all'}`, and the `${*}`
  // escape for a LITERAL asterisk all pass a check that names one variable. The escape is the
  // dangerous direction: the split below would read it as a wildcard and cover MORE keys than the
  // Deny, which is how a predicate that permits what IAM refuses would pass.
  expect(keyPart, `a policy variable survived substitution in ${resource}`).not.toContain('${');
  // IAM's OTHER wildcard, which this matcher does not model: `?` matches any single character
  // within an ARN segment, and the escape below would turn it into a literal, leaving the matcher
  // covering FEWER keys than the Deny does. A limitation of this matcher, not a rule about the
  // policy — neither template uses one today, and the disagreement it would report would be
  // spurious rather than a missed refusal.
  expect(keyPart, `${resource} uses \`?\`, which this matcher does not model`).not.toContain('?');
  const pattern = keyPart
    .split('*')
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('[\\s\\S]*');
  return (key: string) => new RegExp(`^${pattern}$`).test(key);
}

/**
 * The union of every Deny naming the receipt folder in one template.
 *
 * It wrapped two matchers while the folder had two homes and IAM refused each with its own
 * statement. One home, one statement, one matcher — and it stays a union because what it expresses
 * is "every Deny naming this folder", so a second statement returning would otherwise go
 * unmeasured by every row below.
 */
function anyOf(...matchers: ((key: string) => boolean)[]): (key: string) => boolean {
  return (key) => matchers.some((matches) => matches(key));
}

/**
 * Every Sid in a template whose statement denies something under an `archive` folder.
 *
 * The union below NAMES its Sids rather than deriving them, which is what keeps a deleted statement
 * loud — a derived list would shrink along with the thing it derives from and go on passing. This is
 * the other half of that trade: a third archive Deny added to either template would be unioned by
 * nothing, and the matcher would keep agreeing with the two it knows about while the browser
 * predicate was held to less than the policy says.
 *
 * Reach: statements whose `"Sid"` is their FIRST key, which is how every Sid-slicing reader here
 * finds them. One written with `"Sid"` last is invisible to this AND to the matchers above —
 * measured, an any-depth archive Deny written that way leaves every row below green — so that
 * shape has to be refused where statements are counted, which is not this file.
 */
function archiveDenySids(body: string): Set<string> {
  const found = new Set<string>();
  for (const match of body.matchAll(/"Sid":\s*"([^"]+)"/g)) {
    const end = body.indexOf('"Sid"', match.index + match[0].length);
    const statement = body.slice(match.index, end === -1 ? undefined : end);
    if (!/"Effect":\s*"Deny"/.test(statement)) continue;
    // The RESOURCE names the folder, so a `/archive/` sitting in an `s3:prefix` Condition is not
    // one of these. Read as a whole path SEGMENT, because `/archive/*` is merely the spelling used
    // today: a Deny spelled `/archive*` reaches `alice/backups/archive/whatever.csv`, which is a key
    // the table below asserts IAM PERMITS, and a bare `/archive` names the folder as an object.
    // `/archived-notes/*` names a different folder and is not one of these.
    const resource = /"Resource":\s*(\[[^\]]*\]|"[^"]*")/.exec(statement);
    const named = [...(resource?.[1] ?? '').matchAll(/"([^"]*)"/g)];
    if (named.some(([, one]) => /\/archive([/*]|$)/.test(one))) {
      found.add(match[1]);
    }
  }
  return found;
}

// One Sid per bucket again. The narrowing deleted the depth-one statement of each pair and the
// survivor kept its `…SystemSettings` name, so each union now wraps one matcher. `anyOf` stays:
// what it expresses is "every Deny naming this folder", and a second statement returning would
// otherwise be unmeasured by the rows below.
const PERSONAL_DENY = anyOf(
  keyMatcher(resourceOf(portalRolePolicy, 'ArchiveReceiptsAreNotUserWritableSystemSettings'), 'alice')
);
const SHARED_DENY = anyOf(
  keyMatcher(resourceOf(sharedSpacePolicy, 'SharedArchiveReceiptsAreNotUserWritableSystemSettings'), 'finance')
);

/** An upload into `prefix` writes this key — which is what IAM actually judges. */
const uploadedKey = (prefix: string) => `${prefix}whatever.csv`;

describe('the UI write gate and the IAM Deny agree on the same prefixes', () => {
  const personal = [
    'alice/',
    'alice/archive/',
    'alice/archive/3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93/',
    'alice/reports/',
    // A user's own folder that happens to be called `archive`. The personal Deny is anchored at
    // the root, so IAM PERMITS a write here — and the browser must not refuse it.
    'alice/backups/archive/',
    'alice/archived-notes/',
    // A nested copy of the PAIR. IAM still permits it here — the personal Deny is root-anchored,
    // so depth is what refuses, not the name — and it is the row that tells the two arms apart.
    'alice/backups/system_settings/archive/',
    // The home, refused by the surviving statement. The bare settings prefix is NOT denied — no
    // statement names it — so the browser must still offer it.
    'alice/system_settings/',
    'alice/system_settings/archive/',
    'alice/system_settings/archive/3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93/'
  ];

  it.each(personal)('personal: %s', (prefix) => {
    expect(isWriteLockedPrefix(prefix, 'alice/', 'personal')).toBe(PERSONAL_DENY(uploadedKey(prefix)));
  });

  const shared = [
    'finance/',
    'finance/archive/',
    'finance/archive/3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93/',
    'finance/reports/',
    // A user's own folder called `archive` in a SHARED space. The Deny that used to reach it at
    // any depth is gone, so IAM permits a write here now — the row that catches an arm still
    // keyed on the bare folder name, which is how this rule was written until the narrowing.
    'finance/backups/archive/',
    'finance/archived-notes/',
    // The wildcard is the SPACE slot and matches `/`, so IAM refuses the PAIR at any depth here
    // where it permits the personal twin above. Averaging the two rules gets one of these wrong.
    'finance/backups/system_settings/archive/',
    'finance/system_settings/',
    'finance/system_settings/archive/',
    'finance/system_settings/archive/3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93/'
  ];

  it.each(shared)('shared: %s', (prefix) => {
    expect(isWriteLockedPrefix(prefix, 'finance/', 'shared')).toBe(SHARED_DENY(uploadedKey(prefix)));
  });

  it('proves the two Denies really do differ, so the asymmetry above is not an artefact', () => {
    // If this ever fails, one of the policies changed shape and the predicate should follow it
    // rather than the table above being edited to agree with a rule nobody re-read.
    expect(PERSONAL_DENY('alice/backups/system_settings/archive/x.csv')).toBe(false);
    expect(SHARED_DENY('finance/backups/system_settings/archive/x.csv')).toBe(true);
  });

  it('proves the surviving Deny covers the home and NOT the name it left', () => {
    // This replaces the pair that discriminated the two halves of the old union. With one half
    // left the question changes: not which of the two carries the home, but whether the survivor
    // refuses where the receipts are and stops refusing where they no longer are. The second
    // clause IS the narrowing — false, and a user's own `archive/` is still unwritable.
    const personal = keyMatcher(
      resourceOf(portalRolePolicy, 'ArchiveReceiptsAreNotUserWritableSystemSettings'),
      'alice'
    );
    const shared = keyMatcher(
      resourceOf(sharedSpacePolicy, 'SharedArchiveReceiptsAreNotUserWritableSystemSettings'),
      'finance'
    );

    expect(personal('alice/system_settings/archive/x.csv')).toBe(true);
    expect(personal('alice/archive/x.csv')).toBe(false);
    expect(shared('finance/system_settings/archive/x.csv')).toBe(true);
    expect(shared('finance/archive/x.csv')).toBe(false);
  });

  it('names every archive Deny the Sid slicing can see, so a third one is not unioned by nothing', () => {
    // If this fails because a legitimate new Deny landed, union it into the matchers above rather
    // than widening the sets here — the point is that the enumeration cannot fall behind the
    // templates while every row above goes on passing.
    expect(archiveDenySids(portalRolePolicy)).toEqual(new Set(['ArchiveReceiptsAreNotUserWritableSystemSettings']));
    expect(archiveDenySids(sharedSpacePolicy)).toEqual(
      new Set(['SharedArchiveReceiptsAreNotUserWritableSystemSettings'])
    );
  });

  it('matches the wildcard against a slash, which is the trap in reading these resources', () => {
    // `*` in an S3 resource ARN is not a shell glob. A matcher that stopped at `/` would make
    // every shared row above agree with a root-anchored predicate, and the test would pass while
    // the browser offered writes IAM refuses.
    expect(SHARED_DENY('finance/a/b/c/system_settings/archive/x.csv')).toBe(true);
  });
});

/**
 * The query results folder is the second prefix the browser refuses writes into, for the opposite
 * reason: IAM PERMITS the write and denies the DELETE, so whatever the user puts there cannot be
 * removed. Its Denies have the receipt folder's shape — root-anchored in a personal space, any depth
 * in a shared one — and are held the same way, as a matcher run over the same keys as the rule.
 *
 * Compared on the refusal's WORDS rather than on a boolean, because both folders now feed one
 * refusal: a row inside the receipt folder is refused too, and only the sentence says which rule
 * answered. The analytics template names the tag key through a variable, rendered here to the
 * spelling `keyMatcher` substitutes.
 */
describe('the results refusal and the results DeleteObject Deny agree on the same prefixes', () => {
  const rendered = (sid: string) => resourceOf(analyticsPolicy, sid).replace('${principal_tag_key}', 'username');
  const PERSONAL_RESULTS_DENY = keyMatcher(rendered('ResultsNoDeleteSystemSettings'), 'alice');
  const SHARED_RESULTS_DENY = keyMatcher(
    resourceOf(sharedSpacePolicy, 'SharedResultsNoDeleteSystemSettings'),
    'finance'
  );
  const namesResults = (refusal: string | null) => /query results/i.test(refusal ?? '');

  const personal = [
    'alice/',
    'alice/system_settings/',
    'alice/system_settings/athenaresults/',
    'alice/system_settings/athenaresults/2026/09/',
    // The depth-one name the folder left, and a nested copy of the pair: the personal Deny is
    // root-anchored, so IAM lets the user delete what they write in either.
    'alice/athenaresults/',
    'alice/backups/system_settings/athenaresults/',
    'alice/system_settings/athenaresults-old/',
    // Refused, but by the receipt rule — so it must not be answered with the results sentence.
    'alice/system_settings/archive/'
  ];

  it.each(personal)('personal: %s', (prefix) => {
    expect(namesResults(writeLockRefusal(prefix, 'alice/', 'personal'))).toBe(
      PERSONAL_RESULTS_DENY(uploadedKey(prefix))
    );
  });

  const shared = [
    'finance/',
    'finance/system_settings/',
    'finance/system_settings/athenaresults/',
    'finance/athenaresults/',
    // The wildcard is the space slot and matches `/`, so the pair is undeletable at any depth here.
    'finance/backups/system_settings/athenaresults/',
    'finance/system_settings/athenaresults-old/',
    'finance/system_settings/archive/'
  ];

  it.each(shared)('shared: %s', (prefix) => {
    expect(namesResults(writeLockRefusal(prefix, 'finance/', 'shared'))).toBe(SHARED_RESULTS_DENY(uploadedKey(prefix)));
  });

  it('proves the two results Denies differ at depth, so the shared rows are not an artefact', () => {
    expect(PERSONAL_RESULTS_DENY('alice/backups/system_settings/athenaresults/x.csv')).toBe(false);
    expect(SHARED_RESULTS_DENY('finance/backups/system_settings/athenaresults/x.csv')).toBe(true);
  });
});

describe('the refusal explains itself rather than just disappearing', () => {
  it('gives a reason exactly where it locks, and none where it does not', () => {
    expect(writeLockRefusal('alice/system_settings/archive/', 'alice/', 'personal')).toMatch(/read-only/i);
    expect(writeLockRefusal('alice/reports/', 'alice/', 'personal')).toBeNull();
    // The name it left, which the narrowing handed back to the user.
    expect(writeLockRefusal('alice/archive/', 'alice/', 'personal')).toBeNull();
  });

  it('says what the folder is FOR, because a bare "not allowed" invites a support ticket', () => {
    expect(writeLockRefusal('alice/system_settings/archive/', 'alice/', 'personal')).toMatch(/receipts/i);
  });
});

describe('the folder-name lists archive joined, and the two it did not', () => {
  it('is never a paste destination', () => {
    expect(PICKER_LOCKED_FOLDERS).toContain('archive');
    // The list is still keyed on the folder NAME; what changed is where that name resolves to,
    // because `isRootFolderNamed` builds its prefix from `appManagedPrefixes`.
    expect(isRootFolderNamed('alice/system_settings/archive/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(true);
    expect(isRootFolderNamed('alice/archive/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(false);
  });

  it('is undeletable and unrenameable AT ITS OWN LOCATION ONLY', () => {
    expect(undeletableRootFolderRefusal('alice/system_settings/archive/', 'alice/', 'delete')).toMatch(/receipts/i);
    expect(undeletableRootFolderRefusal('alice/system_settings/archive/', 'alice/', 'move')).toMatch(/receipts/i);
    // A user's own nested folder of the same name is an ordinary folder for these two lists —
    // which is a different question from whether it can be WRITTEN into, answered above.
    expect(undeletableRootFolderRefusal('alice/backups/archive/', 'alice/', 'delete')).toBeNull();
    // And so is the depth-one name the folder vacated: the receipts are not there any more, and
    // a user who makes a folder called `archive` at their space root owns it.
    expect(undeletableRootFolderRefusal('alice/archive/', 'alice/', 'delete')).toBeNull();
  });

  it('stays VISIBLE, because the folder names are the archive ids', () => {
    // Hiding it would remove the only surface that carries an id a restore needs — which is also
    // why there is no archive index and no picker of past archives (spec Out of Scope). Asserted
    // as ABSENCE from the hiding list: the first version of this test re-asserted the write lock
    // instead, which says nothing about visibility and passed with `archive` hidden (measured).
    expect(HIDDEN_BROWSER_FOLDERS).not.toContain('archive');
  });
});
