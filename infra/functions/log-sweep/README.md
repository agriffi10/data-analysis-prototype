# `log-sweep` — the structured-logging sweep's documents

The sweep's trust document (`sweep-trust.json.tftpl`, which carries no Sid, so it is passed rather than
the building block's default), its permissions (`sweep.json.tftpl`) and its producer grant
(`logs-producer.json.tftpl`). The call is `../../function-log-sweep.tf`; the queue, the alarm and
the reasoning for the whole pipeline are [`../../modules/observability/README.md`](../../modules/observability/README.md).
