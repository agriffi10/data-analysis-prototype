"""User-facing data-quality notification text (SPEC-114 fills this in).

Stubbed namespace (SPEC-108 skeleton). Will register this domain's reason codes with
cpcommon.messages (SPEC-107 FR-005) — giving a domain-scoped resolver over the shared
base table, and making every code a valid TerminalError reason at raise time — and hold
the verdict/top-issues wording. Raw AWS/Athena text never reaches a notification body
(SPEC-106): it stays in CloudWatch and the SFN execution history.
"""
