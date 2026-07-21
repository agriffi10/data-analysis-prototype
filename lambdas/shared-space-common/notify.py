"""Best-effort notification emit for the shared-space control plane.

SPEC-125: the SEND itself now lives once, in ``cpcommon.notify.emit_notification`` — this
module carried a byte-identical copy of it until then. It is re-exported under this
module's name so the seven SPEC-061 lifecycle call sites keep their
``from notify import emit_notification`` import unchanged.

Same contract as before: a ``create`` envelope with MessageGroupId=username; a logged no-op
when the queue URL is unset; catches and logs everything, never raises — a missed
notification must not change or fail the surrounding control-plane action. The cpcommon
version also accepts an optional ``link``, which no shared-space emitter passes.

ONE NOTE, for tests rather than production: the queue URL is now read from
``cpcommon.config.NOTIFICATIONS_QUEUE_URL``, because that is where the send lives.
Terraform sets the same env var either way; a test that wants notifications ON patches
``cpcommon.config`` (``fakes.install()`` already does).
"""

from cpcommon.notify import emit_notification

__all__ = ["emit_notification"]
