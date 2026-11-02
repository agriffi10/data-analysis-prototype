---
type: Decision
title: "A citation is a promise, and the ratchet is exact in both directions (2026-09-08)"
description: "**Naming a test in a comment is a PROMISE, and the doc gate now holds you to it.** A comment saying some named guard reads this number is worse than a stale comment when the guard is gone: it talks the next reader out of the check they were about to make. Citations in `.py`, `.tf`, `.tftpl`, `.ts`, `.tsx` and `.md` are resolved against the suite — in backticks, as a filename, or BARE inside a comment, the form a backticks-only reader cannot see and the one 11 of this repo's citations use. Specs, delivery docs and test modules are **not** judged, for reasons the checker states; a citation there is on you. Two consequences that apply green and fail later. **Deleting a test silently breaks every doc that cites it**, so the sweep for its name comes before the deletion, not after CI. And **a past-tense record of a retirement must contain the word \"retired\"** within a hundred characters of the name — that is the whole exemption, deliberately not \"deleted\" or \"removed\", which this repo uses constantly in live claims about deletion semantics. A record worded any other way reddens a ratchet whose end state is zero, and the answer is to reword the sentence rather than to raise the number."
---

Comments and docs across this repo name a test as the thing enforcing a claim beside them. One
commit deleted 57 files, 53 of them test modules, and nothing swept the references: 46 such
citations were left standing, seven of them in `locals.tf` comments asserting that a named test
reads a cap back and would fail the build if it were raised. No such test existed. That is worse
than a stale comment, because it discourages precisely the check a careful reader was about to
make.

`check_test_citations` resolves every citation it judges against the suite, in three grammars. The
bare-in-a-comment form is the one that matters: it carries 11 of the 255 judged sites and every
Terraform citation this work existed to repair, and a backticks-only reader sees none of them.

**The ratchet is EXACT, not a ceiling, and that is the load-bearing choice.** A ceiling can only
see the count rise. Measured on this gate, adding one filename to the excluded set dropped eight
findings and stayed green; widening the retirement window to the whole file dropped seventeen. Both
are lost detection, and lost detection is invisible to a ceiling forever. With an exact ratchet a
fall is also an error, which forces the author to look at what stopped being reported and say so by
moving the number. The cost is real — an unrelated PR that deletes a file carrying a stale citation
must lower the constant — and it is the price of the gate being able to see its own blind spot.

Two things it cannot see, recorded rather than papered over. A citation resolves by NAME, globally,
so one plane's guard satisfies another plane's identical citation; the archive and file-send caps
collide exactly this way, which is why their restored guards carry plane-qualified names. And a
module deleted and recreated as a stub keeps every citation to it green — file-ops is in that state
today, which is why no name-resolution gate can see its false claims.

The exemption is a retirement record: the word "retired" within 100 characters of the name, looking
both ways. Deliberately not "deleted" or "removed" — this repo uses those constantly in live claims
about deletion semantics, and admitting them would exempt three of the findings the gate reports.
The house habit is inconsistent enough to matter: of the retirement records in the judged tree, two
are worded "deleted" and will need rewording rather than restoring. A record of a guard that never
existed has no truthful rewording at all, and the one instance sits in the unjudged test-module
tier.

The doc gate judges the file types `TEST_CITATION_SCAN` names in `scripts/validate_docs.py`. Specs, delivery docs and test modules are not judged, for reasons the checker states; a citation there is on you. Deleting a test silently breaks every doc that cites it, so the sweep for its name comes before the deletion, not after CI. A retirement record worded any other way reddens a ratchet whose end state is zero, and the answer is to reword the sentence rather than to raise the number.

## History

### 2026-09-08

- **Settled:** entered the register.
