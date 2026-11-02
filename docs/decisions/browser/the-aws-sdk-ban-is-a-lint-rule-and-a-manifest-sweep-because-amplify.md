---
type: Decision
title: "The `@aws-sdk/*` ban is a lint rule AND a manifest sweep, because Amplify vendors the SDK (SPEC-202)"
description: "**The `@aws-sdk/*` ban is a lint rule AND a `package.json` sweep.** The rule is declared in **every** clause governing `src/` because flat config REPLACES rather than merges, and the sweep reads the **manifest, never `node_modules`** — Amplify vendors the SDK, so a tree assertion would fail permanently and be deleted. A dependency nobody imports is invisible to an import rule, and that leftover is how the next import arrives."
---

Six specs each deleted a browser-side AWS client. What none of them could see is that **a dependency
nobody imports is invisible to every import rule** — the `package.json` entry outlived its last
importer every time, and nothing went red. That leftover is how the next `@aws-sdk` import arrives:
already installed, already resolvable, one autocomplete away. So the fence is two mechanisms, and
each catches what the other cannot.

**The lint rule is declared four times, and that is the hazard.** ESLint flat config **replaces** a
rule's value at the last entry matching a file rather than merging it, so the layering clause, the
exemption clause and the sibling-feature clause each override the `src/**` clause for the files they
match. Written once, the ban is silently off for `src/lib/**`, `src/components/**`, every test in
those trees and four feature directories — while the config reads as though it holds. The guard
therefore **enumerates** every entry governing `src/` that declares `no-restricted-imports` and
requires the group in each, rather than sampling one. And its scoping question is **inverted** on
purpose: an entry is out of scope only if every glob it names is demonstrably not under `src/`,
because an entry with no `files` at all governs everything, and filtering on a `src/` prefix let
exactly that shape declare the rule without the group while an `@aws-sdk` import in `features/`
linted clean. Tests are **in** scope: a test mocking `@aws-sdk/client-s3` is a test of a call the
app no longer makes.

**The sweep reads `package.json`, never `node_modules`.** `aws-amplify` vendors `@aws-sdk/*`
packages transitively, so an assertion over the installed tree would fail permanently, be deleted
inside a week, and a deleted guard is indistinguishable from a passing one in CI. It carries a
guard-the-guard — the manifest must still name `aws-amplify` — because a parse that read nothing
agrees with an empty manifest.

## History

### 2026-09-02

- **Settled:** SPEC-202.
