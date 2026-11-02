---
type: Decision
title: "One image for the whole Lambda fleet, and the sweep that pays for it (SPEC-212)"
description: "**ONE image, and all 86 Lambdas now RUN it** — shared code on `/opt/python`, function modules flat at the task root, **dependencies deliberately in site-packages** so the layout guard is a real set equality. **Shared code is what `lambdas/*-common/` HOLDS**, no list to be missing from, and a directory that is neither that nor a function is REFUSED, never defaulted. One shared task root is the new hazard: a duplicate name does not collide, it **silently wins** for the whole fleet, so collisions and shadowing are asserted **against the built image**. The import sweep runs through the runtime's **own bootstrap** — `--entrypoint python` omits `/opt/python`, and a reconstructed path that is a superset passes what production fails — and its expected count comes from **Terraform**, never from the same rule the sweep uses, or renaming a handler drops **both** sides and agrees. **The fleet's membership is `fleet.py`, read from the Terraform SOURCES** — a `tofu output` is last-applied state and the deploy workflows race on the push adding a function. No `.github/` list names functions."
---

Eighty-six functions ship as zips with ten shared layers attached in a literal order. Everything
hard about that arrangement is hard for one reason: **what a function can import is decided at
deploy time, by a join between two JSON tables, and is observable nowhere else.** A missing layer is
a `ModuleNotFoundError` at the next cold start, in production, behind a green suite — which
happened, and lasted nine days.

The image replaces the join with an artefact. Dependencies installed once, shared code copied once,
every function running the same image with a different command. What a function can import becomes
a property of something you can pull and run.

**The layout reproduces the zip and the layer exactly, and that is measurable rather than hopeful.**
Shared code lands on `/opt/python`, function modules at `${LAMBDA_TASK_ROOT}` with the function
directory's own level stripped. Measured against the base image through its bundled Runtime
Interface Emulator: the container runtime's bootstrap puts `/var/task`,
`/opt/python/lib/python3.12/site-packages` and `/opt/python` on `sys.path` **with no `PYTHONPATH`
involved**, so both a package and a flat module resolve and no import statement changes.

**Dependencies are NOT on `/opt/python`, and that is the one deliberate divergence.** A layer today
mixes its package with its pip-installed dependencies in one directory; reproducing that would make
"the set of packages under `/opt/python` equals what the shared sources publish" false by
construction, and the guard would decay into a hand-maintained dependency list. (That guard read
"the set the layer table declares" until SPEC-214 deleted the table; it is the same set equality
against the `lambdas/*-common/` directories.) The cost is that
repository code now sits **ahead** of the dependencies on the search path, which a layer never did —
so a third guard asserts no repository module shadows an installed one.

**One task root for eighty-six functions is a hazard no zip had.** Every function's modules share
`/var/task`, and the runtime searches it before `/opt/python`. Two directories contributing the same
path do not collide — one silently wins, for the whole fleet. A module named `config.py` would
shadow the shared-space layer's `config` for eleven verbs. Both are measured empty today and both
are asserted **against the built image**: an absence asserted against a source tree proves nothing
about an artefact, which is the same reason the arc exists at all.

**The image is strictly wider than the zip, and the sweep is what pays for it — not the packaging.**
Stated rather than glossed: every function can now import every shared-space flat module. An AST
sweep over the **function** directories forbids it outside that plane, counting attribute-style
usage as well as `from x import y`, with an exemption list of exact paths. The population is
function directories rather than every directory under `lambdas/`, because the layer's own source
imports its own modules and sweeping it invites the wrong repair.

**Two things the matrix had to get right, both measured rather than reasoned.**

**It runs the imports through the runtime's own bootstrap.** `docker run --entrypoint python` gives
a `sys.path` with neither `/opt/python` nor its site-packages on it, so a sweep taken that way must
rebuild the path — and a rebuilt path that is a **superset** of the real one passes an import that
production fails. That is this arc's own failure mode, rebuilt by the tool meant to prevent it. The
sweep is instead invoked as a handler through the emulator, reads its own live `sys.path`, and hands
it to one subprocess per module; the subprocess path comes back **identical**, so there is nothing
to reconstruct and nothing to police.

**A count compared with itself is not a guard.** The first version derived the expected number of
handlers the same way the image-side sweep did — a module defining a top-level `handler`. Renaming
one removed it from **both** sides, the two numbers agreed at 85, and a planted mutation that broke
a function's entry point passed the whole matrix. ~~The expectation now comes from the deploy
table, which is maintained separately.~~ **SPEC-214 deleted both tables, and the instruction was
honoured rather than dropped:** the expected count comes from `lambdas/fleet.py`, which reads the
fleet out of the Terraform that declares it — still a derivation maintained separately from the
tree, and still **not** the sweep. The *shared-code* half of the expectation had no such
independent source and does not pretend to one: it and the assembler both read
`assemble.shared_layout` now, and what is independent of the assembler is the fleet-wide handler
import inside the artefact.

**The fences.**

- **The container runs `--read-only` with a tmpfs `/tmp`**, which is the filesystem Lambda gives it.
  Not only fidelity: importing eighty-six modules writes bytecode beside every one of them, so on a
  writable root the sweep manufactures the `__pycache__` offenders it then reports.
- **The emulator serves one invocation at a time.** A readiness probe that posts to the invocation
  endpoint starts the real sweep and the retry collides with it — `ReserveFailed`, and the emulator
  panics. Wait for any HTTP response on any path instead.
- **The base image has no `find` and no `xargs`.** A `RUN find … -delete` prune exits 127. The
  assembler is Python, which is the one tool a Python runtime image is guaranteed to have — and
  being a module rather than a shell line is what lets the layout tests import the same definition
  the build uses.
- **The build context is the repository root with `lambdas/Dockerfile.dockerignore`.** BuildKit
  reads a Dockerfile-specific ignore file in preference to the context root's; the root file
  excludes `lambdas` on purpose, so that the SPA's build — which asserts its absence — keeps working.

Shared code is what `lambdas/*-common/` holds, with no list to be missing from, and a directory that is neither that nor a function is refused, never defaulted. The fleet's membership is `fleet.py`, read from the Terraform sources, because a `tofu output` is last-applied state and the deploy workflows race on the push adding a function. No `.github/` list names functions.

## History

### 2026-08-28

- **Settled:** SPEC-212.
