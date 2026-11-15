import {describe, expect, it} from 'vitest';
import {HELP_SURFACES} from './helpSurfaces';
import {HELP_SECTIONS} from './helpContent';
import {GATED_SURFACES} from '../feature-flags';
import {AREAS} from '../../lib/navigation';

const SOURCE = import.meta.glob('./helpSurfaces.ts', {query: '?raw', import: 'default', eager: true}) as Record<
  string,
  string
>;

describe('HELP_SURFACES', () => {
  it('names a section that exists, for every row', () => {
    const known = new Set(HELP_SECTIONS.map((section) => section.id));
    expect(HELP_SURFACES.length).toBeGreaterThan(0);
    for (const surface of HELP_SURFACES) {
      expect(known.has(surface.sectionId), `${surface.path} → ${surface.sectionId}`).toBe(true);
    }
  });

  it('names a path the app actually routes, for every row', () => {
    // Rendering the header at a path proves the control resolves — it does NOT prove the path
    // is a route, because the header renders the same either way. So a row left behind by a
    // route rename would silently revert that page's control to plain navigation, which is the
    // failure a registry with a walking test exists to stop. The area records name every
    // signed-in path, whichever router serves it.
    const routed = new Set(AREAS.flatMap((record) => record.paths));
    expect(routed.size, 'no area paths were read').toBeGreaterThan(5);

    for (const surface of HELP_SURFACES) {
      expect(routed.has(surface.path), `${surface.path} is in no area record`).toBe(true);
    }
  });

  it('maps each path once', () => {
    const paths = HELP_SURFACES.map((surface) => surface.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('carries no flag information of any kind', () => {
    // The whole point of the split: route→section here, guide→flag in `gatedSurfaces.ts`.
    // Read from disk rather than inferred, because an import that is only used for a type
    // still forks the mapping the day someone reaches for it.
    const [path, source] = Object.entries(SOURCE)[0] ?? [];
    expect(path, 'the source sweep matched nothing').toBeDefined();
    expect(source!.length).toBeGreaterThan(200);

    const imports = [...source!.matchAll(/^\s*import\s[^;]*?from\s+'([^']+)';/gm)].map((m) => m[1]);
    expect(imports, 'the import sweep matched nothing').not.toEqual([]);
    for (const specifier of imports) {
      expect(specifier, `helpSurfaces.ts imports ${specifier}`).not.toMatch(/feature-flags|gatedSurfaces/);
    }
    // Nor does it read one at runtime by any other route.
    expect(source).not.toMatch(/\buseFeature\b|\bhiddenHelpIds\b|\bFEATURE_FLAG/);
  });

  it('adds no row to GATED_SURFACES — the panel is gated by derivation, not declaration', () => {
    // A route the user cannot reach has no panel because its SECTION is already filtered out
    // of `visibleHelpSections`. Declaring it a second time is what this asserts against.
    // The teeth are shared with `gatedSurfaces.test.tsx`, whose per-flag set-equality over row
    // names fails on any row added there at all; this names the reason for a reader arriving
    // from the panel's side.
    const rows = Object.values(GATED_SURFACES).flat();
    expect(rows.filter((row) => /help panel|contextual help/i.test(row.name))).toEqual([]);
  });
});

describe('the Move between pages guide', () => {
  it('says one sign-in covers every tab, beside the account menu that signs out', () => {
    const guide = HELP_SECTIONS.flatMap((section) => section.guides).find(({id}) => id === 'move-between-pages');
    const step = guide?.steps.find((text) => text.includes('<b>Sign out</b>'));

    expect(step).toContain(
      'Signing in once covers every Data Quarry tab in this browser, and <b>Sign out</b> signs out all of them.'
    );
  });
});
