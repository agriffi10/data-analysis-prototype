# Feature-flags feature (`apps/portal/src/features/feature-flags/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

> **A FLAG IS PRESENTATION, NEVER AUTHORIZATION.** Turning a feature off hides its tab and its entry
> points; it revokes no IAM grant, no queue permission and no credential scope. **No service and no
> `lib/` module may import this feature** — `featureFlags.service.test.ts` enumerates
> `features/**/*.service.ts` and `lib/**` and fails if one does (SPEC-162 FR-006).

> **The fallback is silent and all-on.** An unusable document resolves to the compiled-in defaults
> and reports `'fallback'`, so a blocked read renders exactly like a healthy environment. Consumers
> get no signal and want none — the accepted cost is that during an outage a deliberate "off" does
> not take effect.

| Symbol | File | Purpose |
|---|---|---|
| `getFeatureFlags(environment)` | `featureFlags.service.ts` | Reads `_config/feature-flags.json` from `userSpaceBucket()` through the shared `readJsonDocument`. **STRICTER than `getUserDirectory()` on purpose:** an unparseable body, a non-object, an unsupported `version`, an unusable `defaults` block and a MISSING object are all `{success: false}` — collapsing them to an empty success would make `'fallback'` unreportable. A single malformed VALUE is tolerated for that key only. `environment` may be `undefined` (an unwired `VITE_ENVIRONMENT`); an unnamed environment resolves to the document's `defaults` and is a SUCCESS. `ServiceResult<FeatureFlags>`, never throws (SPEC-162). |
| `useFeatureFlags()` | `useFeatureFlags.ts` | `{flags, status}`. `flags` always holds all five keys as booleans and holds the compiled-in defaults while the fetch is in flight — everything visible, then something may go away, never the reverse. `staleTime` 1h, `retry: false`, gated on a signed-in user. `status` is `'loading' \| 'ready' \| 'fallback'`. Emits a **dev-only** `console.debug` naming which way the read went (FR-009); stripped from production builds (SPEC-162). |
| `FEATURE_FLAG_DEFAULTS` | `featureFlagDefaults.ts` | What is in force when the document cannot be used: every flag `true`. A test asserts it equals `config/feature-flags.json`'s `defaults` block, so the file and the fallback cannot drift (SPEC-162). |
| `FEATURE_FLAG_KEYS` | `featureFlagDefaults.ts` | The five keys as an iterable. The resolver walks THIS, not the document — which is what guarantees a resolved set is complete whatever the document named (SPEC-162). **ORDER is load-bearing** beyond iteration: `FeatureRoute` offers the first ENABLED feature as its fallback link, so a new key is appended LAST or an existing unavailable page silently changes where it points (SPEC-179). |
| `FEATURE_FLAGS_KEY` | `featureFlags.service.ts` | `_config/feature-flags.json`. The portal role holds `GetObject` here and nothing else (SPEC-162). |
| `featureFlagKeys` | `featureFlagKeys.ts` | TanStack key factory. Carries the ENVIRONMENT, unlike `userDirectoryKeys` — one document resolves differently per environment, and a key that could not tell them apart would serve one under the other's name (SPEC-162). |
| `FeatureFlagKey`, `FeatureFlags`, `FeatureFlagsStatus`, `FeatureFlagDocument` | `featureFlags.types.ts` | The FIVE flag names (`dataExplorer` joined in SPEC-179). **Adding a key lands in SIX places** — these types, `FEATURE_FLAG_KEYS`, `FEATURE_FLAG_DEFAULTS`, `config/feature-flags.json`, `scripts/validate_feature_flags.py`'s `FLAG_KEYS` (which refuses an unknown key) and `lambdas/test_feature_flags_config.py`'s, which re-states the tuple on purpose so a test cannot pass by agreeing with a mistake it imported. **The publish workflow's matrix is NOT one of them** — it is per environment, not per flag. Two of the six are Python, so `pytest lambdas/` is a gate this change has to pass. Also here: the complete resolved set, what consumers branch on, and the published document's shape (SPEC-162). |
| `useFeature(key)` | `useFeature.ts` | **The door.** `boolean`, and `false` while the flags are still loading — a tab that appears then vanishes under the pointer is worse than one that arrives a tick late. `'fallback'` resolves every flag `true`, so an unreadable document is indistinguishable from all-on (SPEC-163). |
| `useFeatureSet()` | `useFeatureSet.ts` | `{isEnabled, status}` for the three consumers that cannot ask ONE question: `Header` (one predicate for two nav components), `FeatureRoute` (must tell "off" from "not known yet"), `LandingPage` (first enabled destination). Exists so `useFeatureFlags` stays internal — **a tripwire test fails if any module outside this feature names it** (SPEC-163). |
| `<FeatureGate flag>` | `FeatureGate.tsx` | Renders children only while the flag is on, and **nothing** otherwise — no wrapper, no placeholder, no `hidden` (a visually-hidden control is still focusable and still announced). Use the hook instead when the absence must change a sibling — a toggle that would become a one-option control (SPEC-163). |
| `GATED_SURFACES` | `gatedSurfaces.ts` | Every surface every flag hides, keyed by flag: accessible NAME, kind (`nav`/`route`/`control`/`guide`), owning route, and `helpId` for guides. **Adding a fifth entry point is a registry edit, not a discovery exercise** — `gatedSurfaces.test.tsx` walks it in both states and fails for a row it cannot make disappear (SPEC-163). |
| `hiddenHelpIds(isEnabled)` / `navDestination(key)` / `NAV_PATH_FLAGS` | `gatedSurfaces.ts` | Derived from the registry, never declared beside it: the help section/guide ids to drop, a flag's own label + path (what the unavailable page says out loud), and the `path → flag` map `Header` builds its predicate from (SPEC-163). |

## Route components (`apps/portal/src/routes/`)

| Symbol | File | Purpose |
|---|---|---|
| `FeatureRoute` | `routes/FeatureRoute.tsx` | Route-level gate: the page, or `FeatureUnavailablePage`. **The page must not mount while the answer is unknown** — every gated page fetches on mount, and on `/data-quality/:space/:requestId` that request would be an existence oracle for someone else's report (SPEC-113). Renders `LoadingState` while the flags resolve, which is why FR-007's "render nothing" applies to nav and controls and not here (SPEC-163). |
| `FeatureUnavailablePage` | `routes/FeatureUnavailablePage.tsx` | "X isn't available in this environment", plus a link to the first ENABLED feature. **Not the 404 page** — the route exists, the feature does not, and a user following a colleague's link has mistyped nothing. Names no reason and offers no appeal route: a flag is presentation, and inventing one would imply a permission model that does not exist (SPEC-163). |
