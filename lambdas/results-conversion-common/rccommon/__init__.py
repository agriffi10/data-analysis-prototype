"""The results-conversion plane's domain layer: its wording, reason codes and key rules.

``cpcommon`` supplies every algorithm — the SQS parse, the trusted actor, the registry read, the
containment rule, the notification skeleton. This package holds only what is this plane's: what
a refusal says, which codes it can return, where a destination may and may not be, and how a
converted file is named. It defines no CAS loop, no lock, no message resolver and no queue
parser, and a test asserts that absence.

Attributes:
  None.
"""
