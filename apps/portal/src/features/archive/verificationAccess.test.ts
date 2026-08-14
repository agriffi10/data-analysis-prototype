import {describe, expect, it} from 'vitest';
// Read through Vite's own `?raw` rather than `node:fs`: the app tsconfig carries no node types,
// so `tsc -b` — the only typecheck CI runs — rejects an fs import here. Same mechanism
// `archiveWriteLock.test.ts` uses, and this file lives beside it for the same reason: the
// archive plane is what the access below exists to verify.
import verificationPolicy from '../../../../../infra/modules/verification/policies/verification-role.json.tftpl?raw';
import portalRolePolicy from '../../../../../infra/modules/data/policies/portal-role-permissions.json.tftpl?raw';

/**
 * SPEC-186 FR-004 AC4, as an executable claim rather than a promise in a comment.
 *
 * The requirement was to make two owed assertions POSSIBLE without widening the data path, and
 * "read-only, no grant on any data bucket" is the whole difference between a verification
 * principal and a back door. It is checkable: the policy is a document, and what must not be
 * in it is enumerable.
 *
 * `${…}` placeholders are left as-is — the assertions below are about ACTIONS and about which
 * variables appear, and every variable this policy interpolates is named here.
 */
const policy = JSON.parse(
  verificationPolicy.replace(/\$\{(\w+)\}/g, (_match, name: string) => `PLACEHOLDER_${name}`)
) as {
  Statement: {Sid: string; Effect: string; Action: string[] | string; Resource: string[] | string}[];
};

const actions = policy.Statement.flatMap((s) => (Array.isArray(s.Action) ? s.Action : [s.Action]));
const resources = policy.Statement.flatMap((s) => (Array.isArray(s.Resource) ? s.Resource : [s.Resource]));

describe('the verification role (SPEC-186 FR-004)', () => {
  it('grants nothing but reads', () => {
    // Not a list of forbidden verbs — a rule about the verb itself, so an action nobody thought
    // of is caught too. A `Get`/`List`/`Describe` prefix is the whole allowed vocabulary.
    const notARead = actions.filter((a) => !/:(Get|List|Describe)[A-Z]/.test(a));
    expect(notARead).toEqual([]);
  });

  it('names no data bucket, and no wildcard resource', () => {
    // The three buckets that hold user data, and the archive vault itself. The role may read
    // the TRAIL, which records calls against the vault; it may not read the vault.
    for (const resource of resources) {
      expect(resource).not.toBe('*');
      expect(resource).not.toMatch(/user-space|shared-space|athena-admin/);
      // `archive-audit` is the trail bucket and is allowed; a bare `archive` bucket is not.
      expect(resource).not.toMatch(/:::.*-archive(\/|$)/);
    }
  });

  it('never asks Lake Formation to vend data credentials', () => {
    // `lakeformation:GetDataAccess` is the credential vend for reading a table's DATA. Its
    // absence is what keeps a DESCRIBE grant from becoming a read of everything the catalog
    // points at — and it is easy to add "to make GetTable work", which it is not needed for.
    expect(actions).not.toContain('lakeformation:GetDataAccess');
    expect(actions.filter((a) => a.startsWith('lakeformation:'))).toEqual([]);
  });

  it('can read the catalog back — which is the point of it existing', () => {
    // SPEC-149's Description/column-comment preservation check and SPEC-153's owed foreign
    // projection fixture are exactly these two calls. A policy that granted nothing would pass
    // every assertion above.
    expect(actions).toContain('glue:GetTable');
    expect(actions).toContain('glue:GetTableVersions');
    expect(policy.Statement.map((s) => s.Sid)).toContain('ArchiveAuditRead');
  });

  it('scopes the catalog reads to the DATABASE and TABLE ARNs, not to `catalog/*`', () => {
    // THE ONE THAT WOULD HAVE SHIPPED BROKEN. Glue has no `catalog/*` hierarchy: `GetTable`
    // and `GetTableVersions` each need the database ARN and the table ARN alongside the
    // catalog, which is the shape `portal-role-analytics` and the table-builder execution role
    // already use. The first version scoped to `catalog` + `catalog/*`, which APPLIES CLEANLY
    // and then denies at runtime — the read-back stays blocked with no gate having failed,
    // which is the exact class of defect this spec exists to close.
    //
    // Asserting the ACTIONS alone (the test above) could not catch it. This one asks what the
    // actions are allowed ON.
    const catalogStatement = policy.Statement.find((s) => s.Sid === 'CatalogReadBack')!;
    const scoped = Array.isArray(catalogStatement.Resource) ? catalogStatement.Resource : [catalogStatement.Resource];

    expect(scoped.some((r) => /:catalog$/.test(r))).toBe(true);
    expect(scoped.some((r) => /:database\/\*$/.test(r))).toBe(true);
    expect(scoped.some((r) => /:table\/\*\/\*$/.test(r))).toBe(true);
    // The shape that does not exist, and that a reviewer reading only the action list misses.
    expect(scoped.some((r) => /:catalog\/\*$/.test(r))).toBe(false);
  });

  it('does not appear in portal-role-permissions', () => {
    // FR-004 AC4. The isolation policy is the browser's grants; verification access is a
    // separate principal a human assumes, and the two must never meet.
    expect(portalRolePolicy).not.toMatch(/verification/i);
    expect(portalRolePolicy).not.toMatch(/archive-audit/i);
    expect(portalRolePolicy).not.toMatch(/cloudtrail/i);
  });
});
