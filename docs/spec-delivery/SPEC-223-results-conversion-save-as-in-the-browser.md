# Completed Spec — SPEC-223: Results Conversion, "Save as" in the Browser, the Flag & Help

## What was completed?

The plane converted; now a user can ask it to. **Save results to my files** — one dialog, mounted on
both the Query workspace and the Data Explorer — gained a **Format**. CSV stays the instant
server-side copy it always was, byte for byte; Parquet, JSON and Excel go to the results-conversion
plane and come back as a notification with a link to the folder.

- **`normalizeResultsName(name, format)`** and one `RESULTS_FORMATS` label/extension map, replacing
  `normalizeCsvName`. It **replaces** another format's extension rather than stacking onto it,
  because the format is a control the user can change after typing a name.
- **`resultsConversion.service.ts`**, and an object-level **`objectExists`** beside `folderExists` —
  the pre-flight probe, in which a **403 counts as occupied**.
- **`useSaveResults` routes on the format**, and both dialogs above it needed nothing but the field.
- **The `resultsConversion` flag**, its two registry rows and the both-states walk.
- **The notification link now refreshes the folder it lands on**, as a mechanism over any `/files`
  link rather than a clause for this plane.
- Help on both surfaces, and the live checks in `e2e.md` §4.3, §4.5 and §4.14.

### Deliberate deviations

- **The plane's destination prefix is relative to the space root**; the picker's is absolute.
  Passing one through writes `alice/alice/reports/…` and **nothing refuses it** — `assert_inside_root`
  only proves the key starts with the root, which a doubled root does. The hook derives the root from
  the string it is slicing, which makes the slice total. An earlier revision looked the root up in
  `spaces` with a `?? ''` fallback, and `startsWith('')` is universally true, so the fallback
  re-created the bug it was written to prevent.
- **FR-004's "Open folder" label was dropped.** It contradicts the rule `NotificationRow` states and
  justifies for every producer — the message *is* the link — and honouring both would put two anchors
  on one href. Andrew took the call. The invalidation became a mechanism over any `/files` link, so
  file-send and archive notifications get it too, and the link needs no registry row of its own.
- **FR-005's "the primary button keeps its 38 px height" was a false premise.** That button is the
  `Button` primitive at `h-9` — **31.5 px** at this app's 14 px root, in all four DestinationPicker
  dialogs. 38 px is this repo's *mobile touch* pattern, which it has never used. It clears SC 2.5.8
  comfortably, and resizing four dialogs is not this spec's business.
- **FR-005's "Enter still submits from the file-name field only" was false of the dialog**, which has
  no `<form>`, no `onSubmit` and no `onKeyDown`. Enter submits from nowhere, so the criterion could
  not fail whatever the select did.
- **Help over-describes while the flag is off**, accepted: the registry maps whole guides to flags,
  never sentences, and gating either guide would hide the CSV documentation too. The flag ships `true`
  in both the compiled defaults and the published document, so it bites only a deliberate operator.

## What changed from earlier specs?

- **`resultsConversion` is the seventh flag key and the third kind** — neither an area nor a kill
  switch but presentation over one control. The taxonomy in `decisions/browser.md` said five areas
  and one kill switch, which was a complete account of a set that had grown.
- **SPEC-222's owed rows said "no browser surface until SPEC-223"** three times. That is now false:
  the end-to-end conversion is a click, and `owed.md` says so in place.
- **`normalizeCsvName` is gone**, and with it two `query-feature.md` inventory rows that had been
  describing a `query.format.ts` SPEC-185 deleted.

## Verification

Green by **exit code** on the rebased tree: `tsc -b`, both linters, **2489** portal tests,
`npm run build`, `format:check`, **3132** lambda tests at 90.18%, `mypy`, `ruff`, both validators and
`tofu fmt -check -recursive`.

**Three fresh-context review frames, and the third was owed rather than chosen.** The branch replaced
its root-derivation mechanism *after* the first two gates had run, so both had examined code that no
longer existed — `session-rhythm.md`'s replaced-artifact rule. It found a refusal that was
**unreachable** (deleting the whole branch left every test green) and a hole in the new
cross-language gate.

**The same class recurred in all three frames: guards that read as protection but are not.** Two
vacuous tests, a silent `busy` mutation, a tautological golden, a dead fence, a gate with a hole.
Per CLAUDE.md a recurring class calls for a structural change rather than a fourth frame — every
guard added after that point was planted against before it was committed.

**The two-language golden earned its own lesson.** Written the way SPEC-222's `GOLDEN_LINK` was, it
was a tautology in *both* directions: the browser half fed the literal in as the message and asserted
`getByText` on it, true of any string. Changing the plane's wording and its Python golden together
left the browser copy stale with both suites green. The gate now lives on the side that can produce
the sentence — the Python test reads the value between the backticks of the browser's declaration and
compares. A first attempt searched the whole file, which passed with the old wording sitting in a
comment above a constant that said something else.

**The live checks are written and unrun.** The surface shipped, so every one of them is reachable
from a single signed-in sitting with no second account and no CLI — but this session had no browser
connected. `owed.md` records that as its own section, because "nobody has looked yet" is a different
kind of owing from "one account cannot do this".
