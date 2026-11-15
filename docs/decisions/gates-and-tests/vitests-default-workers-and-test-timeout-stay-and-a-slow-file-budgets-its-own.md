---
type: Decision
title: "Vitest's default workers and test timeout stay, and a slow file budgets its own work (2026-11-15)"
description: "**`apps/portal/vite.config.ts` declares `testTimeout: 5_000`, Vitest's default, and leaves `maxWorkers` to scale with the machine.** Measured under parallel load, the defaults failed nothing, a 10 s timeout bought nothing they lacked, and one run capped at half its workers was the slowest in every round. A case whose waits cover real slow work (a lazy editor, statements run through the real workspace) gets its own budget, narrowest first: a wait's `{timeout}`, then the case's or its `describe`'s timeout, or a file's `asyncUtilTimeout` with a restore; and says why. Do NOT raise the suite-wide timeout to quiet a flake: it makes every genuine hang fail later, and a missed signal is fixed by waiting for the value asserted, not by more time."
---

**The question.** Two Vitest cases flaked in full runs while several sessions loaded this 10-core
Mac. Their fixes landed first, each in its own file: one read a value before the effect that writes
it had run, and the other did real work against a 1 s wait and a 5 s case. That left open whether
the suite as a whole needs a different budget. The candidates were capping the worker count, which
lowers contention, and raising the per-test timeout, which absorbs it.

**How it was measured.** On `900c64f5` (`main` with both fixes, 3,735 tests), three arms ran with
the same configuration and differed only in command-line flags: (a) the defaults, which on this
machine run nine workers; (b) `--maxWorkers=50%`, five; (c) `--testTimeout=10000`. Each of eight
loaded rounds started all three at once, so each ran under the other two plus whatever peer sessions
were doing. The one-minute load average read as each round started went from 27.5 to 68.1, and it
includes the previous round's runs winding down. Each arm then ran alone three times, interleaved,
with the load average read before each lone run between 14.6 and 30.0.

| Arm | Loaded runs that failed | Loaded median wall | Lone median wall |
|---|---|---|---|
| (a) defaults | 0 of 8 | 126 s | 54 s |
| (b) workers capped at half | 1 of 8 (two tests) | 150 s | 61 s |
| (c) test timeout 10 s | 0 of 8 | 126 s | 66 s |

**Why the defaults.** The rule set before measuring was the arm with no failures and the smaller cost
to a lone run. (a) and (c) failed nothing in eight rounds and (b) failed once, but eight rounds
cannot tell one failure from none, so the failures decide nothing here. What separates them is
cost. (b) was the slowest run in all eight loaded rounds, by 16 to 34 s, a median about a fifth
longer. (c) changes nothing unless a case runs past 5 s, and its loaded walls were within a second
of (a)'s in seven rounds and 3.4 s in the eighth. That side-by-side match, not the lone runs, is the
evidence it costs nothing. The lone runs are noise for every arm: (a)'s own three ran from 42.9 to
61.6 s, and the lone medians (54, 61 and 66 s) still order the arms the same way. With (a) and (c)
tied, the defaults win on what the longer timeout would hide: a case that hangs fails after 5 s rather
than 10, in every run.

**What was not tested.** (b) capped one run beside two uncapped ones. That cut only its own load, and
left it a smaller share of the processor, so it says nothing about the case a config setting would
create, where every session's runs are capped and contention falls for all of them. That case went
unmeasured because it was not needed: the uncapped arms already failed nothing under this load, and
alone the capped arm was not faster.

**Declared, not inherited.** The timeout the measurement kept is written into the config at its
value, 5 s, because a default is a decision someone else gets to change (the declared-defaults
decision in this area): the reasoning above holds only while the limit is 5 s, and a Vitest upgrade
that moved it would otherwise move this decision silently. `maxWorkers` stays unset on purpose: its
default scales with the machine's cores, the uncapped runs held under this load, and a fixed number
would be a decision about one machine.

**The one failure, and where such failures are fixed.** (b)'s one failing run, in the round read at
load 68.1, was
`routes/areas/query.test.tsx` › "opens one tab with the statement, and nothing more on Back and then
Forward", in both rows of its `describe.each`. Each failed on a 1 s `findBy` for the result grid, not
on the test's limit. Neither a worker cap nor a test timeout widens a wait. Those two waits now carry
their own `{timeout}`, the narrowest form of the per-case budget: a wait that covers real rendering
gets a longer window where it is, a case or a `describe` that does slow work gets a longer limit
(`features/data-explorer/filterByValue.test.tsx` and `queryHistory.test.tsx` give single cases 20 s
and 15 s), and a file whose every case waits on real rendering raises `asyncUtilTimeout` for itself
and restores it, as `features/query/exploreResult.test.tsx` does. A wait that is really a missed
signal, a read before the write, is fixed by waiting for the asserted value, as
`features/data-explorer/openSavedView.test.tsx` does.

**Do NOT** change the suite-wide `testTimeout` or set `maxWorkers` without re-running the three arms,
and for a cap, with every concurrent run capped. Do not raise the RTL `asyncUtilTimeout` globally either: every wait that expects nothing to appear would
then run five times as long, to hide a few slow files. Re-measure if the machine, the worker pool,
or the suite's size changes materially.

## History

### 2026-11-15

- **Decided:** the Next.js arc's orchestrator asked for the three arms to be measured after the two
  flaky files were fixed, choosing the arm with no failures and the smaller lone cost, and stopping
  rather than combining if neither (b) nor (c) reached zero. (a) and (c) reached zero, and the
  defaults stay. The sources review found that the cap had been tested on one run among uncapped
  ones and that eight rounds cannot separate one failure from none; the entry says so.
