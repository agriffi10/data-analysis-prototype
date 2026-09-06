"""The results-conversion plane's domain layer: its wording, reason codes and key rules.

``cpcommon`` supplies every algorithm — the SQS parse, the trusted actor, the registry read, the
containment rule, the notification skeleton. This package holds only what is this plane's: what
a refusal says, which codes it can return, where a destination may and may not be, and how a
converted file is named. It defines no CAS loop, no lock, no message resolver and no queue
parser, and a test asserts that absence.

**Importing this package registers the plane's reason codes**, and that is structural rather
than tidy. ``TerminalError`` validates its reason at the raise site against the registered
table, and importing ``messages`` is what registers them — so a module that raises without it
raises ``ValueError`` instead, and only when nothing else in the process happened to import
``messages`` first. Two modules carried a ``# noqa: F401`` import to arrange that, and a third
(``paths``, which raises ten times) did not and worked only because every caller also imported
``authz``. One import here retires the whole class: there is no longer a per-module thing to
remember, and the failure it prevented cannot come back one module at a time.

Attributes:
  None.
"""

from . import messages as _messages  # noqa: F401
