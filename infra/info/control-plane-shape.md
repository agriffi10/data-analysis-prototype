# The control-plane shape has moved

It is the README of the module that now builds every plane:
[`../modules/control-plane/README.md`](../modules/control-plane/README.md).

This page stays only because two deployed state-machine definitions (`infra/planes/data-quality/`
and `infra/planes/table-builder/`) cite this path inside their ASL `Comment`, and changing that text
would be a definition update on a live machine for the sake of a doc link. Delete it the next time
either definition changes for a real reason.
