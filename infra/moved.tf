# ── State migrations ─────────────────────────────────────────────────────────
# A refactor that changes a resource's address adds a `moved` block here, so the change is a
# rename in state, not a destroy and a create. Delete a block once every state that predates it
# has applied it: a block whose `from` is not in state is tolerated silently, so a stale one
# proves nothing and only misleads the next reader.
