import {describe, expect, it} from 'vitest';

/**
 * Every IAM policy template in `infra/`, as raw text: each module's `policies/`, each control
 * plane's own templates under `planes/` — less its state-machine definition, which is not an IAM
 * document and is never sent to `CreatePolicy` — and each standalone function's under `functions/`.
 *
 * Read through Vite's own `?raw` glob rather than `node:fs`: the app tsconfig carries no node
 * types, so `tsc -b` — the only typecheck CI runs — rejects an fs import here.
 */
const TEMPLATES = import.meta.glob(
  [
    '/../../infra/modules/*/policies/*.json.tftpl',
    '/../../infra/planes/*/*.tftpl',
    '/../../infra/functions/*/*.tftpl',
    '!/../../infra/planes/*/*.asl.json.tftpl'
  ],
  {
    query: '?raw',
    import: 'default',
    eager: true
  }
) as Record<string, string>;

/**
 * SPEC-186. **An IAM policy document must contain only printable ASCII**, and nothing before
 * `CreatePolicy` says so: `tofu validate` passes, the plan renders, the JSON is well-formed, and
 * the apply fails with `ValidationError: It must contain only printable ASCII characters`.
 *
 * That is how this spec's own first apply of `modules/verification` went red — a `"//"` comment
 * key inside the document carrying an em dash. The comments moved into the `.tf` files, which is
 * where every other policy in this repo already keeps them, and this holds the line: the failure
 * costs a full deploy cycle to discover and is invisible to every local gate.
 */
describe('IAM policy templates are printable ASCII (SPEC-186)', () => {
  const entries = Object.entries(TEMPLATES);

  it('guards the guard — the glob resolves to the real templates', () => {
    // Without this, a glob that matched nothing would make the sweep below pass vacuously.
    expect(entries.length).toBeGreaterThan(10);
    expect(entries.some(([path]) => path.includes('portal-role-permissions'))).toBe(true);
    expect(entries.some(([path]) => path.includes('/planes/') && path.endsWith('/execution.json.tftpl'))).toBe(true);
    expect(entries.some(([path]) => path.endsWith('.asl.json.tftpl'))).toBe(false);
  });

  it.each(entries)('%s contains only printable ASCII', (_path, source) => {
    // Tab, newline and carriage return are the only control characters a JSON document needs;
    // everything else must sit in the printable range. A failure names the offending characters
    // rather than just the file, because an em dash is invisible in a diff.
    const offenders = [...source].filter((ch) => {
      const code = ch.codePointAt(0)!;
      if (ch === '\t' || ch === '\n' || ch === '\r') return false;
      return code < 0x20 || code > 0x7e;
    });
    expect([...new Set(offenders)]).toEqual([]);
  });
});
