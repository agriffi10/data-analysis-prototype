---
type: Decision
title: "An object this plane could copy but could not delete is refused, not archived"
description: "A selection holding a folder named for a reserved root at any depth, such as `alice/projects/archive/`, is refused whole at expansion with the folder named; a file merely called `archive` is untouched."
---

Two rules were each correct alone and disagreed with each other. The code's reserved-folder rule is
anchored at the SPACE ROOT on purpose — ``assert_not_reserved``'s own docstring says
``alice/reports/archive/`` is an ordinary folder the user made. The IAM Deny protecting the same
names cannot be anchored anywhere: ``*`` matches ``/`` in a resource ARN and IAM has no
single-segment wildcard, so ``*/archive/*`` covers every depth.

The gap between them was a real user-facing failure. Archiving ``alice/projects/`` containing
``alice/projects/archive/notes.txt`` would copy every object into Glacier at the 90-day minimum,
write its record, and then fail part way through the deletion with "contact an administrator" — a
full orphaned copy and an escalation, for an ordinarily-named folder.

It is refused at expansion time now, and refused **WHOLE** rather than excluded, which is SPEC-165's
rule: a silent exclusion drops the user's own data out of an archive that reports success. The
message names the folder so the user can rename it. A file merely CALLED ``archive`` is untouched —
the Deny needs a segment after the name, so the rule reads folder segments and not basenames.

## History

### 2026-08-12

- **Settled:** entered the register.
