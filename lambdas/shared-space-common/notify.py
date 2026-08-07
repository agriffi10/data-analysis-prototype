"""Best-effort notification emit for the shared-space control plane.

The send itself lives once, in ``cpcommon.notify``; this module carried a byte-identical copy
of it until the layers were consolidated. It is re-exported under this module's name so the
seven lifecycle call sites keep their import unchanged.

Same contract as before: a create envelope grouped by username, a logged no-op when the queue
URL is unset, and every error caught and logged so a missed notification cannot change or fail
the surrounding control-plane action. The shared version also accepts an optional link, which
no shared-space emitter passes.

One note, for tests rather than production: the queue URL is read from ``cpcommon.config``,
because that is where the send lives. Terraform sets the same variable either way; a test that
wants notifications on patches that module, which the fakes already do.
"""

from cpcommon.notify import emit_notification

__all__ = ["emit_notification"]
