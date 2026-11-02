---
type: Decision
title: "A resolved space carries its own IDENTITY, not only its location (SPEC-191)"
description: "A resolved space carries its `kind` and `name` as well as `{bucket, root}`, riding from the resolver where the claim was authorized; a later verb must not re-read them off the request body."
---

`authz` resolved a space to `{bucket, root}`. A root is not a name and a bucket is not a kind, and
the difference surfaces only at the far end of the plane: the producer has to say which space a run
touched and link into it, and a re-submit built from that notification needs the **source** space,
which no absolute key contains.

Left as it was, `kind` and `name` reached the summary as `None`, the link builder refused to mint
anything, and **every notification shipped with no link at all** while the payload carried nulls
where a re-submit's spaces belong — with a full green suite, because every fixture in the notifier's
tests hand-wrote the shape it wanted. That is the test-that-cannot-fail class: the fixture asserts a
shape the producer does not emit.

They ride from the resolver rather than being re-read off the request, because that is the point at
which the claim has been **authorized** — a later verb reading the untrusted body would be naming a
space the actor may never have been granted. The guard against the fixture problem recurring is one
test that builds the notifier's input from the real `authorize_source` and the real finaliser
instead of a literal.

## History

### 2026-08-17

- **Settled:** SPEC-191.
